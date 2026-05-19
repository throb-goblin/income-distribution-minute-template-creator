from __future__ import annotations

import copy

from app.validation import validate_for_checklist, validate_for_minute


def test_checklist_validation_blocks_without_trust_instrument(sample_data: dict) -> None:
    data = copy.deepcopy(sample_data)
    data["source_documents"]["trust_instrument_present"]["value"] = False
    result = validate_for_checklist(data)
    assert not result["valid"]
    assert any(issue["code"] == "NO_TRUST_INSTRUMENT" for issue in result["blocking_issues"])


def test_checklist_validation_allows_missing_clause_issues(sample_data: dict) -> None:
    sample_data["issues"] = [
        {
            "code": "CLAUSE_NOT_FOUND",
            "message": "Vesting clause could not be identified.",
            "field_path": "trust.vesting.clause_ref",
            "blocking": True,
        }
    ]
    result = validate_for_checklist(sample_data)
    assert result["valid"]
    assert result["can_generate_checklist"]
    assert result["non_blocking_issues"][0]["code"] == "CLAUSE_NOT_FOUND"


def test_minute_validation_blocks_missing_mandatory_clause(sample_data: dict) -> None:
    data = copy.deepcopy(sample_data)
    data["income"]["distribution_power_clause_ref"]["value"] = None
    result = validate_for_minute(
        data,
        distribution_instructions={},
        approved_checklist={"approved": True},
    )
    assert not result["valid"]
    assert any(issue["code"] == "MISSING_DISTRIBUTION_POWER" for issue in result["blocking_issues"])


def test_minute_template_validation_does_not_require_annual_distribution_details(sample_data: dict) -> None:
    data = copy.deepcopy(sample_data)
    data["distribution"]["income_year"]["value"] = None
    data["distribution"]["resolution_date"]["value"] = None
    data["distribution"]["items"] = []
    result = validate_for_minute(data, distribution_instructions={}, approved_checklist={"approved": True})
    assert result["valid"], result["blocking_issues"]


def test_minute_validation_passes_with_required_inputs(sample_data: dict) -> None:
    result = validate_for_minute(
        sample_data,
        distribution_instructions={},
        approved_checklist={"approved": True},
    )
    assert result["valid"], result["blocking_issues"]
