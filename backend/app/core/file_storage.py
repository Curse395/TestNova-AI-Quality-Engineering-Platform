from pathlib import Path

from fastapi import HTTPException


UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"


def resolve_document_storage_path(storage_path: str, project_id: int) -> Path:
    stored_path = Path(storage_path)
    try:
        upload_root = UPLOAD_ROOT.resolve()
        resolved_path = stored_path.resolve()
        relative_path = resolved_path.relative_to(upload_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The document storage path is outside the upload directory",
        ) from exc

    project_dir = upload_root / str(project_id)
    if (
        UPLOAD_ROOT.is_symlink()
        or len(relative_path.parts) != 2
        or relative_path.parts[0] != str(project_id)
        or stored_path.is_symlink()
        or project_dir.is_symlink()
        or (resolved_path.exists() and not resolved_path.is_file())
    ):
        raise HTTPException(
            status_code=400,
            detail="The document storage path is not a valid uploaded file",
        )

    return resolved_path
