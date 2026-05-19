"""Inventory source Word templates as OOXML packages.

Usage:
    python scripts/inventory_templates.py
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.word_ooxml import (  # noqa: E402
    NS,
    SOURCE_DIR,
    FIELDMAP_DIR,
    detect_manual_page_break_branches,
    element_text,
    extract_tables,
    normalise_space,
    package_text,
)


KNOWN_PLACEHOLDERS = [
    "Trust Name",
    "Trustee 1",
    "XXX XXX XXX",
    "Settlor 1",
    "InitialUnitholder 1",
    "Est Date",
    "V Date",
    "YEAR",
    "Director 1",
    "Director 2",
    "Director 3",
    "Director 4",
    "Director 5",
    "Director 6",
    "Trustee 1",
    "Trustee 2",
    "Trustee 3",
    "Trustee 4",
    "Trustee 5",
    "Trustee 6",
    "INDIVIDUAL A",
    "INDIVIDUAL B",
    "COMPANY A Pty Ltd",
    "TRUSTEE A, in their capacity as trustee for the TRUST A",
    "Beneficiaries",
    "Unitholders",
    "Unitholder",
    "Distributable Income",
    "Net Income",
    "Capital",
]


def main() -> None:
    inventory = inventory_templates()
    FIELDMAP_DIR.mkdir(parents=True, exist_ok=True)
    out = FIELDMAP_DIR / "template_inventory.json"
    out.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    print(f"Wrote {out}")


def inventory_templates() -> dict[str, Any]:
    templates = []
    checklist_json = FIELDMAP_DIR / "trust_review_checklist.json"
    if checklist_json.exists():
        templates.append(inventory_checklist_json(checklist_json))
    for path in sorted(SOURCE_DIR.glob("*")):
        if path.suffix.lower() not in {".docx", ".docm", ".dotx", ".dotm"}:
            continue
        templates.append(inventory_template(path))
    return {
        "generated_by": "scripts/inventory_templates.py",
        "source_dir": str(SOURCE_DIR.relative_to(ROOT)),
        "source_templates": templates,
        "manual_tagging_report": manual_tagging_report(templates),
    }


def inventory_checklist_json(path: Path) -> dict[str, Any]:
    checklist = json.loads(path.read_text(encoding="utf-8"))
    rows = checklist.get("rows", [])
    return {
        "path": str(path.relative_to(ROOT)),
        "template_kind": "checklist",
        "package_part_count": 1,
        "macros_present": False,
        "activeX_controls_present": False,
        "content_controls": [],
        "bookmarks": [],
        "fields": [],
        "tables": [{"index": 1, "row_count": len(rows), "column_counts": [3], "sample_rows": [
            {
                "row_id": row.get("row_id"),
                "item": row.get("item"),
                "applies_to": row.get("applies_to", "all"),
            }
            for row in rows[:5]
        ]}],
        "visible_placeholders": [],
        "manual_page_break_branches": [],
        "manual_tagging_required": [
            "Verify checklist rows and helper context map to canonical paths.",
        ],
    }


def inventory_template(path: Path) -> dict[str, Any]:
    text = package_text(path)
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
        document_xml = zf.read("word/document.xml")
    root = ET.fromstring(document_xml)
    controls = _content_controls(root)
    bookmarks = _bookmarks(root)
    fields = _fields(root)
    visible_placeholders = sorted({placeholder for placeholder in KNOWN_PLACEHOLDERS if placeholder in text})
    dynamic_placeholders = _discover_dynamic_placeholders(text)
    branches = [branch.label for branch in detect_manual_page_break_branches(path)]
    return {
        "path": str(path.relative_to(ROOT)),
        "template_kind": _template_kind(path.name),
        "package_part_count": len(names),
        "macros_present": any("vbaProject" in name or "vbaData" in name for name in names),
        "activeX_controls_present": any("activeX" in name for name in names),
        "content_controls": controls,
        "bookmarks": bookmarks,
        "fields": fields,
        "tables": _table_inventory(path),
        "visible_placeholders": sorted(set(visible_placeholders + dynamic_placeholders)),
        "manual_page_break_branches": branches,
        "manual_tagging_required": _manual_tagging_required(path.name, visible_placeholders, branches),
    }


def _content_controls(root: ET.Element) -> list[dict[str, str | None]]:
    controls = []
    for sdt in root.findall(".//w:sdt", NS):
        props = sdt.find("./w:sdtPr", NS)
        tag = props.find("./w:tag", NS).attrib.get(f"{{{NS['w']}}}val") if props is not None and props.find("./w:tag", NS) is not None else None
        alias = props.find("./w:alias", NS).attrib.get(f"{{{NS['w']}}}val") if props is not None and props.find("./w:alias", NS) is not None else None
        controls.append({"tag": tag, "alias": alias, "text": normalise_space(element_text(sdt))[:160]})
    return controls


def _bookmarks(root: ET.Element) -> list[str]:
    names = []
    for bookmark in root.findall(".//w:bookmarkStart", NS):
        name = bookmark.attrib.get(f"{{{NS['w']}}}name")
        if name:
            names.append(name)
    return sorted(set(names))


def _fields(root: ET.Element) -> list[str]:
    values = []
    for instr in root.findall(".//w:instrText", NS):
        if instr.text:
            values.append(normalise_space(instr.text))
    for fld in root.findall(".//w:fldSimple", NS):
        instr = fld.attrib.get(f"{{{NS['w']}}}instr")
        if instr:
            values.append(normalise_space(instr))
    return values


def _table_inventory(path: Path) -> list[dict[str, Any]]:
    tables = []
    for index, table in enumerate(extract_tables(path), start=1):
        tables.append({
            "index": index,
            "row_count": len(table),
            "column_counts": sorted(set(len(row) for row in table)),
            "sample_rows": table[:5],
        })
    return tables


def _discover_dynamic_placeholders(text: str) -> list[str]:
    patterns = [
        r"\{\{[^{}]+\}\}",
        r"\bDirector\s+[1-6]\b",
        r"\bTrustee\s+[1-6]\b",
        r"\bcomma[1-6]\b",
    ]
    values = set()
    for pattern in patterns:
        values.update(re.findall(pattern, text))
    return sorted(values)


def _manual_tagging_required(name: str, placeholders: list[str], branches: list[str]) -> list[str]:
    tasks = []
    if "Checklist" in name:
        tasks.extend([
            "Verify trust details table row labels map to canonical paths.",
            "Verify checklist Relevant clause(s) cells use linked clause fields.",
            "Verify notes cells capture low-confidence and issue text.",
        ])
    if branches:
        tasks.append("Verify page-break branch order for corporate and individual trustee execution blocks.")
    if any(item in placeholders for item in ("INDIVIDUAL A", "Unitholder", "Beneficiaries", "Unitholders")):
        tasks.append("Verify repeatable party/distribution rows are populated from distribution.items.")
    return tasks


def _template_kind(name: str) -> str:
    if "Checklist" in name:
        return "checklist"
    if "Unit Trust" in name:
        return "unit_minute"
    if "Discretionary Trust" in name:
        return "discretionary_minute"
    return "unknown"


def manual_tagging_report(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "template": template["path"],
            "items": template["manual_tagging_required"],
        }
        for template in templates
        if template.get("manual_tagging_required")
    ]


if __name__ == "__main__":
    main()
