import asyncio
import io
import json
import logging
import threading
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from app.api import uploads
from app.core import rate_limit
from app.core.config import Settings
from app.core.rate_limit import InMemoryRateLimiter
from app.core.request_context import (
    JsonLogFormatter,
    RequestContextMiddleware,
    configure_structured_logging,
    request_id_context,
)


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


def _request(host="192.0.2.10"):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": (host, 1234),
            "scheme": "http",
        }
    )


def test_rate_limiter_enforces_sliding_window_and_retry_time():
    clock = FakeClock()
    limiter = InMemoryRateLimiter(clock=clock)

    assert limiter.check("login", "client", limit=2, window_seconds=60) == (True, 0)
    assert limiter.check("login", "client", limit=2, window_seconds=60) == (True, 0)
    assert limiter.check("login", "client", limit=2, window_seconds=60) == (False, 60)

    clock.value += 60
    assert limiter.check("login", "client", limit=2, window_seconds=60) == (True, 0)


def test_rate_limiter_is_thread_safe_for_simultaneous_requests():
    limiter = InMemoryRateLimiter()
    barrier = threading.Barrier(20)
    outcomes = []
    lock = threading.Lock()

    def check_request():
        barrier.wait()
        outcome = limiter.check(
            "generation",
            "same-client",
            limit=4,
            window_seconds=60,
        )[0]
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=check_request) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert sum(outcomes) == 4
    assert len(outcomes) == 20


def test_rate_limit_dependency_returns_429_and_retry_after(monkeypatch):
    limiter = InMemoryRateLimiter()
    monkeypatch.setattr(rate_limit, "rate_limiter", limiter)
    enforce = rate_limit.limit_requests("login", limit=1, window_seconds=30)

    enforce(_request())
    with pytest.raises(HTTPException) as error:
        enforce(_request())

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "30"


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("requirements.txt", "application/octet-stream", "text/plain"),
        ("requirements.csv", "text/csv", "text/csv"),
        ("requirements.json", "application/json", "application/json"),
        ("requirements.pdf", "application/pdf", "application/pdf"),
    ],
)
def test_upload_content_type_is_canonicalized(filename, content_type, expected):
    assert uploads._validate_upload(filename, content_type) == expected


def test_upload_rejects_unsupported_or_mismatched_content_type():
    with pytest.raises(HTTPException) as unsupported:
        uploads._validate_upload("program.exe", "application/octet-stream")
    assert unsupported.value.status_code == 415

    with pytest.raises(HTTPException) as mismatch:
        uploads._validate_upload("requirements.json", "image/png")
    assert mismatch.value.status_code == 415


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../requirements.txt", "requirements.txt"),
        (r"..\..\requirements.txt", "requirements.txt"),
    ],
)
def test_upload_filename_is_reduced_to_a_safe_display_basename(
    filename,
    expected,
):
    assert uploads._safe_original_filename(filename) == expected


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("notes.txt", b"valid utf-8 text", None),
        ("notes.txt", b"\xff\x00", 415),
        ("requirements.json", b'{"ok": true}', None),
        ("requirements.json", b"{broken", 415),
        ("report.pdf", b"%PDF-1.7\n", None),
        ("report.pdf", b"not a pdf", 415),
    ],
)
def test_upload_validates_text_json_and_pdf_signatures(
    tmp_path,
    filename,
    content,
    expected_status,
):
    path = tmp_path / filename
    path.write_bytes(content)

    if expected_status is None:
        uploads._validate_file_content(path, filename)
    else:
        with pytest.raises(HTTPException) as error:
            uploads._validate_file_content(path, filename)
        assert error.value.status_code == expected_status


@pytest.mark.parametrize(
    ("filename", "member"),
    [
        ("report.docx", "word/document.xml"),
        ("report.xlsx", "xl/workbook.xml"),
    ],
)
def test_upload_accepts_office_container_with_required_document_member(
    tmp_path,
    filename,
    member,
):
    path = tmp_path / filename
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, "<document/>")

    uploads._validate_file_content(path, filename)


