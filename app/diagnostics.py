"""Small logging helpers for action-service troubleshooting."""

from __future__ import annotations

import logging
import traceback
import uuid
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "tmp" / "logs"
LOG_PATH = LOG_DIR / "action-service.log"


def get_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("trust_minute_action")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


LOGGER = get_logger()


def new_error_id() -> str:
    return str(uuid.uuid4())


def log_exception(context: str, exc: BaseException, *, extra: dict[str, Any] | None = None) -> str:
    error_id = new_error_id()
    LOGGER.error(
        "%s failed error_id=%s exc_type=%s message=%s extra=%s\n%s",
        context,
        error_id,
        exc.__class__.__name__,
        str(exc),
        _redact(extra or {}),
        traceback.format_exc(),
    )
    return error_id


def log_info(message: str, **kwargs: Any) -> None:
    LOGGER.info("%s %s", message, _redact(kwargs))


def describe_file_refs(refs: Any) -> Any:
    if isinstance(refs, list):
        return [describe_file_refs(ref) for ref in refs]
    if isinstance(refs, dict):
        return {
            "name": refs.get("name") or refs.get("filename"),
            "id": refs.get("id") or refs.get("file_id") or refs.get("openai_file_id"),
            "mime_type": refs.get("mime_type"),
            "has_download_link": bool(refs.get("download_link") or refs.get("download_url") or refs.get("url")),
            "has_content_base64": bool(refs.get("content_base64")),
            "has_local_path": bool(refs.get("path") or refs.get("local_path") or refs.get("downloaded_path")),
        }
    return {"type": type(refs).__name__, "value_preview": str(refs)[:80]}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"download_link", "download_url", "url", "authorization", "content_base64"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
