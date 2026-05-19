"""Render sample checklist and minute DOCX files for manual smoke testing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.extraction import value  # noqa: E402
from app.render_checklist import render_checklist  # noqa: E402
from app.render_minute import render_minute  # noqa: E402
from scripts.prepare_templates import prepare_templates  # noqa: E402


def main() -> None:
    prepare_templates()
    out_dir = ROOT / "tmp" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = sample_data()
    checklist, checklist_summary = render_checklist(data)
    (out_dir / "sample-checklist.docx").write_bytes(checklist)
    minute, minute_summary = render_minute(
        data,
        distribution_instructions={},
        approved_checklist={"approved": True},
    )
    (out_dir / "sample-minute.docx").write_bytes(minute)
    print({"checklist": checklist_summary, "minute": minute_summary, "out_dir": str(out_dir)})


def sample_data() -> dict:
    def v(item: str, clause: str | None = None) -> dict:
        return value(item, "trust_instrument", 1, clause_ref=clause, quote=f"Sample evidence for {item}.", confidence="high")

    return {
        "matter": {"matter_id": "SMOKE"},
        "source_documents": {
            "trust_instrument_present": v(True),
            "trust_instrument_filename": v("sample.pdf"),
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
            "vesting": {"date": v("30 June 2095", "clause 1.33"), "clause_ref": v("clause 1.33", "clause 1.33")},
        },
        "trustee": {
            "name": v("Example Trustee Pty Ltd"),
            "type": v("corporate"),
            "is_corporate": v(True),
            "acn": v("123 456 789"),
            "directors": [{"name": "Alex Director"}, {"name": "Taylor Director"}],
            "secretary": [],
            "shareholders": [],
        },
        "company_report": {
            "company_name": v("Example Trustee Pty Ltd"),
            "acn": v("123 456 789"),
            "registration_status": v("Registered"),
            "registered_office": v("1 Example Street Sydney NSW"),
            "directors": [{"name": "Alex Director"}, {"name": "Taylor Director"}],
            "secretary": [],
            "shareholders": [],
            "report_date": v("1 May 2026"),
        },
        "deed_history": {"amendments": [], "amendment_noted": v(False), "amended_deed_included": v(False)},
        "appointor_guardian": {"appointors": [], "guardians": [], "succession_clause_ref": v(None)},
        "beneficiaries": {
            "classes": v("Primary and general beneficiaries"),
            "primary": [],
            "general": [],
            "excluded": v("See deed"),
            "foreign_exclusion_clause_ref": v("clause 3.5", "clause 3.5"),
            "definition_clause_ref": v("clause 1.4", "clause 1.4"),
        },
        "unitholders": {"holdings": [], "register_clause_ref": v(None)},
        "income": {
            "definition_clause_ref": v("clause 1.12", "clause 1.12"),
            "distribution_power_clause_ref": v("clause 9", "clause 9"),
            "streaming_clause_ref": v("clause 11.5", "clause 11.5"),
            "accumulation_clause_ref": v("clause 9", "clause 9"),
            "determination_power_clause_ref": v("clause 1.12", "clause 1.12"),
        },
        "capital": {"determination_clause_ref": v("clause 10", "clause 10"), "advancement_clause_ref": v("clause 10.2", "clause 10.2")},
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
        "family_trust_election": {"election_made": v(False), "specified_individual": v(None), "income_year": v(None), "amendment_required": v(None)},
        "amendment_review": {"power_clause_ref": v("clause 20", "clause 20"), "consent_required": v("No"), "other_requirements": v("None found")},
        "checklist": {"approved": v(True), "approved_at": v("2026-05-11"), "approved_by": v("Smoke test")},
        "issues": [],
        "evidence": [],
    }


if __name__ == "__main__":
    main()
