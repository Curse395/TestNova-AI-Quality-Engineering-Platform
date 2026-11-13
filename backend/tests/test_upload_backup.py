from datetime import datetime, timezone
import os

import pytest

from scripts.backup_uploads import (
    BackupError,
    create_backup,
    restore_backup,
    timestamped_backup_path,
    verify_backup,
)


FIXED_TIME = datetime(2026, 11, 13, 12, 30, 45, tzinfo=timezone.utc)


def test_backup_creates_timestamped_private_archive_and_verifies_contents(tmp_path):
    source = tmp_path / "uploads"
    project_dir = source / "17"
    project_dir.mkdir(parents=True)
    (project_dir / "document.pdf").write_bytes(b"%PDF-1.7 offline test document")
    destination = tmp_path / "backups"

    archive = create_backup(source, destination, now=FIXED_TIME)

    assert archive == timestamped_backup_path(destination, now=FIXED_TIME)
    assert archive.is_file()
    assert archive.with_name(f"{archive.name}.sha256").is_file()
    assert verify_backup(archive)["files"][0]["path"] == "17/document.pdf"
    if os.name == "posix":
        assert archive.stat().st_mode & 0o777 == 0o600
        checksum = archive.with_name(f"{archive.name}.sha256")
        assert checksum.stat().st_mode & 0o777 == 0o600


def test_backup_refuses_to_overwrite_an_existing_timestamped_archive(tmp_path):
    source = tmp_path / "uploads"
    (source / "17").mkdir(parents=True)
    (source / "17" / "document.txt").write_text("preserve", encoding="utf-8")
    destination = tmp_path / "backups"

    first = create_backup(source, destination, now=FIXED_TIME)
    original_archive = first.read_bytes()
    original_checksum = first.with_name(f"{first.name}.sha256").read_bytes()

    with pytest.raises(FileExistsError):
        create_backup(source, destination, now=FIXED_TIME)

    assert first.read_bytes() == original_archive
    assert first.with_name(f"{first.name}.sha256").read_bytes() == original_checksum


def test_backup_detects_corrupted_archive_bytes(tmp_path):
    source = tmp_path / "uploads"
    (source / "4").mkdir(parents=True)
    (source / "4" / "document.txt").write_text("content", encoding="utf-8")
    archive = create_backup(source, tmp_path / "backups", now=FIXED_TIME)
    corrupted = bytearray(archive.read_bytes())
    corrupted[len(corrupted) // 2] ^= 0x01
    archive.write_bytes(corrupted)

    with pytest.raises(BackupError, match="checksum"):
        verify_backup(archive)


def test_backup_fails_without_leaving_partial_output(tmp_path, monkeypatch):
    import scripts.backup_uploads as backup_module
    import zipfile

    source = tmp_path / "uploads"
    (source / "3").mkdir(parents=True)
    (source / "3" / "document.txt").write_text("content", encoding="utf-8")
    destination = tmp_path / "backups"

    def fail_archive_write(*_args, **_kwargs):
        raise OSError("offline archive failure")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail_archive_write)

    with pytest.raises(OSError, match="offline archive failure"):
        create_backup(source, destination, now=FIXED_TIME)

    assert list(destination.iterdir()) == []


def test_restore_verifies_and_recovers_files_without_overwriting_existing_data(
    tmp_path,
):
    source = tmp_path / "uploads"
    project_dir = source / "9"
    project_dir.mkdir(parents=True)
    (project_dir / "document.csv").write_bytes(b"header,value\none,1\n")
    archive = create_backup(source, tmp_path / "backups", now=FIXED_TIME)
    destination = tmp_path / "restored"

    restored = restore_backup(archive, destination)

    assert restored == destination
    assert (destination / "9" / "document.csv").read_bytes() == b"header,value\none,1\n"

    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    with pytest.raises(BackupError, match="must not already exist"):
        restore_backup(archive, existing)
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_backup_rejects_in_progress_uploads(tmp_path):
    source = tmp_path / "uploads"
    project_dir = source / "2"
    project_dir.mkdir(parents=True)
    (project_dir / ".temporary.upload").write_bytes(b"partial")

    with pytest.raises(BackupError, match="in progress"):
        create_backup(source, tmp_path / "backups", now=FIXED_TIME)


def test_restore_rejects_corrupted_file_payload_even_with_updated_archive_checksum(
    tmp_path,
):
    import hashlib
    import zipfile

    source = tmp_path / "uploads"
    (source / "6").mkdir(parents=True)
    (source / "6" / "document.txt").write_bytes(b"original")
    archive = create_backup(source, tmp_path / "backups", now=FIXED_TIME)
    replacement = tmp_path / "replacement.zip"

    with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(
        replacement, "w", compression=zipfile.ZIP_DEFLATED
    ) as changed:
        for item in original.infolist():
            contents = original.read(item.filename)
            if item.filename == "6/document.txt":
                contents = b"modified"
            changed.writestr(item.filename, contents)

    checksum = hashlib.sha256(replacement.read_bytes()).hexdigest()
    replacement.with_name(f"{replacement.name}.sha256").write_text(
        f"{checksum}  {replacement.name}\n",
        encoding="ascii",
    )

    with pytest.raises(BackupError, match="file integrity"):
        verify_backup(replacement)
