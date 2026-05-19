"""File handling and cleanup utilities."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


ALLOWED_INPUT_EXTENSIONS = {".pdf", ".docx", ".docm", ".dotx", ".dotm", ".txt"}


@dataclass(frozen=True)
class SecuritySettings:
    keep_temp_files: bool = os.getenv("TRUST_MINUTE_KEEP_TEMP_FILES", "false").lower() in {"1", "true", "yes"}
    max_upload_bytes: int = int(os.getenv("TRUST_MINUTE_MAX_UPLOAD_BYTES", "150000000"))


SETTINGS = SecuritySettings()


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", name or "uploaded-file")
    safe = safe.strip(" .")
    return safe or "uploaded-file"


def assert_allowed_extension(path: Path) -> None:
    if path.suffix.lower() not in ALLOWED_INPUT_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def assert_size_allowed(path: Path) -> None:
    if path.exists() and path.stat().st_size > SETTINGS.max_upload_bytes:
        raise ValueError(f"File exceeds configured size limit: {path.name}")


@contextmanager
def matter_tempdir(prefix: str = "trust-minute-") -> Iterator[Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield temp_dir
    finally:
        if not SETTINGS.keep_temp_files:
            shutil.rmtree(temp_dir, ignore_errors=True)


def write_temp_file(temp_dir: Path, filename: str, content: bytes) -> Path:
    path = temp_dir / sanitize_filename(filename)
    path.write_bytes(content)
    assert_allowed_extension(path)
    assert_size_allowed(path)
    return path


def local_file_ref(path: str | Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    assert_allowed_extension(resolved)
    assert_size_allowed(resolved)
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return resolved
