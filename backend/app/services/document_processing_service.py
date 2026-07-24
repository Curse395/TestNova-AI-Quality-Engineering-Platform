from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk


class DocumentProcessingService:
    """Parse documents and persist their chunks as the ingestion record."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def process_document(self, document: Document) -> dict[str, int | str]:
        """Replace a document's chunks with chunks generated from its current file.

        Parsing happens before any database mutation so a parsing failure leaves the
        previously ingested chunks intact.  Database changes are committed together;
        an error while replacing chunks rolls the session back.
        """
        raw_text = self.parse_document(document.storage_path)

        print("=" * 50)
        print("DOCUMENT:", document.filename)
        print("PATH",document.storage_path)
        print("TEXT LENGTH:", len(raw_text))
        print(raw_text[:200])
        print("="*50)

        chunks = self.chunk_text(raw_text)
        print("TOTAL CHUNKS:", len(chunks))

        try:
            existing_chunks = (
                self.db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == document.id)
                .all()
            )
            for chunk in existing_chunks:
                self.db.delete(chunk)

            for index, content in enumerate(chunks):
                print(f"Saving chunk {index}")
                self.db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=content,
                    )
                )
            print("COMMITTING...")

            self.db.commit()
            print("COMMIT SUCCESS")

        except Exception as e:
            print("DATABASE ERROR:", e)
            self.db.rollback()
            raise

        return {
            "document_id": document.id,
            "chunks_created": len(chunks),
            "status": "completed",
        }

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

    def chunk_text(self, text: str, chunk_size: int = 120, overlap: int = 30) -> list[str]:
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
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError(
                "PDF parsing requires PyMuPDF (fitz) to be installed."
            ) from exc

        try:
            with fitz.open(path) as document:
                text = "\n".join(page.get_text("text") for page in document)
            return text.encode("utf-8", errors="replace").decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"Failed to extract text from PDF '{path.name}'.") from exc

    def _parse_docx(self, path: Path) -> str:
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError(
                "DOCX parsing requires python-docx to be installed."
            ) from exc

        try:
            document = Document(path)
            return "\n".join(
                paragraph.text.strip()
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to extract text from DOCX '{path.name}'.") from exc
