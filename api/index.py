"""Vercel serverless entry point for the TestNova FastAPI application."""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import app as backend_app  # noqa: E402


async def app(scope, receive, send):
    """Expose backend routes below Vercel's /api function path."""
    if scope["type"] == "http" and scope["path"].startswith("/api"):
        scope = dict(scope)
        stripped_path = scope["path"][4:] or "/"
        scope["path"] = stripped_path
        scope["raw_path"] = stripped_path.encode("utf-8")
    await backend_app(scope, receive, send)

