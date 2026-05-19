"""Endpoint implementation functions for the FastAPI app."""

from __future__ import annotations

import base64
import copy
import os
import uuid
from pathlib import Path
from typing import Any

from .diagnostics import describe_file_refs, log_info
from .extraction import extract_trust_minute_data
from .render_checklist import render_checklist, render_checklist_markdown
from .render_minute import render_minute
from .security import local_file_ref, matter_tempdir, sanitize_filename, write_temp_file
from .validation import validate_for_checklist, validate_for_minute


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SESSION_STORE: dict[str, dict[str, Any]] = {}


def extract_action(payload: dict[str, Any]) -> dict[str, Any]:
    refs = payload.get("openaiFileIdRefs") or {}
    matter_metadata = payload.get("matter") or {}
    log_info("extract_action.start", refs=describe_file_refs(refs), matter_keys=sorted(matter_metadata.keys()))
    with matter_tempdir() as temp_dir:
        trust_path, company_path = resolve_input_files(refs, temp_dir)
        log_info(
            "extract_action.files_resolved",
            trust_name=trust_path.name,
            trust_size=trust_path.stat().st_size if trust_path.exists() else None,
            company_name=company_path.name if company_path else None,
            company_size=company_path.stat().st_size if company_path and company_path.exists() else None,
        )
        extraction_result = extract_trust_minute_data(trust_path, company_path, matter_metadata=matter_metadata)

    validation_result = validate_for_checklist(extraction_result)
    session_id = str(uuid.uuid4())
    SESSION_STORE[session_id] = {
        "extraction_result": extraction_result,
        "validation_result": validation_result,
        "checklist_summary": None,
        "checklist_id": None,
        "approved_checklist": None,
        "checklist_docx": None,
        "minute_summary": None,
        "minute_docx": None,
    }
    log_info(
        "extract_action.success",
        session_id=session_id,
        trust_name=_field_value(extraction_result, "trust.name"),
        trust_type=_field_value(extraction_result, "trust.type"),
        validation_valid=validation_result.get("valid"),
        blocking_count=len(validation_result.get("blocking_issues", [])),
    )
    return {
        "session_id": session_id,
        "extraction_result": extraction_result,
        "validation_result": validation_result,
    }


