from __future__ import annotations

import json
from pathlib import Path

from app.word_ooxml import WORKING_DIR, package_has_activex, package_has_macros
from scripts.lint_templates import schema_has_path
from scripts.prepare_templates import prepare_templates


ROOT = Path(__file__).resolve().parents[1]


def test_every_fieldmap_path_exists_in_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "trust_minute.schema.json").read_text(encoding="utf-8"))
    for path in sorted((ROOT / "templates" / "fieldmaps").glob("*.fieldmap.json")):
        fieldmap = json.loads(path.read_text(encoding="utf-8"))
        for field in fieldmap["fields"]:
            assert schema_has_path(schema, field["field_path"]), f"{path.name}: {field['field_path']}"


def test_checklist_helper_map_paths_exist_in_schema() -> None:
    schema = json.loads((ROOT / "schemas" / "trust_minute.schema.json").read_text(encoding="utf-8"))
    helper_map = json.loads((ROOT / "templates" / "fieldmaps" / "checklist_helper_map.json").read_text(encoding="utf-8"))
    for row in helper_map["rows"]:
        for path in [row.get("detail_path"), *row.get("clause_paths", [])]:
            if path:
                assert schema_has_path(schema, path), f"{row['row_id']}: {path}"


def test_source_placeholders_are_mapped_removed_or_retained() -> None:
    inventory = json.loads((ROOT / "templates" / "fieldmaps" / "template_inventory.json").read_text(encoding="utf-8"))
    fieldmaps = {
        "checklist": json.loads((ROOT / "templates" / "fieldmaps" / "checklist.fieldmap.json").read_text(encoding="utf-8")),
        "discretionary_minute": json.loads((ROOT / "templates" / "fieldmaps" / "discretionary_minute.fieldmap.json").read_text(encoding="utf-8")),
        "unit_minute": json.loads((ROOT / "templates" / "fieldmaps" / "unit_minute.fieldmap.json").read_text(encoding="utf-8")),
    }
    for template in inventory["source_templates"]:
        kind = template["template_kind"]
        policy = fieldmaps[kind]["placeholder_policy"]
        covered = set(policy["mapped"]) | set(policy["deliberately_removed"]) | set(policy["deliberately_retained"])
        missing = set(template["visible_placeholders"]) - covered
        assert not missing, f"{template['path']} missing policy for {sorted(missing)}"


def test_prepare_templates_creates_macro_free_working_copies() -> None:
    result = prepare_templates()
    for item in result["prepared_templates"]:
        working = ROOT / item["working"]
        assert working.exists()
        assert not package_has_macros(working)
        assert not package_has_activex(working)
    assert {item["kind"] for item in result["prepared_templates"]} == {"discretionary", "unit"}
    assert not (WORKING_DIR / "trust_minute_checklist.docx").exists()


def test_minute_branch_inventory_detects_four_branches() -> None:
    result = prepare_templates()
    minute_items = [item for item in result["prepared_templates"] if item["kind"] in {"discretionary", "unit"}]
    assert minute_items
    for item in minute_items:
        assert item["branches"] == [
            "corporate_multi_director",
            "corporate_sole_director",
            "individual_sole_trustee",
            "individual_multi_trustee",
        ]
