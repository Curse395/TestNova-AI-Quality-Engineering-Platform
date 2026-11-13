from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import BinaryIO


FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
CHECKSUM_SUFFIX = ".sha256"
MAX_BACKUP_FILES = 100_000
MAX_RESTORE_FILE_SIZE = 256 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_NAMES = {".env", "credentials", "secrets"}


class BackupError(ValueError):
    pass


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise BackupError("Backup destination must be a non-symlink directory")
    if os.name == "posix" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise BackupError("Backup destination permissions must be restricted to its owner")


def _open_private_file(path: Path) -> BinaryIO:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, "wb")
    except Exception:
        os.close(descriptor)
        raise


def _utc_timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Backup timestamp must be timezone-aware")
    return current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def timestamped_backup_path(
    destination_dir: Path,
    *,
    now: datetime | None = None,
) -> Path:
    return destination_dir / f"testnova-uploads-{_utc_timestamp(now)}.zip"


def _validate_upload_tree(source_dir: Path) -> list[tuple[Path, str]]:
    source = source_dir.resolve()
    if source_dir.is_symlink() or not source.is_dir():
        raise BackupError("Upload source must be an existing non-symlink directory")

    files: list[tuple[Path, str]] = []
    for project_dir in sorted(source.iterdir()):
        if project_dir.is_symlink():
            raise BackupError("Upload source contains a symbolic link")
        if not project_dir.is_dir() or not project_dir.name.isdecimal():
            raise BackupError("Upload source contains an unexpected entry")

        for file_path in sorted(project_dir.iterdir()):
            if file_path.is_symlink():
                raise BackupError("Upload source contains a symbolic link")
            if not file_path.is_file():
                raise BackupError("Upload source contains an unexpected entry")
            if _is_sensitive_name(file_path.name):
                continue
            if file_path.name.startswith(".") and file_path.name.endswith(".upload"):
                raise BackupError("An upload is in progress; quiesce uploads and retry")
            if file_path.name.startswith("."):
                raise BackupError("Upload source contains an unexpected hidden file")
            relative_name = f"{project_dir.name}/{file_path.name}"
            files.append((file_path, relative_name))
            if len(files) > MAX_BACKUP_FILES:
                raise BackupError("Upload source exceeds the supported file count")
    return files


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _checksum_path(archive_path: Path) -> Path:
    return Path(f"{archive_path}{CHECKSUM_SUFFIX}")


def _is_sensitive_name(name: str) -> bool:
    normalized = name.casefold()
    return normalized in _SENSITIVE_NAMES or normalized.startswith(".env")


def _write_checksum(archive_path: Path, checksum_path: Path) -> None:
    digest, _ = _sha256_file(archive_path)
    created = False
    try:
        with _open_private_file(checksum_path) as checksum_file:
            created = True
            checksum_file.write(f"{digest}  {archive_path.name}\n".encode("ascii"))
    except Exception:
        if created:
            checksum_path.unlink(missing_ok=True)
        raise


