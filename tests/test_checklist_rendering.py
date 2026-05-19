from __future__ import annotations

import csv
import json

from app.render_checklist import render_checklist, render_checklist_markdown
from app.word_ooxml import package_text, read_package_part
from scripts.prepare_templates import prepare_templates
from conftest import RAW_PLACEHOLDERS, assert_valid_docx_bytes

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_checklist_generation_leaves_no_raw_placeholders(sample_data: dict) -> None:
    prepare_templates()
    docx, summary = render_checklist(sample_data)
    assert_valid_docx_bytes(docx)
    text = package_text(docx)
    for placeholder in RAW_PLACEHOLDERS:
        assert placeholder not in text
    assert "Example Family Trust" in text
    assert "clause 1.33" in text
    assert "For approval" in text
    assert "Status" in text
    assert "[Usually only indicated" not in text
    assert "[For approval,Review,Approved]" not in text
    assert summary["rows_populated"] > 10
    assert "checklist_markdown" in summary
    document_xml = read_package_part(docx, "word/document.xml").decode("utf-8")
    assert 'w:orient="landscape"' in document_xml
    assert "Arial" in document_xml
    assert 'w:sz w:val="16"' in document_xml


def test_checklist_uses_not_found_for_missing_clause(sample_data: dict) -> None:
    prepare_templates()
    sample_data["income"]["streaming_clause_ref"]["value"] = None
    docx, summary = render_checklist(sample_data)
    text = package_text(docx)
    assert_valid_docx_bytes(docx)
    assert "Clause not found" in text
    assert "Income classification / streaming" in summary["not_found_clause_fields"]


def test_markdown_checklist_is_available_for_chat_review(sample_data: dict) -> None:
    markdown = render_checklist_markdown(sample_data)
    assert markdown.startswith("# Trust Review Checklist")
    assert "| Item | Relevant clause(s) | Extracted detail | Status |" in markdown
    assert "Example Family Trust" in markdown


def test_checklist_uses_clean_csv_and_json_helper_map() -> None:
    csv_path = ROOT / "Trust Review Checklist.csv"
    helper_path = ROOT / "templates" / "fieldmaps" / "checklist_helper_map.json"
    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8-sig").splitlines()))
    helper_map = json.loads(helper_path.read_text(encoding="utf-8"))
    helper_rows = {row["row_id"]: row for row in helper_map["rows"]}

    assert rows
    assert set(rows[0]) == {"row_id", "Item", "Applies to"}
    assert all(row["row_id"] in helper_rows for row in rows)
    assert helper_map["output_columns"] == ["Item", "Relevant clause(s)", "Extracted detail", "Status"]
    assert any(helper_rows[row["row_id"]]["helper_context"]["extracted_detail"] for row in rows)
