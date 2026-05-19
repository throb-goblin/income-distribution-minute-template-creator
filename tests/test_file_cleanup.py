from __future__ import annotations

from app import security


def test_temp_files_deleted_after_completion(monkeypatch) -> None:
    monkeypatch.setattr(security, "SETTINGS", security.SecuritySettings(keep_temp_files=False))
    with security.matter_tempdir() as temp_dir:
        path = temp_dir / "matter.txt"
        path.write_text("temporary matter file", encoding="utf-8")
        assert path.exists()
        temp_dir_path = temp_dir
    assert not temp_dir_path.exists()
