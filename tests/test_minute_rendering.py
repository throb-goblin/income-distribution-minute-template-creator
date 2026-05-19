from __future__ import annotations

import copy

from app.render_checklist import build_checklist_rows, render_checklist
from app.render_minute import render_minute
from app.word_ooxml import get_field_value, package_text
from scripts.prepare_templates import prepare_templates
from conftest import RAW_PLACEHOLDERS, assert_valid_docx_bytes


def test_minute_template_generation_leaves_no_raw_placeholders(sample_data: dict) -> None:
    prepare_templates()
    data = copy.deepcopy(sample_data)
    data["distribution"]["income_year"]["value"] = None
    data["distribution"]["resolution_date"]["value"] = None
    data["distribution"]["items"] = []
    docx, summary = render_minute(
        data,
        distribution_instructions={},
        approved_checklist={"approved": True},
    )
    assert_valid_docx_bytes(docx)
    text = package_text(docx)
    retained_template_placeholders = {"YEAR", "INDIVIDUAL A", "INDIVIDUAL B", "COMPANY A Pty Ltd", "TRUSTEE A, in their capacity as trustee for the TRUST A"}
    for placeholder in set(RAW_PLACEHOLDERS) - retained_template_placeholders:
        assert placeholder not in text
    assert "Example Family Trust" in text
    assert "Year ended 30 June YEAR" in text
    assert "INDIVIDUAL A" in text
    assert "Clause reference schedule" not in text
    assert "Distribution schedule" not in text
    assert "Drafting aid only" not in text
    assert "In respect of the year ended 30 June YEAR the Trustee has NOT made any DETERMINATION in respect of the Capital of the Trust." in text
    assert summary["template_branch"] == "corporate_multi_director"
    assert "income year" in summary["template_insert_points"]


def test_clause_references_are_sourced_from_same_canonical_fields(sample_data: dict) -> None:
    prepare_templates()
    _, checklist_summary = render_checklist(sample_data)
    minute_docx, minute_summary = render_minute(
        sample_data,
        distribution_instructions={},
        approved_checklist={"approved": True},
    )
    text = package_text(minute_docx)
    linked_paths = {
        "trust.vesting.clause_ref",
        "income.definition_clause_ref",
        "income.distribution_power_clause_ref",
        "income.streaming_clause_ref",
    }
    checklist_text = "\n".join(
        f"{row['Relevant clause(s)']} {row['Extracted detail']}"
        for row in build_checklist_rows(sample_data)
    )
    lower_text = text.lower()
    for path in linked_paths:
        clause = get_field_value(sample_data, path)
        if clause:
            assert clause.lower() in checklist_text.lower()
            assert clause.lower() in lower_text
    assert minute_summary["clause_fields"]["vesting"] == get_field_value(sample_data, "trust.vesting.clause_ref")
    assert minute_summary["clause_fields"]["capital"] == get_field_value(sample_data, "capital.determination_clause_ref")
    assert minute_summary["clause_fields"]["method"] == get_field_value(sample_data, "distribution.method_clause_ref")
