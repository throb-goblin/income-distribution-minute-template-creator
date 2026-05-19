from __future__ import annotations

from pathlib import Path

from app.extraction import LLMExtractionClient, PageText, extract_trust_minute_data


class FakeLLM:
    called = False

    def extract(self, trust_pages: list[PageText], company_pages: list[PageText], current_result: dict) -> dict:
        self.called = True
        current_result["matter"]["llm_mocked"] = True
        return current_result


def test_extraction_uses_deterministic_fields_and_mockable_llm(tmp_path: Path) -> None:
    trust = tmp_path / "trust.txt"
    trust.write_text(
        """
        By deed of settlement dated 1 July 2015 made between Example Trustee Pty Ltd
        ACN 123 456 789 (Trustee) as trustee and Sam Settlor as settlor, a trust
        was established known as Example Family Trust. Pursuant to clause 1.33 the
        Vesting Date is 30 June 2095. Clause 9 permits the trustee to distribute
        income. Pursuant to clause 1.12 income means trust income. Clause 11.5
        permits classes of income. Clause 1.4 defines Beneficiaries. Amounts may
        be credited to unpaid present entitlement accounts under clause 12.
        """,
        encoding="utf-8",
    )
    fake = FakeLLM()
    result = extract_trust_minute_data(trust, matter_metadata={"matter_id": "X"}, llm_client=fake)
    assert fake.called
    assert result["matter"]["llm_mocked"] is True
    assert result["trust"]["name"]["value"] == "Example Family Trust"
    assert result["trustee"]["acn"]["value"] == "123 456 789"
    assert result["trust"]["vesting"]["clause_ref"]["value"] == "clause 1.33"
    assert result["income"]["distribution_power_clause_ref"]["value"] == "clause 9"
    assert result["income"]["definition_clause_ref"]["quote"]
    assert len(result["income"]["definition_clause_ref"]["quote"].split()) <= 50


def test_missing_required_clause_creates_issue(tmp_path: Path) -> None:
    trust = tmp_path / "bare.txt"
    trust.write_text("Example Family Trust discretionary trust with no clause references.", encoding="utf-8")
    result = extract_trust_minute_data(trust)
    issue_paths = {issue["field_path"] for issue in result["issues"]}
    assert "income.distribution_power_clause_ref" in issue_paths
    assert result["income"]["distribution_power_clause_ref"]["issue_if_any"]


def test_unit_trust_detected_from_units_language(tmp_path: Path) -> None:
    trust = tmp_path / "unit.txt"
    trust.write_text(
        """
        Deed dated 1 July 2020 establishing the Example Investment Trust. The initial
        unitholder subscribes for 100 units and the trustee must maintain a unit register.
        Alex Unitholder holds 60 units. Taylor Unitholder holds 40 units.
        Clause 9 permits the trustee to distribute income. Clause 1.12 income means
        trust income. Clause 1.33 states the Vesting Date is 30 June 2100.
        """,
        encoding="utf-8",
    )
    result = extract_trust_minute_data(trust)
    assert result["trust"]["type"]["value"] == "unit"
    assert "unit" in result["trust"]["type"]["quote"].lower()
    holdings = {(item["name"], item["units"]) for item in result["unitholders"]["holdings"]}
    assert ("Alex Unitholder", "60") in holdings


def test_schedule_facts_override_investment_power_unit_wording(tmp_path: Path) -> None:
    trust = tmp_path / "schedule-family.txt"
    trust.write_text(
        """
        Trust Deed Damini Family Trust
        1.1 Definitions
        Income means the net income of the Trust as defined in section 95 of the Act.
        4.4 Trustee makes determinations.
        The Trustee may acquire units in any unit trust as part of the investment powers.
        Schedule
        Item 1: Deed Date 11/12/2025
        Item 2: Place of Settlement Victoria
        Item 3: Settlor Acis Settlements Pty. Ltd. ACN 081 961 391
        Item 4: Trustee/s Rosstrevor Avenue Pty Ltd ACN 693 658 605
        Item 5: Settlement Sum $10.00
        Item 6: Name of Trust Damini Family Trust
        Item 7: Applicable Law Victoria
        Item 10: Primary Beneficiaries Damini Rose Glenane
        Clause 4.4 permits the trustee to distribute income.
        Clause 12 provides amounts may be credited to unpaid present entitlement accounts.
        Clause 18 states the Vesting Date is 30 June 2095.
        """,
        encoding="utf-8",
    )
    result = extract_trust_minute_data(trust)
    assert result["trust"]["type"]["value"] == "discretionary"
    assert result["trust"]["deed_date"]["value"] == "11/12/2025"
    assert result["trustee"]["name"]["value"] == "Rosstrevor Avenue Pty Ltd"
    assert result["trustee"]["acn"]["value"] == "693 658 605"
    assert result["income"]["definition_clause_ref"]["value"] == "clause 1.1"


def test_vesting_perpetuity_formula_uses_jurisdiction_note(tmp_path: Path) -> None:
    trust = tmp_path / "perpetuity.txt"
    trust.write_text(
        """
        This deed is governed by the laws of New South Wales. Pursuant to clause 1.33
        the Vesting Date means the day immediately before the expiry of the perpetuity
        period for this trust. Clause 9 permits the trustee to distribute income.
        Clause 1.12 income means trust income. Amounts may be credited under clause 12.
        """,
        encoding="utf-8",
    )
    result = extract_trust_minute_data(trust)
    vesting = result["trust"]["vesting"]
    assert vesting["clause_ref"]["value"] == "clause 1.33"
    assert "New South Wales" in vesting["date"]["value"]
    assert "80 years" in vesting["date"]["value"]