def generate_checklist_action(payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(payload["session_id"])
    data = _with_overrides(session["extraction_result"], payload.get("user_overrides"))
    log_info("generate_checklist.start", session_id=payload["session_id"])
    validation_result = validate_for_checklist(data)
    if not validation_result["valid"]:
        log_info(
            "generate_checklist.validation_blocked",
            session_id=payload["session_id"],
            blocking_count=len(validation_result.get("blocking_issues", [])),
        )
        return {
            "checklist_summary": None,
            "validation_result": validation_result,
        }

    checklist_id = str(uuid.uuid4())
    markdown = render_checklist_markdown(data)
    summary = {
        "trust_name": _field_value(data, "trust.name"),
        "trust_type": _field_value(data, "trust.type"),
        "checklist_id": checklist_id,
        "checklist_markdown": markdown,
        "review_format": "markdown",
        "word_checklist_deferred_until_minute_generation": True,
        "unresolved_issues": data.get("issues", []),
    }
    session["extraction_result"] = data
    session["validation_result"] = validation_result
    session["checklist_summary"] = summary
    session["checklist_id"] = checklist_id
    session["checklist_docx"] = None
    log_info(
        "generate_checklist.success",
        session_id=payload["session_id"],
        checklist_id=checklist_id,
        markdown_len=len(markdown),
        validation_valid=validation_result.get("valid"),
    )
    return {
        "checklist_summary": summary,
        "validation_result": validation_result,
    }


def validate_action(payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(payload["session_id"])
    data = _with_overrides(session["extraction_result"], payload.get("proposed_overrides"))
    return validate_for_minute(
        data,
        distribution_instructions=payload.get("distribution_instructions"),
        approved_checklist=payload.get("approved_checklist") or _approved_from_id(session, payload.get("approved_checklist_id")),
    )


def generate_minute_action(payload: dict[str, Any]) -> dict[str, Any]:
    session = _get_session(payload["session_id"])
    data = _with_overrides(session["extraction_result"], payload.get("user_overrides"))
    approved_checklist = payload.get("approved_checklist") or _approved_from_id(session, payload.get("approved_checklist_id"))
    distribution_instructions = payload.get("distribution_instructions") or {}
    validation_result = validate_for_minute(
        data,
        distribution_instructions=distribution_instructions,
        approved_checklist=approved_checklist,
    )
    if not validation_result["valid"]:
        return {
            "minute_summary": None,
            "validation_result": validation_result,
            "openaiFileResponse": None,
        }

    minute_docx, summary = render_minute(
        data,
        distribution_instructions=distribution_instructions,
        approved_checklist=approved_checklist,
        output_options=payload.get("output_options"),
    )
    checklist_docx, checklist_summary = render_checklist(data, approved=bool(approved_checklist))
    session["extraction_result"] = data
    session["minute_summary"] = summary
    session["minute_docx"] = minute_docx
    session["checklist_docx"] = checklist_docx
    return {
        "minute_summary": {**summary, "final_checklist_summary": checklist_summary},
        "validation_result": validation_result,
        "openaiFileResponse": [
            *openai_file_response("trust-minute-final-checklist.docx", checklist_docx, DOCX_MIME),
            *openai_file_response("trust-income-distribution-minute-template.docx", minute_docx, DOCX_MIME),
        ],
    }


def resolve_input_files(openai_file_id_refs: dict[str, Any], temp_dir: Path) -> tuple[Path, Path | None]:
    if isinstance(openai_file_id_refs, list):
        if not openai_file_id_refs:
            raise ValueError("openaiFileIdRefs must include the trust instrument.")
        trust_ref, company_ref = _split_file_ref_list(openai_file_id_refs)
        trust_path = _resolve_one_file(trust_ref, temp_dir, default_filename="trust-instrument.pdf")
        company_path = _resolve_one_file(company_ref, temp_dir, default_filename="company-report.pdf") if company_ref else None
        return trust_path, company_path

    trust_ref = (
        openai_file_id_refs.get("trust_instrument")
        or openai_file_id_refs.get("trustInstrument")
        or openai_file_id_refs.get("trust_instrument_file")
    )
    if not trust_ref:
        raise ValueError("openaiFileIdRefs.trust_instrument is required.")
    company_ref = openai_file_id_refs.get("company_report") or openai_file_id_refs.get("companyReport")
    trust_path = _resolve_one_file(trust_ref, temp_dir, default_filename="trust-instrument.pdf")
    company_path = _resolve_one_file(company_ref, temp_dir, default_filename="company-report.pdf") if company_ref else None
    return trust_path, company_path


def _resolve_one_file(ref: Any, temp_dir: Path, *, default_filename: str) -> Path:
    if isinstance(ref, (str, Path)):
        text = str(ref)
        if Path(text).exists():
            return local_file_ref(text)
        return _download_openai_file({"id": text, "filename": default_filename}, temp_dir)
    if isinstance(ref, dict):
        path_value = ref.get("path") or ref.get("local_path") or ref.get("downloaded_path")
        if path_value:
            return local_file_ref(path_value)
        content_base64 = ref.get("content_base64")
        if content_base64:
            filename = ref.get("name") or ref.get("filename") or default_filename
            return write_temp_file(temp_dir, filename, base64.b64decode(content_base64))
        file_id = ref.get("id") or ref.get("file_id") or ref.get("openai_file_id")
        if file_id:
            return _download_openai_file({**ref, "id": file_id, "filename": ref.get("name") or ref.get("filename") or default_filename}, temp_dir)
    raise ValueError("Unsupported file reference format.")


def _download_openai_file(ref: dict[str, Any], temp_dir: Path) -> Path:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("Downloading OpenAI files requires httpx. Install project requirements first.") from exc

    download_link = ref.get("download_link") or ref.get("download_url") or ref.get("url")
    if download_link:
        if not str(download_link).lower().startswith(("http://", "https://")):
            log_info("download_openai_file.unsupported_download_link_scheme", ref=describe_file_refs(ref))
        else:
            log_info("download_openai_file.start", ref=describe_file_refs(ref))
            timeout = httpx.Timeout(180.0, connect=30.0)
            response = httpx.get(download_link, timeout=timeout, follow_redirects=True)
            log_info(
                "download_openai_file.response",
                ref=describe_file_refs(ref),
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                content_length=response.headers.get("content-length"),
                bytes_received=len(response.content),
            )
            response.raise_for_status()
            filename = ref.get("name") or ref.get("filename") or "uploaded-file"
            return write_temp_file(temp_dir, filename, response.content)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required when an OpenAI file reference does not include a reachable HTTP(S) download_link.")
    file_id = ref["id"]
    filename = sanitize_filename(ref.get("filename") or f"{file_id}.pdf")
    url = f"https://api.openai.com/v1/files/{file_id}/content"
    log_info("download_openai_file.files_api_start", ref=describe_file_refs(ref))
    response = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=httpx.Timeout(180.0, connect=30.0), follow_redirects=True)
    log_info(
        "download_openai_file.files_api_response",
        ref=describe_file_refs(ref),
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        content_length=response.headers.get("content-length"),
        bytes_received=len(response.content),
    )
    response.raise_for_status()
    return write_temp_file(temp_dir, filename, response.content)


def _split_file_ref_list(file_refs: list[Any]) -> tuple[Any, Any | None]:
    company_ref = None
    trust_ref = None
    for ref in file_refs:
        name = ""
        if isinstance(ref, dict):
            name = str(ref.get("name") or ref.get("filename") or "").lower()
        elif isinstance(ref, str):
            name = ref.lower()
        if any(token in name for token in ("company", "asic", "extract", "report")):
            company_ref = ref
        elif trust_ref is None:
            trust_ref = ref
        elif company_ref is None:
            company_ref = ref
    return trust_ref or file_refs[0], company_ref


def openai_file_response(filename: str, content: bytes, mime_type: str) -> list[dict[str, Any]]:
    return [
        {
            "name": filename,
            "mime_type": mime_type,
            "content": base64.b64encode(content).decode("ascii"),
        }
    ]


def _get_session(session_id: str) -> dict[str, Any]:
    try:
        return SESSION_STORE[session_id]
    except KeyError as exc:
        raise KeyError(f"Unknown session_id: {session_id}") from exc


def _with_overrides(data: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(data)
    if overrides:
        _deep_merge(merged, overrides)
    return merged


def _deep_merge(target: dict[str, Any], overrides: dict[str, Any]) -> None:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            if "value" in target[key] and "value" not in value:
                target[key]["value"] = value
                target[key]["confidence"] = "high"
            else:
                _deep_merge(target[key], value)
        else:
            if isinstance(target.get(key), dict) and "value" in target[key]:
                target[key]["value"] = value
                target[key]["confidence"] = "high"
            else:
                target[key] = value


def _field_value(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    if isinstance(current, dict) and "value" in current:
        return current.get("value")
    return current


def _approved_from_id(session: dict[str, Any], approved_checklist_id: str | None) -> dict[str, Any] | None:
    if approved_checklist_id and approved_checklist_id == session.get("checklist_id"):
        approved = {"approved": True, "approved_checklist_id": approved_checklist_id, "summary": session.get("checklist_summary")}
        session["approved_checklist"] = approved
        return approved
    if session.get("approved_checklist"):
        return session["approved_checklist"]
    return None
