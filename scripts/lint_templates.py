"""Lint prepared templates, field maps and schema path coverage."""

from __future__ import annotations

import json
import csv
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.word_ooxml import FIELDMAP_DIR  # noqa: E402


SCHEMA = ROOT / "schemas" / "trust_minute.schema.json"


def main() -> None:
    errors = lint()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("Template lint passed.")


def lint() -> list[str]:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors: list[str] = []
    for fieldmap_path in sorted(FIELDMAP_DIR.glob("*.fieldmap.json")):
        fieldmap = json.loads(fieldmap_path.read_text(encoding="utf-8"))
        for field in fieldmap.get("fields", []):
            path = field.get("field_path")
            if path and not schema_has_path(schema, path):
                errors.append(f"{fieldmap_path.name}: field path not in schema: {path}")
        policy = fieldmap.get("placeholder_policy", {})
        covered = set(policy.get("mapped", [])) | set(policy.get("deliberately_removed", [])) | set(policy.get("deliberately_retained", []))
        if not covered:
            errors.append(f"{fieldmap_path.name}: placeholder_policy does not cover any placeholders")
    errors.extend(_lint_checklist_helper_map(schema))
    return errors


def _lint_checklist_helper_map(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    checklist_csv = ROOT / "Trust Review Checklist.csv"
    helper_path = FIELDMAP_DIR / "checklist_helper_map.json"
    if not checklist_csv.exists():
        return [f"missing checklist CSV: {checklist_csv.name}"]
    if not helper_path.exists():
        return [f"missing checklist helper map: {helper_path.name}"]
    csv_rows = list(csv.DictReader(checklist_csv.read_text(encoding="utf-8-sig").splitlines()))
    csv_ids = {row.get("row_id") for row in csv_rows}
    helper = json.loads(helper_path.read_text(encoding="utf-8"))
    helper_rows = helper.get("rows", [])
    helper_ids = {row.get("row_id") for row in helper_rows}
    if csv_ids != helper_ids:
        errors.append("checklist_helper_map.json: row_id set does not match Trust Review Checklist.csv")
    for row in helper_rows:
        for path in [row.get("detail_path"), *row.get("clause_paths", [])]:
            if path and not schema_has_path(schema, path):
                errors.append(f"checklist_helper_map.json: {row.get('row_id')} path not in schema: {path}")
    return errors


def schema_has_path(schema: dict[str, Any], field_path: str) -> bool:
    current: dict[str, Any] | None = schema
    for part in field_path.split("."):
        if not current:
            return False
        properties = _resolve_ref(schema, current).get("properties", {})
        if part not in properties:
            return False
        current = _resolve_ref(schema, properties[part])
        if current.get("type") == "array":
            current = _resolve_ref(schema, current.get("items", {}))
    return True


def _resolve_ref(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/$defs/"):
            return schema["$defs"][ref.rsplit("/", 1)[1]]
    if "allOf" in node and node["allOf"]:
        return _resolve_ref(schema, node["allOf"][0])
    return node


if __name__ == "__main__":
    main()
