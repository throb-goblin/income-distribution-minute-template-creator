"""Validation rules for checklist and minute generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .word_ooxml import get_field_value


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    field_path: str | None = None
    severity: str = "blocking"

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.field_path:
            payload["field_path"] = self.field_path
        return payload


CHECKLIST_REQUIRED = [
    ("source_documents.trust_instrument_present", "NO_TRUST_INSTRUMENT", "A deed or trust instrument must be uploaded before a checklist can be generated."),
    ("trust.name", "MISSING_TRUST_NAME", "Trust name could not be determined."),
    ("trust.type", "MISSING_TRUST_TYPE", "Trust type could not be determined."),
]

MINUTE_REQUIRED = [
    ("trust.name", "MISSING_TRUST_NAME", "Trust name is required."),
    ("trust.type", "MISSING_TRUST_TYPE", "Trust type is required."),
    ("trust.deed_date", "MISSING_DEED_DATE", "Deed date is required."),
    ("trust.vesting.date", "MISSING_VESTING_DATE", "Vesting date must be determined from the trust instrument."),
    ("trust.vesting.clause_ref", "MISSING_VESTING_CLAUSE", "Vesting clause reference must be determined from the trust instrument."),
    ("income.definition_clause_ref", "MISSING_INCOME_DEFINITION", "Income definition clause reference is required."),
    ("income.distribution_power_clause_ref", "MISSING_DISTRIBUTION_POWER", "Income distribution power clause reference is required."),
]


def validate_for_checklist(data: dict[str, Any]) -> dict[str, Any]:
    blocking: list[Issue] = []
    non_blocking: list[Issue] = []
    for path, code, message in CHECKLIST_REQUIRED:
        if _missing(data, path):
            blocking.append(Issue(code, message, path))
    if get_field_value(data, "source_documents.trust_instrument_present") is not True:
        if not any(issue.code == "NO_TRUST_INSTRUMENT" for issue in blocking):
            blocking.append(Issue("NO_TRUST_INSTRUMENT", "A deed or trust instrument must be uploaded before a checklist can be generated.", "source_documents.trust_instrument_present"))

    for issue in data.get("issues", []):
        if issue.get("blocking") and issue.get("code") != "CLAUSE_NOT_FOUND":
            blocking.append(Issue(issue.get("code", "EXTRACTION_BLOCKER"), issue.get("message", "Blocking extraction issue."), issue.get("field_path")))
        else:
            non_blocking.append(Issue(issue.get("code", "EXTRACTION_ISSUE"), issue.get("message", "Extraction issue."), issue.get("field_path"), "non_blocking"))

    return _result("checklist", blocking, non_blocking)


def validate_for_minute(
    data: dict[str, Any],
    *,
    distribution_instructions: dict[str, Any] | None = None,
    approved_checklist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    blocking: list[Issue] = []
    non_blocking: list[Issue] = []

    for path, code, message in MINUTE_REQUIRED:
        if _missing(data, path):
            blocking.append(Issue(code, message, path))

    trust_type = str(get_field_value(data, "trust.type", "") or "").lower()
    if trust_type in {"", "unsure"}:
        blocking.append(Issue("TRUST_TYPE_UNSURE", "Minute template generation is blocked until the trust type is identified from the uploaded documents or corrected in the approved checklist.", "trust.type"))
    elif trust_type not in {"discretionary", "unit", "hybrid"}:
        blocking.append(Issue("TRUST_TYPE_UNSUPPORTED", f"Unsupported trust type for minute generation: {trust_type}.", "trust.type"))
    elif trust_type == "hybrid":
        blocking.append(Issue("HYBRID_TRUST_REVIEW", "Hybrid trust minutes require practitioner review before template selection.", "trust.type"))

    trustee_type = str(get_field_value(data, "trustee.type", "") or "").lower()
    is_corporate = get_field_value(data, "trustee.is_corporate")
    if trustee_type == "unsure" or is_corporate is None:
        blocking.append(Issue("TRUSTEE_TYPE_UNSURE", "Trustee type must be identified from the uploaded documents or corrected in the approved checklist before minute template generation.", "trustee.is_corporate"))
    if is_corporate:
        for path in ("trustee.name", "trustee.acn", "company_report.company_name", "company_report.acn", "company_report.registration_status", "company_report.directors"):
            if _missing(data, path):
                blocking.append(Issue("MISSING_CORPORATE_TRUSTEE_DETAILS", "Corporate trustee details are incomplete.", path))

    if _truthy(get_field_value(data, "deed_history.amendment_noted")) and not _truthy(get_field_value(data, "deed_history.amended_deed_included")):
        blocking.append(Issue("AMENDED_DEED_NOT_INCLUDED", "An amendment is noted, but the amended deed has not been included.", "deed_history.amended_deed_included"))

    if not approved_checklist:
        blocking.append(Issue("CHECKLIST_NOT_APPROVED", "The checklist must be approved or corrected before minute generation.", "checklist.approved"))

    for path in (
        "income.streaming_clause_ref",
        "income.accumulation_clause_ref",
        "capital.determination_clause_ref",
        "beneficiaries.definition_clause_ref",
        "unitholders.register_clause_ref",
        "distribution.method_clause_ref",
        "distribution.resolution_deadline_clause_ref",
    ):
        if _missing(data, path):
            non_blocking.append(Issue("CLAUSE_NOT_FOUND", f"{path} was not found and should be reviewed.", path, "non_blocking"))

    return _result("minute", blocking, non_blocking)


def _result(stage: str, blocking: list[Issue], non_blocking: list[Issue]) -> dict[str, Any]:
    return {
        "stage": stage,
        "valid": not blocking,
        "can_generate_checklist": stage == "checklist" and not blocking,
        "can_generate_minute": stage == "minute" and not blocking,
        "blocking_issues": [issue.as_dict() for issue in blocking],
        "non_blocking_issues": [issue.as_dict() for issue in non_blocking],
    }


def _missing(data: dict[str, Any], path: str) -> bool:
    value = get_field_value(data, path, default=None)
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in {"", "not found", "unknown", "unsure", "null"}:
        return True
    if isinstance(value, list) and not value:
        return True
    return False


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"yes", "true", "1", "noted"}
    return bool(value)
