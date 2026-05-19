from __future__ import annotations

import base64
from typing import Any

from fastapi.testclient import TestClient

from app.main import app


def test_extract_accepts_current_file_ref_shape_with_inline_content() -> None:
    client = TestClient(app)
    trust_text = (
        "By deed of settlement dated 1 July 2015 made between Example Trustee Pty Ltd "
        "ACN 123 456 789 (Trustee) and Sam Settlor as settlor, a trust was established "
        "known as Example Family Trust. Clause 1.33 states the Vesting Date is 30 June "
        "2095. Clause 9 permits the trustee to distribute income. Clause 1.12 income "
        "means trust income."
    )
    response = client.post(
        "/extract",
        json={
            "openaiFileIdRefs": [
                {
                    "name": "Damini Trust Deed (signed).txt",
                    "id": "file_00000000c7a07201aa3088e12a8f49f9",
                    "mime_type": "text/plain",
                    "content_base64": base64.b64encode(trust_text.encode()).decode(),
                }
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["extraction_result"]["trust"]["name"]["value"] == "Example Family Trust"

    checklist_response = client.post("/generate-checklist", json={"session_id": payload["session_id"]})
    assert checklist_response.status_code == 200
    checklist_payload = checklist_response.json()
    assert checklist_payload["checklist_summary"]["checklist_id"]
    assert checklist_payload["checklist_summary"]["checklist_markdown"].startswith("# Trust Review Checklist")
    assert "openaiFileResponse" not in checklist_payload


def test_generate_minute_returns_approved_checklist_docx(sample_data: dict[str, Any]) -> None:
    client = TestClient(app)
    from app.actions import SESSION_STORE

    session_id = "approved-checklist-test"
    checklist_id = "approved-checklist-id"
    SESSION_STORE[session_id] = {
        "extraction_result": sample_data,
        "validation_result": {"valid": True},
        "checklist_summary": {"checklist_id": checklist_id},
        "checklist_id": checklist_id,
        "approved_checklist": None,
        "checklist_docx": None,
        "minute_summary": None,
        "minute_docx": None,
    }
    response = client.post("/generate-minute", json={"session_id": session_id, "approved_checklist_id": checklist_id})
    assert response.status_code == 200
    payload = response.json()
    assert payload["validation_result"]["valid"]
    assert [item["name"] for item in payload["openaiFileResponse"]] == [
        "trust-minute-final-checklist.docx",
        "trust-income-distribution-minute-template.docx",
    ]
    assert payload["minute_summary"]["final_checklist_summary"]["status_counts"] == {"Approved": 35}


def test_extract_returns_structured_error_instead_of_non_2xx_for_unreachable_file_ref(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)
    response = client.post(
        "/extract",
        json={
            "openaiFileIdRefs": [
                {
                    "name": "Damini Trust Deed (signed).pdf",
                    "id": "file_00000000c7a07201aa3088e12a8f49f9",
                    "mime_type": "application/pdf",
                }
            ]
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] is None
    assert payload["validation_result"]["blocking_issues"][0]["code"] == "ACTION_ERROR"
    assert payload["error"]["type"] == "RuntimeError"
