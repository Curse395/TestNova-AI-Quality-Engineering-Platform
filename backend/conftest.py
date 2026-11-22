import os
import sys
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parent

# Test modules contain destructive reset fixtures; always direct their engine
# to a disposable per-process database rather than inheriting a deployment URL.
test_database = Path(gettempdir()) / f"testnova-tests-{os.getpid()}-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{test_database.as_posix()}"
os.environ["GEMINI_API_KEY"] = "test-only-not-a-real-key"
os.environ["JWT_SECRET_KEY"] = "test-only-signing-key-not-for-deployment"
os.environ["LLM_FALLBACK_ENABLED"] = "false"
os.environ["AUTO_CREATE_SCHEMA"] = "true"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_in_memory_rate_limits(monkeypatch):
    from app.core.rate_limit import InMemoryRateLimiter
    from app.core import rate_limit

    monkeypatch.setattr(rate_limit, "rate_limiter", InMemoryRateLimiter())
