from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from app.extraction import value


RAW_PLACEHOLDERS = [
    "Trust Name",
    "XXX XXX XXX",
    "Settlor 1",
    "InitialUnitholder 1",
    "Est Date",
    "V Date",
    "YEAR",
    "INDIVIDUAL A",
    "INDIVIDUAL B",
    "COMPANY A Pty Ltd",
    "TRUSTEE A, in their capacity as trustee for the TRUST A",
]


def assert_valid_docx_bytes(content: bytes) -> None:
    path = Path("unused")
    with zipfile.ZipFile(__import__("io").BytesIO(content), "r") as zf:
        assert zf.testzip() is None
        assert "word/document.xml" in zf.namelist()


@pytest.fixture()
def sample_data() -> dict[str, Any]:
    def v(item: Any, clause: str | None = None) -> dict[str, Any]:
        return value(item, "trust_instrument", 1, clause_ref=clause, quote=f"Evidence for {item}.", confidence="high")

    return {
        "matter": {"matter_id": "TEST-1", "client_name": "Example Client"},
        "source_documents": {
            "trust_instrument_present": v(True),
            "trust_instrument_filename": v("trust.pdf"),
            "company_report_present": v(True),
            "company_report_filename": v("company.pdf"),
        },
        "trust": {
            "name": v("Example Family Trust"),
            "type": v("discretionary"),
            "deed_date": v("1 July 2015"),
            "settlor": {"name": v("Sam Settlor")},
            "initial_unitholder": {"name": v(None)},
            "initial_property": v("$10"),
            "governing_law": v("New South Wales"),
            "vesting": {
                "date": v("30 June 2095", "clause 1.33"),
                "clause_ref": v("clause 1.33", "clause 1.33"),
            },
        },
        "trustee": {
            "name": v("Example Trustee Pty Ltd"),
            "type": v("corporate"),
            "is_corporate": v(True),
            "acn": v("123 456 789"),
            "directors": [{"name": "Alex Director"}, {"name": "Taylor Director"}],
            "secretary": [{"name": "Casey Secretary"}],
            "shareholders": [{"name": "Example Holdings Pty Ltd"}],
            "individual_trustees": [],
        },
        "company_report": {
            "company_name": v("Example Trustee Pty Ltd"),
            "acn": v("123 456 789"),
            "registration_status": v("Registered"),
            "registered_office": v("1 Example Street Sydney NSW"),
            "directors": [{"name": "Alex Director"}, {"name": "Taylor Director"}],
            "secretary": [{"name": "Casey Secretary"}],
            "shareholders": [{"name": "Example Holdings Pty Ltd"}],
            "report_date": v("1 May 2026"),
        },
        "deed_history": {
            "amendments": [],
            "amendment_noted": v(False),
            "amended_deed_included": v(False),
        },
        "appointor_guardian": {
            "appointors": [{"name": "Alex Appointor"}],
            "guardians": [],
            "succession_clause_ref": v("clause 18", "clause 18"),
        },
        "beneficiaries": {
            "classes": v("Primary and general beneficiaries"),
            "primary": [{"name": "Alex Example"}],
            "general": [{"name": "Taylor Example"}],
            "excluded": v("No excluded beneficiary clause found"),
            "foreign_exclusion_clause_ref": v("clause 3.5", "clause 3.5"),
            "definition_clause_ref": v("clause 1.4", "clause 1.4"),
        },
        "unitholders": {
            "holdings": [],
            "register_clause_ref": v(None),
        },
        "income": {
            "definition_clause_ref": v("clause 1.12", "clause 1.12"),
            "distribution_power_clause_ref": v("clause 9", "clause 9"),
            "streaming_clause_ref": v("clause 11.5", "clause 11.5"),
            "accumulation_clause_ref": v("clause 9", "clause 9"),
            "determination_power_clause_ref": v("clause 1.12", "clause 1.12"),
        },
        "capital": {
            "determination_clause_ref": v("clause 10", "clause 10"),
            "advancement_clause_ref": v("clause 10.2", "clause 10.2"),
        },
        "distribution": {
            "items": [],
            "income_year": v("2026"),
            "resolution_date": v("25 June 2026"),
            "method": v("Credited to unpaid present entitlement accounts."),
            "method_clause_ref": v("clause 12", "clause 12"),
            "resolution_deadline": v("before 30 June"),
            "resolution_deadline_clause_ref": v("clause 9", "clause 9"),
            "balance_to_named_beneficiary": v(False),
        },
        "family_trust_election": {
            "election_made": v(False),
            "specified_individual": v(None),
            "income_year": v(None),
            "amendment_required": v(None),
        },
        "amendment_review": {
            "power_clause_ref": v("clause 20", "clause 20"),
            "consent_required": v("No"),
            "other_requirements": v("None found"),
        },
        "checklist": {
            "approved": v(True),
            "approved_at": v("2026-05-11"),
            "approved_by": v("Unit test"),
        },
        "issues": [],
        "evidence": [],
    }


@pytest.fixture()
def distribution_instructions() -> dict[str, Any]:
    return {
        "income_year": "2026",
        "resolution_date": "25 June 2026",
        "items": [
            {"name": "Alex Example", "proportion": 60, "income_class": "Ordinary income"},
            {"name": "Taylor Example", "proportion": 40, "income_class": "Capital gains"},
        ],
        "method": "Credited to each beneficiary's unpaid present entitlement account.",
    }
