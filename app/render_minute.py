"""Trust income distribution minute rendering."""

from __future__ import annotations

import re
from typing import Any

from .word_ooxml import (
    ensure_working_template,
    fill_tables_by_header,
    get_field_value,
    load_fieldmap,
    package_text,
    remove_paragraphs_matching,
    remove_unresolved_placeholders,
    replace_placeholders,
    select_branch,
    stringify_value,
)


def render_minute(
    data: dict[str, Any],
    *,
    distribution_instructions: dict[str, Any] | None = None,
    approved_checklist: dict[str, Any] | None = None,
    output_options: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    distribution_instructions = distribution_instructions or {}
    trust_type = str(get_field_value(data, "trust.type", "unsure")).lower()
    if trust_type not in {"discretionary", "unit"}:
        raise ValueError(f"Unsupported trust type for minute rendering: {trust_type}")

    is_corporate = bool(get_field_value(data, "trustee.is_corporate", False))
    director_count = len(get_field_value(data, "trustee.directors", []) or [])
    trustee_count = _trustee_count(data)
    branch = _branch_label(is_corporate=is_corporate, director_count=director_count, trustee_count=trustee_count)

    template = ensure_working_template("unit" if trust_type == "unit" else "discretionary")
    fieldmap_name = "unit_minute.fieldmap.json" if trust_type == "unit" else "discretionary_minute.fieldmap.json"
    fieldmap = load_fieldmap(fieldmap_name)

    docx = select_branch(template, branch)
    render_data = _merged_render_data(data, distribution_instructions)
    docx = replace_placeholders(docx, _template_variable_replacements(render_data, fieldmap.get("fields", [])))
    docx = _remove_unused_signature_blocks(docx, is_corporate=is_corporate, director_count=director_count, trustee_count=trustee_count)
    docx = replace_placeholders(docx, _visible_placeholder_replacements(render_data, distribution_instructions, trust_type))
    if trust_type == "unit":
        unit_rows = _unit_holding_rows(render_data)
        docx = fill_tables_by_header(docx, ["Unitholder", "Ownership percentage"], unit_rows)
        docx = fill_tables_by_header(docx, ["Unitholders", "Proportion"], unit_rows)
    docx = remove_unresolved_placeholders(docx, _mapped_placeholders_to_remove(fieldmap, distribution_instructions))

    text = package_text(docx)
    unresolved = [placeholder for placeholder in _mapped_placeholders_to_remove(fieldmap, distribution_instructions) if placeholder in text]
    summary = {
        "trust_name": get_field_value(render_data, "trust.name"),
        "trust_type": trust_type,
        "template_branch": branch,
        "template_insert_points": _template_insert_points(trust_type),
        "clause_fields": {
            "vesting": get_field_value(render_data, "trust.vesting.clause_ref"),
            "income_definition": get_field_value(render_data, "income.definition_clause_ref"),
            "distribution_power": get_field_value(render_data, "income.distribution_power_clause_ref"),
            "streaming": get_field_value(render_data, "income.streaming_clause_ref"),
            "capital": get_field_value(render_data, "capital.determination_clause_ref"),
            "method": get_field_value(render_data, "distribution.method_clause_ref"),
        },
        "unresolved_placeholders": unresolved,
    }
    return docx, summary


def _mapped_placeholders_to_remove(fieldmap: dict[str, Any], distribution: dict[str, Any]) -> list[str]:
    retain = set(fieldmap.get("placeholder_policy", {}).get("deliberately_retained", []))
    if not distribution.get("income_year"):
        retain.add("YEAR")
    if not distribution.get("items"):
        retain.update({
            "INDIVIDUAL A",
            "INDIVIDUAL B",
            "COMPANY A Pty Ltd",
            "TRUSTEE A, in their capacity as trustee for the TRUST A",
        })
    return [
        placeholder
        for placeholder in fieldmap.get("placeholder_policy", {}).get("mapped", [])
        if placeholder not in retain
    ]


def _template_variable_replacements(data: dict[str, Any], fields: list[dict[str, Any]]) -> dict[str, Any]:
    replacements: dict[str, Any] = {}
    visible_or_repeat_fields = {
        "distribution.income_year",
        "distribution.resolution_date",
        "distribution.items",
        "trustee.directors",
        "trustee.individual_trustees",
    }
    for field in fields:
        path = field.get("field_path")
        if not path or path in visible_or_repeat_fields:
            continue
        value = get_field_value(data, path, "")
        if value in (None, "") or value == []:
            continue
        replacements[f"{{{{{path}}}}}"] = value
    return replacements


def _branch_label(*, is_corporate: bool, director_count: int, trustee_count: int) -> str:
    if is_corporate:
        return "corporate_multi_director" if director_count >= 2 else "corporate_sole_director"
    return "individual_multi_trustee" if trustee_count >= 2 else "individual_sole_trustee"


def _trustee_count(data: dict[str, Any]) -> int:
    trustees = get_field_value(data, "trustee.individual_trustees", None)
    if isinstance(trustees, list) and trustees:
        return len(trustees)
    name = stringify_value(get_field_value(data, "trustee.name", ""))
    if not name:
        return 1
    return max(1, len([part for part in name.split(";") if part.strip()]))


def _merged_render_data(data: dict[str, Any], distribution_instructions: dict[str, Any]) -> dict[str, Any]:
    merged = dict(data)
    distribution = dict(data.get("distribution", {}))
    for key in ("income_year", "resolution_date", "method", "items", "balance_to_named_beneficiary"):
        if key in distribution_instructions:
            existing = distribution.get(key)
            if isinstance(existing, dict) and "value" in existing:
                existing = {**existing, "value": distribution_instructions[key], "confidence": "high"}
            else:
                existing = distribution_instructions[key]
            distribution[key] = existing
    merged["distribution"] = distribution
    return merged


def _visible_placeholder_replacements(data: dict[str, Any], distribution: dict[str, Any], trust_type: str) -> dict[str, Any]:
    income_year = distribution.get("income_year") or get_field_value(data, "distribution.income_year", "") or "YEAR"
    resolution_date = distribution.get("resolution_date") or get_field_value(data, "distribution.resolution_date", "") or "______________________"
    trustee_name = get_field_value(data, "trustee.name", "")
    acn = get_field_value(data, "trustee.acn", "")
    trustee_names = _trustee_names(data)
    directors = get_field_value(data, "trustee.directors", []) or []
    director_names = [item.get("name", "") if isinstance(item, dict) else str(item) for item in directors]
    party_label = "Unitholders" if trust_type == "unit" else "Beneficiaries"

    replacements = {
        "Trust Name": get_field_value(data, "trust.name", ""),
        "YEAR": income_year,
        "______________________": resolution_date,
        "Est Date": get_field_value(data, "trust.deed_date", ""),
        "Trustee 1": trustee_names[0] if trustee_names else trustee_name,
        "XXX XXX XXX": acn,
        "Settlor 1": get_field_value(data, "trust.settlor.name", ""),
        "InitialUnitholder 1": get_field_value(data, "trust.initial_unitholder.name", ""),
        "V Date": get_field_value(data, "trust.vesting.date", ""),
        "clause 1.33": _clause_text(data, "trust.vesting.clause_ref"),
        "clause 1.29": _clause_text(data, "trust.vesting.clause_ref"),
        "Clause 9": _clause_text(data, "income.distribution_power_clause_ref").capitalize(),
        "clause 5.1.3": _clause_text(data, "income.distribution_power_clause_ref"),
        "clause 1.12": _clause_text(data, "income.definition_clause_ref"),
        "clause 1.24.2": _clause_text(data, "income.definition_clause_ref"),
        "clause 1.25.2": _clause_text(data, "income.definition_clause_ref"),
        "clause 11.5": _clause_text(data, "income.streaming_clause_ref"),
        "clause 5.2.4": _clause_text(data, "income.streaming_clause_ref"),
        "clause 1.4": _clause_text(data, "beneficiaries.definition_clause_ref"),
        "clause 1.26": _clause_text(data, "unitholders.register_clause_ref"),
        "INDIVIDUAL A": _party_name(distribution, 0, party_label),
        "INDIVIDUAL B": _party_name(distribution, 1, party_label),
        "COMPANY A Pty Ltd": _party_name(distribution, 2, party_label),
        "TRUSTEE A, in their capacity as trustee for the TRUST A": _party_name(distribution, 3, party_label),
    }
    for index in range(6):
        replacements[f"Director {index + 1}"] = director_names[index] if index < len(director_names) else ""
        replacements[f"Trustee {index + 1}"] = trustee_names[index] if index < len(trustee_names) else ""
        replacements[f"comma{index + 1}"] = ", " if index < len(trustee_names) - 1 else ""
    return replacements


def _template_insert_points(trust_type: str) -> list[str]:
    party_label = "unitholders" if trust_type == "unit" else "beneficiaries"
    return [
        "income year",
        "resolution date",
        party_label,
        "distribution proportions",
        "income classes, if any",
    ]


def _party_name(distribution: dict[str, Any], index: int, fallback_label: str) -> str:
    items = distribution.get("items") or []
    if index < len(items):
        item = items[index]
        return str(item.get("name") or item.get("beneficiary") or item.get("unitholder") or "")
    defaults = [
        "INDIVIDUAL A",
        "INDIVIDUAL B",
        "COMPANY A Pty Ltd",
        "TRUSTEE A, in their capacity as trustee for the TRUST A",
    ]
    if index < len(defaults):
        return defaults[index]
    if index == 0:
        return f"[insert {fallback_label.lower()}]"
    return ""


def _clause_text(data: dict[str, Any], path: str) -> str:
    value = stringify_value(get_field_value(data, path, ""))
    return value if value else "Clause not found"


def _trustee_names(data: dict[str, Any]) -> list[str]:
    trustees = get_field_value(data, "trustee.individual_trustees", None)
    if isinstance(trustees, list) and trustees:
        return [item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in trustees]
    name = stringify_value(get_field_value(data, "trustee.name", ""))
    if ";" in name:
        return [part.strip() for part in name.split(";") if part.strip()]
    return [name] if name else []


def _unit_holding_rows(data: dict[str, Any]) -> list[list[str]]:
    holdings = get_field_value(data, "unitholders.holdings", []) or []
    rows: list[list[str]] = []
    total_units = 0.0
    parsed_units: list[float | None] = []
    for holding in holdings:
        units_text = ""
        if isinstance(holding, dict):
            units_text = stringify_value(holding.get("units") or holding.get("number_of_units") or holding.get("value"))
        number = _parse_number(units_text)
        parsed_units.append(number)
        if number is not None:
            total_units += number
    for index, holding in enumerate(holdings):
        if isinstance(holding, dict):
            name = stringify_value(holding.get("name") or holding.get("unitholder") or holding.get("holder"))
            explicit_percentage = stringify_value(holding.get("percentage") or holding.get("ownership_percentage") or holding.get("proportion"))
            units = stringify_value(holding.get("units") or holding.get("number_of_units") or holding.get("value"))
        else:
            name = stringify_value(holding)
            explicit_percentage = ""
            units = ""
        if explicit_percentage:
            proportion = explicit_percentage
        elif parsed_units[index] is not None and total_units:
            proportion = f"{parsed_units[index] / total_units:.2%}"
        else:
            proportion = units
        rows.append([name, proportion])
    return rows


def _parse_number(value: str) -> float | None:
    cleaned = re.sub(r"[^0-9.]", "", value)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _remove_unused_signature_blocks(docx: bytes, *, is_corporate: bool, director_count: int, trustee_count: int) -> bytes:
    patterns = []
    if is_corporate:
        for index in range(max(1, director_count) + 1, 7):
            patterns.append(rf"\bDirector\s+{index}\b")
    else:
        for index in range(max(1, trustee_count) + 1, 7):
            patterns.append(rf"\bTrustee\s+{index}\b")
    return remove_paragraphs_matching(docx, patterns)