def _load_and_verify_archive(archive_path: Path) -> tuple[dict, list[zipfile.ZipInfo]]:
    checksum_path = _checksum_path(archive_path)
    try:
        checksum_line = checksum_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise BackupError("Backup checksum file is unavailable or invalid") from exc

    expected_checksum, separator, recorded_name = checksum_line.partition("  ")
    if (
        not separator
        or recorded_name != archive_path.name
        or not _SHA256_PATTERN.fullmatch(expected_checksum)
    ):
        raise BackupError("Backup checksum file is malformed")
    actual_checksum, _ = _sha256_file(archive_path)
    if actual_checksum != expected_checksum:
        raise BackupError("Backup archive checksum does not match")

    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError("Backup archive cannot be opened") from exc

    with archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if (
            len(members) > MAX_BACKUP_FILES + 1
            or len(names) != len(set(names))
            or MANIFEST_NAME not in names
        ):
            raise BackupError("Backup archive member list is invalid")
        member_by_name = {item.filename: item for item in members}
        manifest_info = member_by_name[MANIFEST_NAME]
        if manifest_info.is_dir() or manifest_info.file_size > 10 * 1024 * 1024:
            raise BackupError("Backup manifest exceeds the supported size")
        for info in members:
            if info.filename == MANIFEST_NAME:
                continue
            if info.is_dir() or info.file_size > MAX_RESTORE_FILE_SIZE:
                raise BackupError("Backup archive contains an unsupported file")

        bad_member = archive.testzip()
        if bad_member is not None:
            raise BackupError("Backup archive integrity check failed")
        try:
            manifest = json.loads(archive.read(MANIFEST_NAME))
        except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
            raise BackupError("Backup manifest is missing or invalid") from exc

        if (
            not isinstance(manifest, dict)
            or manifest.get("format_version") != FORMAT_VERSION
            or not isinstance(manifest.get("created_at"), str)
            or not isinstance(manifest.get("files"), list)
            or len(manifest["files"]) > MAX_BACKUP_FILES
        ):
            raise BackupError("Backup manifest has an unsupported structure")

        expected_files: dict[str, dict] = {}
        for item in manifest["files"]:
            if not isinstance(item, dict):
                raise BackupError("Backup manifest contains an invalid entry")
            member_name = item.get("path")
            path = PurePosixPath(member_name) if isinstance(member_name, str) else None
            if (
                path is None
                or path.is_absolute()
                or len(path.parts) != 2
                or path.parts[0] in {"", ".", ".."}
                or not path.parts[0].isdecimal()
                or path.parts[1] in {"", ".", ".."}
                or path.parts[1].startswith(".")
                or _is_sensitive_name(path.parts[1])
                or "\\" in member_name
                or str(path) != member_name
                or member_name in expected_files
                or isinstance(item.get("size"), bool)
                or not isinstance(item.get("size"), int)
                or item["size"] < 0
                or item["size"] > MAX_RESTORE_FILE_SIZE
                or not isinstance(item.get("sha256"), str)
                or not _SHA256_PATTERN.fullmatch(item["sha256"])
            ):
                raise BackupError("Backup manifest contains an unsafe entry")
            expected_files[member_name] = item

        if set(names) != {MANIFEST_NAME, *expected_files}:
            raise BackupError("Backup archive entries do not match its manifest")
        for name, metadata in expected_files.items():
            info = member_by_name[name]
            if info.is_dir() or info.file_size != metadata["size"]:
                raise BackupError("Backup archive entry size does not match its manifest")
            digest = hashlib.sha256()
            size = 0
            with archive.open(info) as content:
                for block in iter(lambda: content.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
            if size != metadata["size"] or digest.hexdigest() != metadata["sha256"]:
                raise BackupError("Backup file integrity check failed")
        return manifest, members


def verify_backup(archive_path: Path) -> dict:
    manifest, _ = _load_and_verify_archive(archive_path)
    return manifest


def create_backup(
    source_dir: Path,
    destination_dir: Path,
    *,
    now: datetime | None = None,
) -> Path:
    source = source_dir.resolve()
    destination = destination_dir.resolve()
    if _is_relative_to(destination, source):
        raise BackupError("Backup destination must not be inside the upload source")
    _ensure_private_directory(destination_dir)

    files = _validate_upload_tree(source_dir)
    manifest_files = []
    for file_path, relative_name in files:
        digest, size = _sha256_file(file_path)
        if size > MAX_RESTORE_FILE_SIZE:
            raise BackupError("An upload exceeds the supported restore size")
        manifest_files.append(
            {"path": relative_name, "size": size, "sha256": digest}
        )

    archive_path = timestamped_backup_path(destination_dir, now=now)
    checksum_path = _checksum_path(archive_path)
    created_archive = False
    created_checksum = False
    try:
        with _open_private_file(archive_path) as output:
            created_archive = True
            with zipfile.ZipFile(
                output,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                allowZip64=True,
            ) as archive:
                for file_path, relative_name in files:
                    archive.write(file_path, arcname=relative_name)
                archive.writestr(
                    MANIFEST_NAME,
                    json.dumps(
                        {
                            "format_version": FORMAT_VERSION,
                            "created_at": _utc_timestamp(now),
                            "files": manifest_files,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
        _write_checksum(archive_path, checksum_path)
        created_checksum = True
        verify_backup(archive_path)
        return archive_path
    except Exception:
        if created_checksum:
            checksum_path.unlink(missing_ok=True)
        if created_archive:
            archive_path.unlink(missing_ok=True)
        raise


def restore_backup(archive_path: Path, destination_dir: Path) -> Path:
    manifest, _ = _load_and_verify_archive(archive_path)
    if destination_dir.exists() or destination_dir.is_symlink():
        raise BackupError("Restore destination must not already exist")
    if not destination_dir.parent.is_dir():
        raise BackupError("Restore destination parent must already exist")

    destination_dir.mkdir(mode=0o700)
    created_directories: list[Path] = []
    created_files: list[Path] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for entry in manifest["files"]:
                relative_path = PurePosixPath(entry["path"])
                parent = destination_dir / relative_path.parts[0]
                if not parent.exists():
                    parent.mkdir(mode=0o700)
                    created_directories.append(parent)
                target = parent / relative_path.parts[1]
                with archive.open(entry["path"], "r") as source:
                    with _open_private_file(target) as output:
                        created_files.append(target)
                        digest = hashlib.sha256()
                        size = 0
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            output.write(block)
                            digest.update(block)
                            size += len(block)
                if size != entry["size"] or digest.hexdigest() != entry["sha256"]:
                    raise BackupError("Restored file integrity check failed")
        return destination_dir
    except Exception:
        for file_path in reversed(created_files):
            file_path.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            directory.rmdir()
        destination_dir.rmdir()
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Back up and restore TestNova's local uploaded documents."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="Create a timestamped upload archive")
    backup.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "app" / "uploads",
    )
    backup.add_argument("--destination-dir", type=Path, required=True)

    verify = commands.add_parser("verify", help="Verify an archive and its checksums")
    verify.add_argument("--archive", type=Path, required=True)

    restore = commands.add_parser("restore", help="Restore into a new empty directory")
    restore.add_argument("--archive", type=Path, required=True)
    restore.add_argument("--destination-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "backup":
            path = create_backup(args.source_dir, args.destination_dir)
            print(f"Upload backup created and verified: {path}")
        elif args.command == "verify":
            manifest = verify_backup(args.archive)
            print(f"Backup verified: {len(manifest['files'])} uploaded file(s)")
        else:
            path = restore_backup(args.archive, args.destination_dir)
            print(f"Uploaded files restored and verified: {path}")
    except (BackupError, OSError, zipfile.BadZipFile, ValueError) as exc:
        print(f"Backup operation failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
