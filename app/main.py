"""FastAPI entrypoint for the income distribution minute template action service."""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .diagnostics import log_exception, log_info
from .actions import (
    extract_action,
    generate_checklist_action,
    generate_minute_action,
    validate_action,
)


app = FastAPI(
    title="Income Distribution Minute Template Creator",
    version="0.1.0",
    description="Extracts trust facts, renders a checklist first, and generates draft income distribution minutes after approval.",
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    client = request.client.host if request.client else None
    log_info("request.start", method=request.method, path=request.url.path, client=client)
    try:
        response = await call_next(request)
    except Exception as exc:
        log_exception("request.unhandled", exc, extra={"method": request.method, "path": request.url.path, "client": client})
        raise
    log_info(
        "request.finish",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - start) * 1000, 2),
        client=client,
    )
    return response


class ExtractRequest(BaseModel):
    openaiFileIdRefs: dict[str, Any] | list[Any] = Field(..., description="Trust instrument and optional company report file references.")
    matter: dict[str, Any] = Field(default_factory=dict)


class GenerateChecklistRequest(BaseModel):
    session_id: str
    user_overrides: dict[str, Any] | None = None


class ValidateRequest(BaseModel):
    session_id: str
    proposed_overrides: dict[str, Any] | None = None
    approved_checklist: dict[str, Any] | None = None
    approved_checklist_id: str | None = None


class GenerateMinuteRequest(BaseModel):
    session_id: str
    approved_checklist: dict[str, Any] | None = None
    approved_checklist_id: str | None = None
    output_options: dict[str, Any] | None = None
    user_overrides: dict[str, Any] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    error_id = log_exception("request_validation", exc, extra={"path": str(request.url.path)})
    return JSONResponse(
        status_code=200,
        content=_action_error_payload(_stage_from_path(request.url.path), exc, error_id=error_id),
    )


@app.post("/extract", operation_id="extractTrustFacts")
def extract(request: ExtractRequest) -> dict[str, Any]:
    try:
        return extract_action(request.model_dump())
    except Exception as exc:
        error_id = log_exception("extractTrustFacts", exc, extra={"openaiFileIdRefs_type": type(request.openaiFileIdRefs).__name__})
        return _action_error_payload("extract", exc, error_id=error_id)


@app.post("/generate-checklist", operation_id="generateTrustChecklist")
def generate_checklist(request: GenerateChecklistRequest) -> dict[str, Any]:
    try:
        return generate_checklist_action(request.model_dump())
    except Exception as exc:
        error_id = log_exception("generateTrustChecklist", exc, extra={"session_id": request.session_id})
        return _action_error_payload("checklist", exc, error_id=error_id)


@app.post("/validate", operation_id="validateTrustMinuteInputs")
def validate(request: ValidateRequest) -> dict[str, Any]:
    try:
        return validate_action(request.model_dump())
    except Exception as exc:
        error_id = log_exception("validateTrustMinuteInputs", exc, extra={"session_id": request.session_id})
        return _action_error_payload("validate", exc, error_id=error_id)


@app.post("/generate-minute", operation_id="generateTrustMinute")
def generate_minute(request: GenerateMinuteRequest) -> dict[str, Any]:
    try:
        return generate_minute_action(request.model_dump())
    except Exception as exc:
        error_id = log_exception("generateTrustMinute", exc, extra={"session_id": request.session_id})
        return _action_error_payload("minute", exc, error_id=error_id)


def _stage_from_path(path: str) -> str:
    if "generate-checklist" in path:
        return "checklist"
    if "validate" in path:
        return "validate"
    if "generate-minute" in path:
        return "minute"
    return "extract"


def _action_error_payload(stage: str, exc: BaseException, *, error_id: str) -> dict[str, Any]:
    validation_result = {
        "stage": stage,
        "valid": False,
        "can_generate_checklist": False,
        "can_generate_minute": False,
        "blocking_issues": [
            {
                "code": "ACTION_ERROR",
                "message": f"{exc.__class__.__name__}: {str(exc)}",
                "severity": "blocking",
            }
        ],
        "non_blocking_issues": [],
    }
    error = {
        "error_id": error_id,
        "type": exc.__class__.__name__,
        "message": str(exc),
        "log_path": "tmp/logs/action-service.log",
    }
    if stage == "extract":
        return {
            "session_id": None,
            "extraction_result": None,
            "validation_result": validation_result,
            "error": error,
        }
    if stage == "checklist":
        return {
            "checklist_summary": None,
            "validation_result": validation_result,
            "error": error,
        }
    if stage == "minute":
        return {
            "minute_summary": None,
            "validation_result": validation_result,
            "openaiFileResponse": None,
            "error": error,
        }
    return {
        **validation_result,
        "error": error,
    }
