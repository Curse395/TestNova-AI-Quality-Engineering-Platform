from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


class DocumentProcessingService:
    def parse_document(self, file_path: str) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".txt":
            return self._parse_text(path)
        if suffix == ".csv":
            return self._parse_csv(path)
        if suffix == ".json":
            return self._parse_json(path)
        if suffix == ".pdf":
            return self._parse_pdf(path)
        if suffix == ".docx":
            return self._parse_docx(path)

        return self._parse_text(path)

    def normalize_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\n+", "\n", text)
        return text.strip()

    def chunk_text(self, text: str, chunk_size: int = 300, overlap: int = 50) -> list[str]:
        normalized = self.normalize_text(text)
        if not normalized:
            return []

        words = normalized.split()
        chunks: list[str] = []
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_words = words[start:end]
            if not chunk_words:
                break
            chunks.append(" ".join(chunk_words))
            if end == len(words):
                break
            start = max(0, end - overlap)
        return chunks

    def _parse_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="ignore")

    def _parse_csv(self, path: Path) -> str:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            rows = list(csv.reader(handle))
        return "\n".join(" | ".join(row) for row in rows)

    def _parse_json(self, path: Path) -> str:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            payload: Any = json.load(handle)
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def _parse_pdf(self, path: Path) -> str:
        return f"PDF content placeholder for {path.name}"

    def _parse_docx(self, path: Path) -> str:
        return f"DOCX content placeholder for {path.name}"
