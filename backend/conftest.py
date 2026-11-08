import os
import sys
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

ROOT = Path(__file__).resolve().parent

# Test modules contain destructive reset fixtures; always direct their engine
# to a disposable per-process database rather than inheriting a deployment URL.
test_database = Path(gettempdir()) / f"testnova-tests-{os.getpid()}-{uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{test_database.as_posix()}"
os.environ["GEMINI_API_KEY"] = "test-only-not-a-real-key"
os.environ["JWT_SECRET_KEY"] = "test-only-signing-key-not-for-deployment"
os.environ["AUTO_CREATE_SCHEMA"] = "true"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
