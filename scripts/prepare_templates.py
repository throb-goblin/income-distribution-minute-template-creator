"""Prepare macro-free working minute templates and verify field maps.

Usage:
    python scripts/prepare_templates.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.word_ooxml import (  # noqa: E402
    FIELDMAP_DIR,
    WORKING_DIR,
    detect_manual_page_break_branches,
    macro_free_copy,
    package_has_activex,
    package_has_macros,
)


SOURCES = {
    "discretionary": ("Discretionary Trust Minute Template - User Form.docm", "discretionary_trust_minute.docx"),
    "unit": ("Unit Trust Minute Template - User Form.docm", "unit_trust_minute.docx"),
}


def main() -> None:
    prepared = prepare_templates()
    print(json.dumps(prepared, indent=2))


def prepare_templates() -> dict[str, object]:
    WORKING_DIR.mkdir(parents=True, exist_ok=True)
    stale_checklist = WORKING_DIR / "trust_minute_checklist.docx"
    if stale_checklist.exists():
        stale_checklist.unlink()
    prepared = []
    for kind, (source_name, dest_name) in SOURCES.items():
        source = ROOT / "templates" / "source" / source_name
        dest = WORKING_DIR / dest_name
        if not source.exists():
            raise FileNotFoundError(source)
        macro_free_copy(source, dest)
        prepared.append({
            "kind": kind,
            "source": str(source.relative_to(ROOT)),
            "working": str(dest.relative_to(ROOT)),
            "source_macros_present": package_has_macros(source),
            "source_activex_present": package_has_activex(source),
            "working_macros_present": package_has_macros(dest),
            "working_activex_present": package_has_activex(dest),
            "branches": [branch.label for branch in detect_manual_page_break_branches(dest)],
        })
    _verify_fieldmaps_exist()
    return {
        "prepared_templates": prepared,
        "fieldmaps": sorted(path.name for path in FIELDMAP_DIR.glob("*.fieldmap.json")),
        "runtime_requires_word": False,
        "runtime_requires_macros_or_activex": False,
    }


def _verify_fieldmaps_exist() -> None:
    required = {
        "checklist.fieldmap.json",
        "discretionary_minute.fieldmap.json",
        "unit_minute.fieldmap.json",
    }
    missing = [name for name in required if not (FIELDMAP_DIR / name).exists()]
    if missing:
        raise FileNotFoundError(f"Missing field map(s): {', '.join(missing)}")


if __name__ == "__main__":
    main()
