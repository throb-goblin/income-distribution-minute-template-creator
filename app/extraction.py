"""Trust instrument and company report extraction.

The extractor is intentionally conservative.  It records evidence when a value
is found and emits issues instead of inventing clause references.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .word_ooxml import clamp_quote, package_text


class LLMExtractionClient(Protocol):
    """Clean interface for optional model-assisted extraction.

    Tests can pass a fake implementation.  The default extractor never calls an
    external service.
    """

    def extract(
        self,
        trust_pages: list["PageText"],
        company_pages: list["PageText"],
        current_result: dict[str, Any],
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class PageText:
    source_document_id: str
    page: int
    text: str


class NullLLMExtractionClient:
    def extract(
        self,
        trust_pages: list[PageText],
        company_pages: list[PageText],
        current_result: dict[str, Any],
    ) -> dict[str, Any]:
        return current_result


JURISDICTION_PERPETUITY_NOTES = {
    "New South Wales": "80 years from the date the settlement takes effect.",
    "Victoria": "80 years from the date the settlement takes effect, if specified in the deed.",
    "Queensland": "125 years from the day the disposition is made unless the trust terms state or imply a shorter period. The 125-year regime commenced on 1 August 2025, so pre-commencement deeds require practitioner review.",
    "South Australia": "No fixed statutory perpetuity period; rules against perpetuities and excessive accumulations are abolished. The court may still order vesting of interests after 80 years in some cases.",
    "Western Australia": "A period specified in the deed, not exceeding 80 years; otherwise the period applicable under the rule at law.",
    "Tasmania": "A period specified in the deed, not exceeding 80 years from when the disposition takes effect; otherwise the rule against perpetuities as affected by statute.",
    "Australian Capital Territory": "80 years from the date the settlement takes effect.",
    "Northern Territory": "Lives in being plus 21 years or 80 years from the settlement taking effect, whichever is specified in the settlement. If no period is specified, 80 years applies.",
}


JURISDICTION_PATTERNS = {
    "New South Wales": [r"\bnew south wales\b", r"\bnsw\b"],
    "Victoria": [r"\bvictoria\b", r"\bvic\b"],
    "Queensland": [r"\bqueensland\b", r"\bqld\b"],
    "South Australia": [r"\bsouth australia\b", r"\bsa\b"],
    "Western Australia": [r"\bwestern australia\b", r"\bwa\b"],
    "Tasmania": [r"\btasmania\b", r"\btas\b"],
    "Australian Capital Territory": [r"\baustralian capital territory\b", r"\bact\b"],
    "Northern Territory": [r"\bnorthern territory\b", r"\bnt\b"],
}


def extract_trust_minute_data(
    trust_instrument_path: str | Path,
    company_report_path: str | Path | None = None,
    *,
    matter_metadata: dict[str, Any] | None = None,
    llm_client: LLMExtractionClient | None = None,
) -> dict[str, Any]:
    trust_path = Path(trust_instrument_path)
    company_path = Path(company_report_path) if company_report_path else None
    trust_pages = extract_text_pages(trust_path, "trust_instrument")
    company_pages = extract_text_pages(company_path, "company_report") if company_path else []

    result = empty_result(matter_metadata=matter_metadata)
    result["source_documents"] = {
        "trust_instrument_present": value(True, "trust_instrument", None, quote=trust_path.name, confidence="high"),
        "trust_instrument_filename": value(trust_path.name, "trust_instrument", None, quote=trust_path.name, confidence="high"),
        "company_report_present": value(bool(company_path), "company_report" if company_path else None, None, quote=company_path.name if company_path else "", confidence="high"),
        "company_report_filename": value(company_path.name if company_path else None, "company_report" if company_path else None, None, confidence="high" if company_path else "low"),
    }

    trust_text = "\n".join(page.text for page in trust_pages)
    company_text = "\n".join(page.text for page in company_pages)
    _extract_trust_facts(result, trust_pages, trust_text)
    if company_path:
        _extract_company_report(result, company_pages, company_text)

    _copy_company_to_trustee(result)
    _add_missing_clause_issues(result)

    llm_client = llm_client or NullLLMExtractionClient()
    result = llm_client.extract(trust_pages, company_pages, result)
    return result


def extract_text_pages(path: Path | None, source_document_id: str) -> list[PageText]:
    if path is None:
        return []
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_pages(path, source_document_id)
    if suffix in {".docx", ".docm", ".dotx", ".dotm"}:
        return [PageText(source_document_id, 1, package_text(path))]
    return [PageText(source_document_id, 1, path.read_text(encoding="utf-8", errors="ignore"))]


def _extract_pdf_pages(path: Path, source_document_id: str) -> list[PageText]:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        fitz = None
    if fitz is not None:
        with fitz.open(path) as doc:
            return [PageText(source_document_id, index + 1, page.get_text("text") or "") for index, page in enumerate(doc)]

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires PyMuPDF or pypdf. Install project requirements first.") from exc

    reader = PdfReader(str(path))
    pages: list[PageText] = []
    for index, page in enumerate(reader.pages, start=1):
        pages.append(PageText(source_document_id, index, page.extract_text() or ""))
    return pages


def empty_result(*, matter_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "matter": matter_metadata or {},
        "source_documents": {},
        "trust": {
            "name": empty_value(),
            "type": empty_value("unsure", confidence="low", issue_if_any="Trust type requires review."),
            "deed_date": empty_value(),
            "settlor": {"name": empty_value()},
            "initial_unitholder": {"name": empty_value()},
            "initial_property": empty_value(),
            "place_of_settlement": empty_value(),
            "governing_law": empty_value(),
            "vesting": {"date": empty_value(), "clause_ref": empty_value()},
        },
        "trustee": {
            "name": empty_value(),
            "type": empty_value("unsure", confidence="low"),
            "is_corporate": empty_value(None, confidence="low"),
            "acn": empty_value(),
            "directors": [],
            "secretary": [],
            "shareholders": [],
        },
        "company_report": {
            "company_name": empty_value(),
            "acn": empty_value(),
            "registration_status": empty_value(),
            "registered_office": empty_value(),
            "directors": [],
            "secretary": [],
            "shareholders": [],
            "report_date": empty_value(),
        },
        "deed_history": {
            "amendments": [],
            "amendment_noted": empty_value(False, confidence="medium"),
            "amended_deed_included": empty_value(False, confidence="low"),
        },
        "appointor_guardian": {
            "appointors": [],
            "guardians": [],
            "succession_clause_ref": empty_value(),
        },
        "beneficiaries": {
            "classes": empty_value(),
            "primary": [],
            "general": [],
            "excluded": empty_value(),
            "foreign_exclusion_clause_ref": empty_value(),
            "definition_clause_ref": empty_value(),
        },
        "unitholders": {
            "holdings": [],
            "register_clause_ref": empty_value(),
        },
        "income": {
            "definition_clause_ref": empty_value(),
            "distribution_power_clause_ref": empty_value(),
            "streaming_clause_ref": empty_value(),
            "accumulation_clause_ref": empty_value(),
            "determination_power_clause_ref": empty_value(),
        },
        "capital": {
            "determination_clause_ref": empty_value(),
            "advancement_clause_ref": empty_value(),
        },
        "distribution": {
            "items": [],
            "income_year": empty_value(),
            "resolution_date": empty_value(),
            "method": empty_value(),
            "method_clause_ref": empty_value(),
            "resolution_deadline": empty_value(),
            "resolution_deadline_clause_ref": empty_value(),
            "balance_to_named_beneficiary": empty_value(False, confidence="medium"),
        },
        "family_trust_election": {
            "election_made": empty_value(None, confidence="low"),
            "specified_individual": empty_value(),
            "income_year": empty_value(),
            "amendment_required": empty_value(None, confidence="low"),
        },
        "amendment_review": {
            "power_clause_ref": empty_value(),
            "consent_required": empty_value(),
            "other_requirements": empty_value(),
        },
        "checklist": {
            "approved": empty_value(False, confidence="medium"),
            "approved_at": empty_value(),
            "approved_by": empty_value(),
        },
        "issues": [],
        "evidence": [],
    }


def empty_value(default: Any = None, *, confidence: str = "low", issue_if_any: str | None = None) -> dict[str, Any]:
    return {
        "value": default,
        "source_document_id": None,
        "page": None,
        "clause_ref": None,
        "heading": None,
        "quote": "",
        "confidence": confidence,
        "issue_if_any": issue_if_any,
    }


def value(
    extracted_value: Any,
    source_document_id: str | None,
    page: int | None,
    *,
    clause_ref: str | None = None,
    heading: str | None = None,
    quote: str = "",
    confidence: str = "medium",
    issue_if_any: str | None = None,
) -> dict[str, Any]:
    return {
        "value": extracted_value,
        "source_document_id": source_document_id,
        "page": page,
        "clause_ref": clause_ref,
        "heading": heading,
        "quote": clamp_quote(quote, 50),
        "confidence": confidence,
        "issue_if_any": issue_if_any,
    }


def _extract_trust_facts(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    _extract_schedule_facts(result, pages, text)

    trust_name = _first_match(text, [
        r"known as\s+([A-Z][A-Za-z0-9 '&.,()-]{2,120}?\s*Trust)\b",
        r"trust\s+known\s+as\s+([A-Z][A-Za-z0-9 '&.,()-]{2,120}?\s*Trust)\b",
        r"([A-Z][A-Za-z0-9 '&.,()-]{2,120}?\b(?:Unit|Discretionary|Family)?\s*Trust)\b",
    ])
    if trust_name and not result["trust"]["name"].get("value"):
        page = _page_for(pages, trust_name)
        result["trust"]["name"] = value(trust_name, page.source_document_id, page.page, quote=_quote_around(page.text, trust_name), confidence="medium")

    _extract_trust_type(result, pages, text)

    deed_date = _first_match(text, [
        r"deed(?:\s+of\s+settlement)?\s+dated\s+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"dated\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
    ])
    if deed_date and not result["trust"]["deed_date"].get("value"):
        page = _page_for(pages, deed_date)
        result["trust"]["deed_date"] = value(deed_date, page.source_document_id, page.page, quote=_quote_around(page.text, deed_date), confidence="medium")

    trustee = _first_match(text, [
        r"between\s+(.{2,120}?)\s+(?:ACN\s+([0-9 ]{9,15})\s+)?\((?:the\s+)?Trustee\)",
        r"trustee[:\s]+([A-Z][A-Za-z0-9 '&.,()-]{2,120})",
    ], group=1)
    if trustee and not result["trustee"]["name"].get("value"):
        clean = _clean_party_name(trustee)
        page = _page_for(pages, trustee)
        result["trustee"]["name"] = value(clean, page.source_document_id, page.page, quote=_quote_around(page.text, trustee), confidence="medium")
        is_corporate = bool(re.search(r"\b(Pty Ltd|Limited|Ltd)\b", clean, re.IGNORECASE))
        result["trustee"]["is_corporate"] = value(is_corporate, page.source_document_id, page.page, quote=_quote_around(page.text, trustee), confidence="medium")
        result["trustee"]["type"] = value("corporate" if is_corporate else "individual", page.source_document_id, page.page, quote=_quote_around(page.text, trustee), confidence="medium")

    acn = _first_match(text, [r"\bACN\s+([0-9 ]{9,15})\b"])
    if acn and not result["trustee"]["acn"].get("value"):
        page = _page_for(pages, acn)
        result["trustee"]["acn"] = value(_normalise_acn(acn), page.source_document_id, page.page, quote=_quote_around(page.text, acn), confidence="medium")
        result["trustee"]["is_corporate"] = value(True, page.source_document_id, page.page, quote=_quote_around(page.text, acn), confidence="medium")
        result["trustee"]["type"] = value("corporate", page.source_document_id, page.page, quote=_quote_around(page.text, acn), confidence="medium")

    settlor = _first_match(text, [r"settlor[,:\s]+([A-Z][A-Za-z0-9 '&.,()-]{2,120})", r"and\s+(.{2,120}?)\s+as\s+settlor"])
    if settlor and not result["trust"]["settlor"]["name"].get("value"):
        page = _page_for(pages, settlor)
        result["trust"]["settlor"]["name"] = value(_clean_party_name(settlor), page.source_document_id, page.page, quote=_quote_around(page.text, settlor), confidence="medium")

    initial_unitholder = _first_match(text, [r"initial\s+Unitholder(?:\(s\))?[,:\s]+([A-Z][A-Za-z0-9 '&.,()-]{2,120})", r"and\s+(.{2,120}?)\s+as\s+the\s+initial\s+Unitholder"])
    if initial_unitholder and not result["trust"]["initial_unitholder"]["name"].get("value"):
        page = _page_for(pages, initial_unitholder)
        result["trust"]["initial_unitholder"]["name"] = value(_clean_party_name(initial_unitholder), page.source_document_id, page.page, quote=_quote_around(page.text, initial_unitholder), confidence="medium")

    _extract_unit_holdings(result, pages, text)

    governing_law = _first_match(text, [r"governed\s+by\s+the\s+laws\s+of\s+([A-Za-z ]+)", r"jurisdiction[:\s]+([A-Za-z ]+)"])
    if governing_law and not result["trust"]["governing_law"].get("value"):
        page = _page_for(pages, governing_law)
        result["trust"]["governing_law"] = value(governing_law.strip(), page.source_document_id, page.page, quote=_quote_around(page.text, governing_law), confidence="medium")

    _extract_vesting_details(result, pages, text)

    _extract_named_clause(result, pages, text, "income.definition_clause_ref", ["income means", "definition of income", "net income", "distributable income"], "Income definition")
    _extract_income_definition_clause(result, pages, text)
    _extract_named_clause(result, pages, text, "income.distribution_power_clause_ref", ["distribute income", "distribute", "distribution of income", "pay or accumulate"], "Income distribution power")
    _extract_named_clause(result, pages, text, "income.determination_power_clause_ref", ["determine whether", "trust law income", "division 6", "Div 6"], "Income determination power")
    _extract_named_clause(result, pages, text, "income.streaming_clause_ref", ["streaming", "classes of income", "income into various classes"], "Income streaming")
    _extract_named_clause(result, pages, text, "income.accumulation_clause_ref", ["accumulate income", "pay or accumulate"], "Accumulation power")
    _extract_named_clause(result, pages, text, "capital.determination_clause_ref", ["determine capital", "capital of the trust", "capital account"], "Capital determination")
    _extract_named_clause(result, pages, text, "capital.advancement_clause_ref", ["advance capital", "advancement of capital"], "Capital advancement")
    _extract_named_clause(result, pages, text, "beneficiaries.definition_clause_ref", ["beneficiaries are defined", "beneficiary means", "eligible beneficiaries"], "Beneficiary definition")
    _extract_named_clause(result, pages, text, "beneficiaries.foreign_exclusion_clause_ref", ["foreign beneficiary", "foreign person", "surcharge"], "Foreign beneficiary exclusion")
    _extract_named_clause(result, pages, text, "unitholders.register_clause_ref", ["unit register", "registered unitholder", "register of unitholders"], "Unit register")
    _extract_named_clause(result, pages, text, "distribution.method_clause_ref", ["undrawn present entitlement", "separate trust", "credited to"], "Method of distribution")
    _extract_named_clause(result, pages, text, "distribution.resolution_deadline_clause_ref", ["before 30 June", "prior to 30 June", "before the expiration of each accounting period"], "Resolution deadline")
    _extract_named_clause(result, pages, text, "amendment_review.power_clause_ref", ["amend", "variation", "power to amend"], "Amendment power")

    deadline = _first_match(text, [r"(before\s+(?:30\s+June|the\s+expiration\s+of\s+each\s+accounting\s+period))", r"(prior\s+to\s+30\s+June)"])
    if deadline:
        page = _page_for(pages, deadline)
        result["distribution"]["resolution_deadline"] = value(deadline, page.source_document_id, page.page, clause_ref=result["distribution"]["resolution_deadline_clause_ref"].get("value"), quote=_quote_around(page.text, deadline), confidence="medium")

    initial_property = _first_match(text, [r"initial\s+trust\s+property[:\s]+([^.\n]{1,120})", r"settled\s+sum\s+of\s+([^.\n]{1,80})"])
    if initial_property and not result["trust"]["initial_property"].get("value"):
        page = _page_for(pages, initial_property)
        result["trust"]["initial_property"] = value(initial_property.strip(), page.source_document_id, page.page, quote=_quote_around(page.text, initial_property), confidence="medium")

    if _detect_supplied_amendment(text):
        page = _page_for(pages, "amend")
        result["deed_history"]["amendment_noted"] = value(True, page.source_document_id, page.page, quote=_quote_around(page.text, "amend"), confidence="low", issue_if_any="Potential amendment reference requires review.")


def _extract_company_report(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    company_name = _first_match(text, [
        r"Company Name[:\s]+([A-Z][A-Za-z0-9 '&.,()-]{2,120})",
        r"\b([A-Z][A-Z0-9 '&.,()-]+(?:PTY LTD|LIMITED|LTD))\b",
    ])
    if company_name:
        page = _page_for(pages, company_name)
        result["company_report"]["company_name"] = value(_clean_party_name(company_name), page.source_document_id, page.page, quote=_quote_around(page.text, company_name), confidence="medium")

    acn = _first_match(text, [r"\bACN[:\s]+([0-9 ]{9,15})\b"])
    if acn:
        page = _page_for(pages, acn)
        result["company_report"]["acn"] = value(_normalise_acn(acn), page.source_document_id, page.page, quote=_quote_around(page.text, acn), confidence="medium")

    status = _first_match(text, [r"Status[:\s]+([A-Za-z ]{3,40})", r"Registration Status[:\s]+([A-Za-z ]{3,40})"])
    if status:
        page = _page_for(pages, status)
        result["company_report"]["registration_status"] = value(status.strip(), page.source_document_id, page.page, quote=_quote_around(page.text, status), confidence="medium")
    elif re.search(r"\bDate of incorporation\b|\bState of Registration\b|\bCompany Class\b", text, re.IGNORECASE):
        page = _page_for(pages, "Date of incorporation")
        result["company_report"]["registration_status"] = value("Registered", page.source_document_id, page.page, quote=_quote_around(page.text, "Date of incorporation"), confidence="medium")

    office = _first_match(text, [r"Registered Office[:\s]+([^\n]{5,180})"])
    if office:
        page = _page_for(pages, office)
        result["company_report"]["registered_office"] = value(office.strip(), page.source_document_id, page.page, quote=_quote_around(page.text, office), confidence="medium")

    report_date = _first_match(text, [r"Report Date[:\s]+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", r"Current Extract Date[:\s]+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})"])
    if report_date:
        page = _page_for(pages, report_date)
        result["company_report"]["report_date"] = value(report_date, page.source_document_id, page.page, quote=_quote_around(page.text, report_date), confidence="medium")

    result["company_report"]["directors"] = _extract_people_after_labels(pages, text, ["Director", "Directors"])
    result["company_report"]["secretary"] = _extract_people_after_labels(pages, text, ["Secretary", "Secretaries"])
    result["company_report"]["shareholders"] = _extract_people_after_labels(pages, text, ["Shareholder", "Members"])


def _extract_schedule_facts(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    schedule_items = _schedule_items(text)
    if not schedule_items:
        return

    def set_evidenced(path: str, item_no: int, raw_value: str, *labels: str, confidence: str = "high") -> None:
        cleaned = _schedule_value(raw_value, labels)
        page = _page_for(pages, raw_value)
        _set_path(
            result,
            path,
            value(cleaned, page.source_document_id, page.page, heading=f"Schedule Item {item_no}", quote=_quote_around(page.text, raw_value), confidence=confidence),
        )

    if raw := schedule_items.get(1):
        set_evidenced("trust.deed_date", 1, raw, "Deed Date")
    if raw := schedule_items.get(2):
        set_evidenced("trust.place_of_settlement", 2, raw, "Place of Settlement")
    if raw := schedule_items.get(3):
        set_evidenced("trust.settlor.name", 3, raw, "Settlor")
    if raw := schedule_items.get(4):
        trustee_name, acn = _split_name_acn(_schedule_value(raw, ("Trustee/s", "Trustees", "Trustee")))
        set_evidenced("trustee.name", 4, trustee_name)
        page = _page_for(pages, raw)
        if acn:
            result["trustee"]["acn"] = value(acn, page.source_document_id, page.page, heading="Schedule Item 4", quote=_quote_around(page.text, raw), confidence="high")
        is_corporate = bool(re.search(r"\b(Pty Ltd|Limited|Ltd)\b", trustee_name, re.IGNORECASE))
        result["trustee"]["is_corporate"] = value(is_corporate, page.source_document_id, page.page, heading="Schedule Item 4", quote=_quote_around(page.text, raw), confidence="high")
        result["trustee"]["type"] = value("corporate" if is_corporate else "individual", page.source_document_id, page.page, heading="Schedule Item 4", quote=_quote_around(page.text, raw), confidence="high")
    if raw := schedule_items.get(5):
        set_evidenced("trust.initial_property", 5, raw, "Settlement Sum")
    if raw := schedule_items.get(6):
        set_evidenced("trust.name", 6, raw, "Name of Trust")
    if raw := schedule_items.get(7):
        set_evidenced("trust.governing_law", 7, raw, "Applicable Law")
    if raw := schedule_items.get(8):
        result["appointor_guardian"]["appointors"] = _people_from_schedule(_schedule_value(raw, ("Appointor/s", "Appointors")), pages, "Schedule Item 8")
    if raw := schedule_items.get(9):
        result["appointor_guardian"]["guardians"] = _people_from_schedule(_schedule_value(raw, ("Alternative Appointor/s", "Alternative Appointors")), pages, "Schedule Item 9")
    if raw := schedule_items.get(10):
        primary = _schedule_value(raw, ("Primary Beneficiaries", "Primary Beneficiary"))
        result["beneficiaries"]["primary"] = _people_from_schedule(primary, pages, "Schedule Item 10")
        page = _page_for(pages, raw)
        result["beneficiaries"]["classes"] = value("Primary and general beneficiaries", page.source_document_id, page.page, heading="Schedule Item 10", quote=_quote_around(page.text, raw), confidence="medium")


def _schedule_items(text: str) -> dict[int, str]:
    items: dict[int, str] = {}
    pattern = re.compile(r"Item\s+(\d+):\s*(.+?)(?=\s+Item\s+\d+:|\s+Signing\s+Page\b|\Z)", re.IGNORECASE | re.DOTALL)
    for match in pattern.finditer(text):
        item_no = int(match.group(1))
        if item_no not in items:
            items[item_no] = _normalise_sentence(match.group(2))
    return items


def _split_name_acn(raw: str) -> tuple[str, str | None]:
    acn_match = re.search(r"\bACN\s+([0-9 ]{9,15})\b", raw, re.IGNORECASE)
    acn = _normalise_acn(acn_match.group(1)) if acn_match else None
    name = re.sub(r"\bACN\s+[0-9 ]{9,15}\b", "", raw, flags=re.IGNORECASE)
    return _clean_schedule_value(name), acn


def _people_from_schedule(raw: str, pages: list[PageText], heading: str) -> list[dict[str, Any]]:
    cleaned = _clean_schedule_value(raw)
    parts = [part.strip() for part in re.split(r"\s*(?:;|,|\band\b)\s*", cleaned) if part.strip()]
    page = _page_for(pages, raw)
    return [
        {
            "name": part,
            "source_document_id": page.source_document_id,
            "page": page.page,
            "quote": clamp_quote(raw, 50),
            "confidence": "medium",
            "heading": heading,
        }
        for part in parts
    ]


def _extract_trust_type(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    title_hint = str(result.get("trust", {}).get("name", {}).get("value") or "")
    hybrid_hit = _first_regex_hit(text, [r"\bhybrid\s+trust\b"])
    if hybrid_hit:
        page = _page_for(pages, hybrid_hit)
        result["trust"]["type"] = value("hybrid", page.source_document_id, page.page, quote=_quote_around(page.text, hybrid_hit), confidence="medium")
        return

    unit_hit = _first_regex_hit(text, [
        r"\bunit\s+trust\b",
        r"\bunit\s+holder(?:s)?\b",
        r"\bunitholder(?:s)?\b",
        r"\binitial\s+unitholder\b",
        r"\bunit\s+register\b",
        r"\bunit\s+certificate(?:s)?\b",
        r"\bissued\s+units?\b",
        r"\bunits?\s+held\b",
    ])
    discretionary_hit = _first_regex_hit(text, [
        r"\bdiscretionary\s+trust\b",
        r"\bfamily\s+trust\b",
        r"\bprimary\s+beneficiar(?:y|ies)\b",
        r"\bgeneral\s+beneficiar(?:y|ies)\b",
        r"\beligible\s+beneficiar(?:y|ies)\b",
    ])

    if unit_hit and not _unit_hit_is_investment_power(unit_hit, text):
        page = _page_for(pages, unit_hit)
        confidence = "high" if re.search(r"\bunitholder|unit\s+register|unit\s+certificate|issued\s+units|units?\s+held", unit_hit, re.IGNORECASE) else "medium"
        result["trust"]["type"] = value("unit", page.source_document_id, page.page, quote=_quote_around(page.text, unit_hit), confidence=confidence)
        return

    if discretionary_hit or re.search(r"\bfamily\s+trust\b", title_hint, re.IGNORECASE):
        hit = discretionary_hit or title_hint
        page = _page_for(pages, hit)
        result["trust"]["type"] = value("discretionary", page.source_document_id, page.page, quote=_quote_around(page.text, hit), confidence="medium")


def _extract_vesting_details(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    _extract_named_clause(
        result,
        pages,
        text,
        "trust.vesting.clause_ref",
        ["vesting date", "termination date", "vesting day", "perpetuity period", "rule against perpetuities"],
        "Vesting or perpetuity provision",
    )
    clause_ref = result["trust"]["vesting"]["clause_ref"].get("value")

    vesting_date = _first_match(text, [
        r"(?:Vesting Date|Termination Date|Vesting Day).{0,160}?(?:being|is|means|shall be)\s+([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"(?:Vesting Date|Termination Date|Vesting Day).{0,160}?(?:being|is|means|shall be)\s+([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
        r"vest(?:ing)?(?:\s+or\s+termination)?\s+date.{0,100}?([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})",
        r"vest(?:ing)?(?:\s+or\s+termination)?\s+date.{0,100}?([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4})",
    ])
    if vesting_date:
        page = _page_for(pages, vesting_date)
        result["trust"]["vesting"]["date"] = value(vesting_date, page.source_document_id, page.page, clause_ref=clause_ref, quote=_quote_around(page.text, vesting_date), confidence="medium")
        return

    formula = _first_match(text, [
        r"((?:Vesting Date|Termination Date|Vesting Day).{0,320}?(?:perpetuity\s+period|rule\s+against\s+perpetuities|80\s+years|125\s+years|less\s+one\s+day).{0,160}?)\.",
        r"((?:perpetuity\s+period|rule\s+against\s+perpetuities).{0,320}?(?:vesting|vest|trust property|trust fund|assets).{0,160}?)\.",
        r"((?:latest date|last day).{0,220}?(?:trust property|trust fund|assets).{0,220}?(?:vest|vesting).{0,160}?)\.",
    ])
    if not formula:
        return

    page = _page_for(pages, formula[:80])
    jurisdiction = _infer_jurisdiction(result, text)
    note = JURISDICTION_PERPETUITY_NOTES.get(jurisdiction or "")
    formula_summary = _normalise_sentence(formula)
    if note and jurisdiction:
        latest_date = f"{formula_summary}. Jurisdiction note ({jurisdiction}): {note}"
        confidence = "medium"
        issue = None
    else:
        latest_date = f"{formula_summary}. Jurisdiction could not be determined for the applicable perpetuity period."
        confidence = "low"
        issue = "Jurisdiction/perpetuity period requires practitioner review."
    result["trust"]["vesting"]["date"] = value(latest_date, page.source_document_id, page.page, clause_ref=clause_ref, quote=formula, confidence=confidence, issue_if_any=issue)


def _extract_income_definition_clause(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    if result["income"]["definition_clause_ref"].get("value"):
        return
    match = re.search(r"\bIncome\s+means\b", text, re.IGNORECASE)
    if not match:
        return
    before = text[max(0, match.start() - 4000): match.start()]
    headings = re.findall(r"\b([0-9]+(?:\.[0-9]+)*)\s+Definitions\b", before, re.IGNORECASE)
    clause = f"clause {headings[-1]}" if headings else "clause 1.1"
    page = _page_for(pages, match.group(0))
    quote = _quote_around(page.text, match.group(0))
    result["income"]["definition_clause_ref"] = value(clause, page.source_document_id, page.page, clause_ref=clause, heading="Income definition", quote=quote, confidence="medium")


def _extract_unit_holdings(result: dict[str, Any], pages: list[PageText], text: str) -> None:
    if str(result.get("trust", {}).get("type", {}).get("value") or "").lower() != "unit":
        return
    holdings: list[dict[str, Any]] = []
    patterns = [
        r"([A-Z][A-Za-z0-9 '&.,()-]{2,120}?)\s+(?:holds?|is\s+the\s+holder\s+of|subscribes?\s+for)\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s+(?:ordinary\s+|income\s+|capital\s+)?units?\b",
        r"([A-Z][A-Za-z0-9 '&.,()-]{2,120}?)\s+([0-9][0-9,]*(?:\.[0-9]+)?)\s+(?:ordinary\s+|income\s+|capital\s+)?units?\b",
        r"(?:unitholder|holder)[:\s]+([A-Z][A-Za-z0-9 '&.,()-]{2,120}?).{0,80}?(?:number\s+of\s+units|units)[:\s]+([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]
    seen: set[tuple[str, str]] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            name = _clean_party_name(match.group(1))
            units = match.group(2).replace(",", "")
            key = (name.lower(), units)
            if key in seen or not name:
                continue
            seen.add(key)
            quote = match.group(0)
            page = _page_for(pages, quote[:80])
            holdings.append({
                "name": name,
                "units": units,
                "source_document_id": page.source_document_id,
                "page": page.page,
                "quote": clamp_quote(quote, 50),
                "confidence": "medium",
            })
    result["unitholders"]["holdings"] = holdings


def _unit_hit_is_investment_power(unit_hit: str, text: str) -> bool:
    index = text.lower().find(unit_hit.lower())
    if index < 0:
        return False
    window = text[max(0, index - 220): index + len(unit_hit) + 220]
    return bool(re.search(r"\b(?:acquire|purchase|securities|shares|stocks|bonds|debentures)\b", window, re.IGNORECASE))


def _detect_supplied_amendment(text: str) -> bool:
    amendment_patterns = [
        r"\bdeed\s+of\s+(?:variation|amendment|rectification)\b",
        r"\bsupplemental\s+deed\b",
        r"\bamending\s+deed\b",
        r"\bdeed\s+amended\s+by\b",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in amendment_patterns)


def _copy_company_to_trustee(result: dict[str, Any]) -> None:
    company = result.get("company_report", {})
    trustee = result.get("trustee", {})
    if not trustee.get("name", {}).get("value") and company.get("company_name", {}).get("value"):
        trustee["name"] = company["company_name"]
    if not trustee.get("acn", {}).get("value") and company.get("acn", {}).get("value"):
        trustee["acn"] = company["acn"]
    if company.get("directors"):
        trustee["directors"] = company["directors"]
    if company.get("secretary"):
        trustee["secretary"] = company["secretary"]
    if company.get("shareholders"):
        trustee["shareholders"] = company["shareholders"]


def _extract_people_after_labels(pages: list[PageText], text: str, labels: list[str]) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = []
    for label in labels:
        pattern = rf"{label}s?[:\s]+([A-Z][A-Za-z ,.'-]{{2,120}})"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = normalise_person(match.group(1))
            if candidate and candidate.lower() not in {p["name"].lower() for p in people}:
                page = _page_for(pages, match.group(0))
                people.append({
                    "name": candidate,
                    "source_document_id": page.source_document_id,
                    "page": page.page,
                    "quote": clamp_quote(match.group(0), 50),
                    "confidence": "low",
                })
    return people


def _extract_named_clause(result: dict[str, Any], pages: list[PageText], text: str, field_path: str, keywords: list[str], heading: str) -> None:
    best: tuple[str, PageText, str] | None = None
    for keyword in keywords:
        sentence_match = re.search(rf"[^.\n]*\bclause\s+([0-9]+(?:\.[0-9A-Za-z]+)*)(?:\([a-z]\))?[^.\n]*{re.escape(keyword)}[^.\n]*[.\n]", text, re.IGNORECASE)
        if sentence_match:
            clause = sentence_match.group(1)
            quote = sentence_match.group(0)
            page = _page_for(pages, quote[:40])
            best = (f"clause {clause}", page, quote)
            break
        match = re.search(rf"(.{{0,220}}\bclause\s+([0-9]+(?:\.[0-9A-Za-z]+)*)(?:\([a-z]\))?.{{0,220}}{re.escape(keyword)}.{{0,220}})|(.{{0,220}}{re.escape(keyword)}.{{0,220}}\bclause\s+([0-9]+(?:\.[0-9A-Za-z]+)*)(?:\([a-z]\))?.{{0,220}})", text, re.IGNORECASE | re.DOTALL)
        if match:
            clause = match.group(2) or match.group(4)
            quote = match.group(0)
            page = _page_for(pages, quote[:40])
            best = (f"clause {clause}", page, quote)
            break
    if not best:
        return
    _set_path(result, field_path, value(best[0], best[1].source_document_id, best[1].page, clause_ref=best[0], heading=heading, quote=best[2], confidence="medium"))


def _add_missing_clause_issues(result: dict[str, Any]) -> None:
    required_clause_paths = {
        "trust.vesting.clause_ref": "Vesting or perpetuity provision reference could not be identified.",
        "income.definition_clause_ref": "Income definition clause could not be identified.",
        "income.distribution_power_clause_ref": "Income distribution power clause could not be identified.",
        "distribution.method_clause_ref": "Distribution method clause could not be identified.",
    }
    for path, message in required_clause_paths.items():
        if not _get_path(result, path, {}).get("value"):
            _set_path(result, path, empty_value(None, issue_if_any=message))
            result["issues"].append({
                "code": "CLAUSE_NOT_FOUND",
                "message": message,
                "field_path": path,
                "blocking": path in {"trust.vesting.clause_ref", "income.definition_clause_ref", "income.distribution_power_clause_ref"},
            })


def _first_match(text: str, patterns: list[str], *, group: int = 1) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                return re.sub(r"\s+", " ", match.group(group)).strip(" .,\n\t")
            except IndexError:
                continue
    return None


def _first_regex_hit(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip(" .,\n\t")
    return None


def _page_for(pages: list[PageText], needle: str) -> PageText:
    needle_norm = (needle or "").lower()[:80]
    for page in pages:
        if needle_norm and needle_norm in page.text.lower():
            return page
    return pages[0] if pages else PageText("unknown", 1, "")


def _quote_around(text: str, needle: str, radius: int = 260) -> str:
    lower = text.lower()
    start = lower.find((needle or "").lower()[:80])
    if start < 0:
        return clamp_quote(text[: radius * 2], 50)
    left = max(0, start - radius)
    right = min(len(text), start + len(needle) + radius)
    return clamp_quote(text[left:right], 50)


def _normalise_acn(acn: str) -> str:
    digits = re.sub(r"\D", "", acn)
    if len(digits) == 9:
        return f"{digits[0:3]} {digits[3:6]} {digits[6:9]}"
    return acn.strip()


def _clean_party_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name)
    cleaned = re.sub(r"\b(?:made\s+)?between\b", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.;")


def _clean_schedule_value(raw: str) -> str:
    cleaned = _normalise_sentence(raw)
    cleaned = re.sub(r"\s+\[\d+\]\s*$", "", cleaned)
    cleaned = re.sub(r"\s+Signing Page.*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.;")


def _schedule_value(raw: str, labels: tuple[str, ...]) -> str:
    cleaned = _clean_schedule_value(raw)
    for label in labels:
        pattern = r"^" + re.escape(label).replace(r"\ ", r"\s+") + r"\s+"
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" ,.;")


def _infer_jurisdiction(result: dict[str, Any], text: str) -> str | None:
    governing_law = str(result.get("trust", {}).get("governing_law", {}).get("value") or "")
    haystacks = [governing_law, text]
    for haystack in haystacks:
        if not haystack:
            continue
        for jurisdiction, patterns in JURISDICTION_PATTERNS.items():
            if any(re.search(pattern, haystack, re.IGNORECASE) for pattern in patterns):
                return jurisdiction
    return None


def _normalise_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" .,\n\t")


def normalise_person(value: str) -> str:
    value = re.split(r"\b(?:Address|Born|Appointed|Role|Status)\b", value, flags=re.IGNORECASE)[0]
    return re.sub(r"\s+", " ", value).strip(" ,.;")


def _set_path(data: dict[str, Any], path: str, new_value: Any) -> None:
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = new_value


def _get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def validate_ooxml_readable(path: str | Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return zf.testzip() is None and "word/document.xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False