def test_upload_rejects_office_zip_without_expected_content(tmp_path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("not-a-document.xml", "<document/>")

    with pytest.raises(HTTPException) as error:
        uploads._validate_file_content(path, "report.docx")
    assert error.value.status_code == 415


def test_upload_rejects_office_archive_with_too_many_members(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(uploads, "MAX_OFFICE_ARCHIVE_MEMBERS", 1)
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("word/extra.xml", "<extra/>")

    with pytest.raises(HTTPException) as error:
        uploads._validate_file_content(path, "report.docx")
    assert error.value.status_code == 415


def test_document_storage_path_is_confined_to_its_project(tmp_path, monkeypatch):
    from app.core import file_storage

    upload_root = tmp_path / "uploads"
    project_dir = upload_root / "17"
    project_dir.mkdir(parents=True)
    monkeypatch.setattr(file_storage, "UPLOAD_ROOT", upload_root)

    document = project_dir / "document.pdf"
    document.write_bytes(b"%PDF-1.7")
    assert file_storage.resolve_document_storage_path(str(document), 17) == document

    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.7")
    with pytest.raises(HTTPException) as error:
        file_storage.resolve_document_storage_path(str(outside), 17)
    assert error.value.status_code == 400


def test_upload_stream_rejects_oversized_content_and_removes_partial_file(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(uploads.settings, "MAX_UPLOAD_SIZE_BYTES", 3)
    path = tmp_path / "upload.tmp"

    with pytest.raises(HTTPException) as error:
        uploads._write_upload_stream(io.BytesIO(b"four"), path)

    assert error.value.status_code == 413
    assert not path.exists()


def test_upload_stream_rejects_empty_content(monkeypatch, tmp_path):
    path = tmp_path / "empty.tmp"
    with pytest.raises(HTTPException) as error:
        uploads._write_upload_stream(io.BytesIO(b""), path)

    assert error.value.status_code == 400
    assert not path.exists()


def test_structured_log_formatter_redacts_credentials_and_includes_request_id():
    token = request_id_context.set("request-123")
    try:
        record = logging.LogRecord(
            "test",
            logging.WARNING,
            __file__,
            1,
            "authorization=Bearer private-token password=secret",
            (),
            None,
        )
        formatted = JsonLogFormatter().format(record)
    finally:
        request_id_context.reset(token)

    payload = json.loads(formatted)
    assert payload["request_id"] == "request-123"
    assert "private-token" not in formatted
    assert "password=secret" not in formatted
    assert "[REDACTED]" in payload["message"]


def test_structured_application_diagnostics_are_written_to_stdout(capsys):
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    try:
        root.handlers = []
        configure_structured_logging()
        logging.getLogger("app.api.analytics").warning(
            "Quality summary API result: project_id=2 status=unavailable "
            "failure_category=structured_output_invalid"
        )
        output = capsys.readouterr().out
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)

    assert '"level": "WARNING"' in output
    assert '"logger": "app.api.analytics"' in output
    assert "failure_category=structured_output_invalid" in output


def test_request_context_middleware_sets_response_header_and_resets_context():
    messages = []

    async def app(scope, receive, send):
        assert request_id_context.get() != "-"
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": [],
        "query_string": b"",
        "client": ("192.0.2.1", 1),
    }

    asyncio.run(RequestContextMiddleware(app)(scope, receive, send))
    response_headers = dict(messages[0]["headers"])

    assert messages[0]["status"] == 204
    assert len(response_headers[b"x-request-id"]) == 32
    assert request_id_context.get() == "-"


def test_database_dependency_rolls_back_on_request_failure_and_closes_session(
    monkeypatch,
):
    from app.database import connection

    session = SimpleNamespace(rollback=lambda: calls.append("rollback"))
    calls = []
    session.close = lambda: calls.append("close")
    monkeypatch.setattr(connection, "SessionLocal", lambda: session)
    dependency = connection.get_db()

    assert next(dependency) is session
    with pytest.raises(RuntimeError, match="offline failure"):
        dependency.throw(RuntimeError("offline failure"))

    assert calls == ["rollback", "close"]


@pytest.mark.parametrize("timeout", [0, 301])
def test_llm_timeout_setting_rejects_out_of_range_values(timeout):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
            GEMINI_API_KEY="offline-test-placeholder",
            JWT_SECRET_KEY="offline-test-signing-key-only-not-for-use",
            LLM_TIMEOUT_SECONDS=timeout,
        )


def test_llm_timeout_setting_accepts_a_bounded_value():
    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite://",
        GEMINI_API_KEY="offline-test-placeholder",
        JWT_SECRET_KEY="offline-test-signing-key-only-not-for-use",
        LLM_TIMEOUT_SECONDS=300,
    )

    assert configured.LLM_TIMEOUT_SECONDS == 300
