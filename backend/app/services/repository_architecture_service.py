import re
from pathlib import Path


_APPROVED_SOURCES = (
    "docs/architecture.md",
    "docs/phase5-completion.md",
    "docs/phase9-security-reliability.md",
    "backend/app/agents/test_generation_agent.py",
    "backend/app/agents/knowledge_agent.py",
    "backend/app/agents/requirements_agent.py",
    "backend/app/agents/review_agent.py",
    "backend/app/agents/change_risk_agent.py",
    "backend/app/agents/test_analysis_agent.py",
    "backend/app/agents/quality_insight_agent.py",
    "backend/app/agents/bug_analysis_agent.py",
    "backend/app/agents/orchestrator.py",
    "backend/app/services/test_case_generation_service.py",
    "backend/app/services/workflow_service.py",
    "backend/app/services/retrieval_service.py",
    "backend/app/services/llm_services.py",
    "backend/app/llm/router.py",
    "backend/app/llm/providers/gemini.py",
    "backend/app/api/test_cases.py",
    "backend/app/api/chat.py",
    "backend/app/models/test_execution.py",
)
_STOP_WORDS = {
    "about",
    "does",
    "explain",
    "from",
    "give",
    "how",
    "into",
    "which",
    "what",
    "when",
    "where",
    "work",
    "works",
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_ -]?key|access[_ -]?token|authorization|token|password|secret|credential)"
    r"\s*[:=]\s*)(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;]+)"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+\S+")
_PROVIDER_TOKEN = re.compile(r"\b(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{16,})\b")


class RepositoryArchitectureService:
    """Reads only approved TestNova source and documentation files."""

    def __init__(self, repository_root: Path | None = None) -> None:
        self.repository_root = (
            repository_root
            if repository_root is not None
            else Path(__file__).resolve().parents[3]
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    @staticmethod
    def _redact(value: str) -> str:
        value = _PROVIDER_TOKEN.sub(
            "[redacted]",
            _SECRET_ASSIGNMENT.sub(r"\1[redacted]", value),
        )
        return _BEARER_TOKEN.sub("Bearer [redacted]", value)

    def search(self, query: str, limit: int = 4) -> list[dict[str, object]]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("A non-empty architecture question is required.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
            raise ValueError("Architecture result limit must be between 1 and 10.")

        terms = {
            term.lower()
            for term in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", query)
            if term.lower() not in _STOP_WORDS
        }
        normalized_terms = {self._normalize(term) for term in terms}
        results: list[tuple[int, str, int, str]] = []
        found_source_count = 0

        for source_path in _APPROVED_SOURCES:
            path = self.repository_root / source_path
            if not path.is_file():
                continue
            found_source_count += 1
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            file_name = self._normalize(path.name)
            scores = []
            for index, line in enumerate(lines):
                normalized_line = self._normalize(line)
                score = sum(
                    2 if term in file_name else 1
                    for term in normalized_terms
                    if term and term in normalized_line
                )
                if score:
                    scores.append((score, index))
            if not scores:
                continue

            selected_indexes: set[int] = set()
            for _, index in sorted(scores, reverse=True)[:3]:
                selected_indexes.update(range(max(0, index - 2), min(len(lines), index + 4)))
            excerpt = "\n".join(
                f"{index + 1}: {lines[index]}"
                for index in sorted(selected_indexes)
            )
            excerpt = self._redact(excerpt)[:2400]
            document_name = source_path.replace("\\", "/")
            results.append((sum(score for score, _ in scores), document_name, len(results) + 1, excerpt))

        if found_source_count == 0:
            raise RuntimeError("No approved repository architecture sources are available.")

        results.sort(key=lambda result: (-result[0], result[1]))
        return [
            {
                "chunk_id": chunk_id,
                "document_id": None,
                "document_name": document_name,
                "source_type": "platform_architecture",
                "content": excerpt,
            }
            for _, document_name, chunk_id, excerpt in results[:limit]
        ]
