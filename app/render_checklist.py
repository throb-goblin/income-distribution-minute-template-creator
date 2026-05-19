"""CSV-backed checklist rendering for chat review and final DOCX output."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Callable

from .word_ooxml import (
    ROOT,
    build_landscape_table_docx,
    get_field_value,
    package_text,
    stringify_value,
)


CHECKLIST_CSV = ROOT / "Trust Review Checklist.csv"
CHECKLIST_HELPER_MAP = ROOT / "templates" / "fieldmaps" / "checklist_helper_map.json"
CLAUSE_NOT_FOUND = "Clause not found"
NOT_FOUND = "Not found"
HEADERS = ["Item", "Relevant clause(s)", "Extracted detail", "Status"]
CSV_HEADERS = ["row_id", "Item", "Applies to"]


RowBuilder = Callable[[dict[str, Any]], tuple[str, str]]


def render_checklist(data: dict[str, Any], *, approved: bool = False) -> tuple[bytes, dict[str, Any]]:
    rows = build_checklist_rows(data, status_override="Approved" if approved else None)
    docx = build_landscape_table_docx(HEADERS, [[row[h] for h in HEADERS] for row in rows], title="Trust Review Checklist")
    summary = {
        "trust_name": get_field_value(data, "trust.name"),
        "trust_type": get_field_value(data, "trust.type"),
        "rows_populated": len(rows),
        "status_counts": _status_counts(rows),
        "not_found_clause_fields": _not_found_clause_fields(rows),
        "unresolved_issues": data.get("issues", []),
        "raw_placeholder_count_after_render": _raw_placeholder_count(docx),
        "checklist_markdown": render_checklist_markdown(data),
    }
    return docx, summary


def render_checklist_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Trust Review Checklist",
        "",
        "| Item | Relevant clause(s) | Extracted detail | Status |",
        "| --- | --- | --- | --- |",
    ]
    for row in build_checklist_rows(data):
        lines.append(
            f"| {_md(row['Item'])} | {_md(row['Relevant clause(s)'])} | {_md(row['Extracted detail'])} | {_md(row['Status'])} |"
        )
    return "\n".join(lines)


def build_checklist_rows(data: dict[str, Any], *, status_override: str | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    helper_rows = {row["row_id"]: row for row in _load_helper_rows()}
    for template_row in _load_csv_rows():
        row_id = template_row["row_id"]
        item = template_row["Item"]
        row_map = helper_rows.get(row_id, {"row_id": row_id, "item": item, "builder": "simple"})
        if _row_applies(data, row_map, template_row):
            clause, detail = _row_values(data, row_map)
            if clause == CLAUSE_NOT_FOUND:
                detail = CLAUSE_NOT_FOUND
        else:
            clause, detail = "", "Not applicable"
        status = status_override or _status(clause, detail)
        rows.append({
            "Item": item,
            "Relevant clause(s)": clause,
            "Extracted detail": detail,
            "Status": status,
        })
    return rows


def _row_values(data: dict[str, Any], row_map: dict[str, Any]) -> tuple[str, str]:
    builder_name = row_map.get("builder", "simple")
    if builder_name == "simple":
        return _simple_value(data, row_map)
    builder = CUSTOM_BUILDERS.get(builder_name)
    if builder:
        return builder(data)
    return "", NOT_FOUND


def _load_csv_rows() -> list[dict[str, str]]:
    text = _read_text(CHECKLIST_CSV)
    reader = csv.DictReader(text.splitlines())
    rows = []
    for row in reader:
        item = (row.get("Item") or "").strip()
        rows.append({
            "row_id": (row.get("row_id") or _slug(item)).strip(),
            "Item": item,
            "Applies to": (row.get("Applies to") or "all").strip(),
        })
    return rows


def _load_helper_rows() -> list[dict[str, Any]]:
    helper_map = json.loads(CHECKLIST_HELPER_MAP.read_text(encoding="utf-8"))
    return helper_map.get("rows", [])


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _simple_value(data: dict[str, Any], row_map: dict[str, Any]) -> tuple[str, str]:
    clause_paths = tuple(row_map.get("clause_paths") or [])
    detail_path = row_map.get("detail_path") or ""
    clause = _clauses(data, clause_paths)
    detail = _detail(data, detail_path) if detail_path else NOT_FOUND
    return clause, detail


def _row_applies(data: dict[str, Any], row_map: dict[str, Any], template_row: dict[str, str]) -> bool:
    applies_to = (template_row.get("Applies to") or row_map.get("applies_to") or "all").strip().lower()
    if applies_to in {"", "all"}:
        return True
    trust_type = str(get_field_value(data, "trust.type", "") or "").strip().lower()
    is_corporate = get_field_value(data, "trustee.is_corporate")
    if applies_to == "unit":
        return trust_type != "discretionary"
    if applies_to == "discretionary":
        return trust_type != "unit"
    if applies_to == "corporate":
        return is_corporate is not False
    if applies_to == "individual":
        return is_corporate is not True
    return True


def _trustee(data: dict[str, Any]) -> tuple[str, str]:
    name = _detail(data, "trustee.name")
    acn = _detail(data, "trustee.acn")
    if acn != NOT_FOUND and name != NOT_FOUND:
        return "", f"{name} ACN {acn}"
    return "", name


def _trustee_type(data: dict[str, Any]) -> tuple[str, str]:
    is_corporate = get_field_value(data, "trustee.is_corporate")
    if is_corporate is True:
        return "Schedule and/or Company Profile", "Corporate Trustee"
    if is_corporate is False:
        return "Schedule and/or Company Profile", "Individual Trustee"
    return "Schedule and/or Company Profile", NOT_FOUND


def _directors(data: dict[str, Any]) -> tuple[str, str]:
    directors = _people(data, "trustee.directors")
    secretary = _people(data, "trustee.secretary")
    parts = []
    if directors:
        parts.append(f"Directors: {directors}")
    if secretary:
        parts.append(f"Secretary: {secretary}")
    return "-", "; ".join(parts) if parts else NOT_FOUND


def _shareholders(data: dict[str, Any]) -> tuple[str, str]:
    return "-", _people(data, "trustee.shareholders") or NOT_FOUND


def _amendments(data: dict[str, Any]) -> tuple[str, str]:
    if get_field_value(data, "deed_history.amendment_noted") is True:
        amendments = get_field_value(data, "deed_history.amendments", []) or []
        return "", stringify_value(amendments) or "Amendment reference noted; review supplied documents."
    return "", "None provided or apparent"


def _appointors_guardians(data: dict[str, Any]) -> tuple[str, str]:
    appointors = _people(data, "appointor_guardian.appointors")
    guardians = _people(data, "appointor_guardian.guardians")
    detail = "; ".join(part for part in (f"Appointors: {appointors}" if appointors else "", f"Guardians: {guardians}" if guardians else "") if part)
    return "", detail or NOT_FOUND


def _unit_holdings(data: dict[str, Any]) -> tuple[str, str]:
    if str(get_field_value(data, "trust.type", "") or "").lower() != "unit":
        return "", "Not applicable"
    return _clauses(data, ("unitholders.register_clause_ref",)), _detail(data, "unitholders.holdings")


def _capital_power(data: dict[str, Any]) -> tuple[str, str]:
    clause = _clauses(data, ("capital.determination_clause_ref", "capital.advancement_clause_ref"))
    detail = _join_nonempty(_detail(data, "capital.determination_clause_ref"), _detail(data, "capital.advancement_clause_ref"))
    return clause, detail


def _amendment_power(data: dict[str, Any]) -> tuple[str, str]:
    clause = _clauses(data, ("amendment_review.power_clause_ref",))
    detail = _join_nonempty(
        _detail(data, "amendment_review.power_clause_ref"),
        f"Consent required: {_detail(data, 'amendment_review.consent_required')}",
        f"Other requirements: {_detail(data, 'amendment_review.other_requirements')}",
    )
    return clause, detail


def _amend_income_definition(data: dict[str, Any]) -> tuple[str, str]:
    return _amendment_need(data, "income.definition_clause_ref", "Income definition found.")


def _amend_characterisation(data: dict[str, Any]) -> tuple[str, str]:
    if _has_value(data, "income.determination_power_clause_ref") or _has_value(data, "capital.determination_clause_ref"):
        return "", "No - income/capital characterisation power found."
    return "", CLAUSE_NOT_FOUND


def _amend_streaming(data: dict[str, Any]) -> tuple[str, str]:
    return _amendment_need(data, "income.streaming_clause_ref", "Income streaming/classification power found.")


def _execution_layout(data: dict[str, Any]) -> tuple[str, str]:
    is_corporate = bool(get_field_value(data, "trustee.is_corporate", False))
    director_count = len(get_field_value(data, "trustee.directors", []) or [])
    trustee_name = _detail(data, "trustee.name")
    if is_corporate:
        layout = "Corporate trustee - multi-director execution" if director_count >= 2 else "Corporate trustee - sole-director execution"
    else:
        trustee_count = max(1, len([part for part in trustee_name.split(";") if part.strip()])) if trustee_name != NOT_FOUND else 1
        layout = "Individual trustees - multi-trustee execution" if trustee_count >= 2 else "Individual trustee - sole-trustee execution"
    return "", layout


def _amendment_need(data: dict[str, Any], path: str, found_text: str) -> tuple[str, str]:
    if _has_value(data, path):
        return "", f"No - {found_text}"
    return "", CLAUSE_NOT_FOUND


def _detail(data: dict[str, Any], path: str) -> str:
    value = stringify_value(get_field_value(data, path, ""))
    return value if value else NOT_FOUND


def _clauses(data: dict[str, Any], paths: tuple[str, ...]) -> str:
    values = []
    for path in paths:
        value = stringify_value(get_field_value(data, path, ""))
        if value:
            values.append(value)
    return "; ".join(dict.fromkeys(values)) if values else (CLAUSE_NOT_FOUND if paths else "")


def _has_value(data: dict[str, Any], path: str) -> bool:
    value = _detail(data, path)
    return value.strip().lower() not in {"", NOT_FOUND.lower(), "none", "unknown", "unsure", "null", CLAUSE_NOT_FOUND.lower()}


def _people(data: dict[str, Any], path: str) -> str:
    values = get_field_value(data, path, []) or []
    return "; ".join(item.get("name", stringify_value(item)) if isinstance(item, dict) else str(item) for item in values)


def _join_nonempty(*values: str) -> str:
    parts = [value for value in values if value and NOT_FOUND not in value]
    return "; ".join(parts) if parts else NOT_FOUND


def _status(clause: str, detail: str) -> str:
    if detail in {NOT_FOUND, ""}:
        return "Review"
    if detail == CLAUSE_NOT_FOUND:
        return "Review"
    if CLAUSE_NOT_FOUND in clause:
        return "Review"
    if "Review" in detail:
        return "Review"
    return "For approval"


def _status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["Status"]] = counts.get(row["Status"], 0) + 1
    return counts


def _not_found_clause_fields(rows: list[dict[str, str]]) -> list[str]:
    return [row["Item"] for row in rows if row["Relevant clause(s)"] == CLAUSE_NOT_FOUND]


def _raw_placeholder_count(docx: bytes) -> int:
    text = package_text(docx)
    return len(re.findall(r"\[[^\]]+\]", text))


def _md(value: Any) -> str:
    text = stringify_value(value)
    return text.replace("\n", " ").replace("|", "\\|")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


CUSTOM_BUILDERS: dict[str, RowBuilder] = {
    "amendments": _amendments,
    "trustee": _trustee,
    "trustee_type": _trustee_type,
    "directors": _directors,
    "shareholders": _shareholders,
    "appointors_guardians": _appointors_guardians,
    "unit_holdings": _unit_holdings,
    "capital_power": _capital_power,
    "amendment_power": _amendment_power,
    "amend_income_definition": _amend_income_definition,
    "amend_characterisation": _amend_characterisation,
    "amend_streaming": _amend_streaming,
    "execution_layout": _execution_layout,
}
