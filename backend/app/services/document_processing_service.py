from __future__ import annotations
import csv
import json
import re
from openpyxl import load_workbook
from pathlib import Path
from typing import Any
from app.core.config import settings
from sqlalchemy.orm import Session
from app.models.document import Document
from app.models.document_chunk import DocumentChunk


class DocumentProcessingService:
    """Parse documents and persist their chunks as the ingestion record."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _parse_xlsx(self,path:Path)->str:
        workbook = None
        try:
            workbook=load_workbook(filename=path,read_only=True,data_only=True)
            extracted_text=[]

            for sheet in workbook.worksheets:
                extracted_text.append(f"Sheet: {sheet.title}")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value) for value in row if value is not None]
                    if values:
                        extracted_text.append(" | ".join(values))

            return"\n".join(extracted_text)

        except Exception as exc:
            raise RuntimeError(f"Failed to extract text from XLSX '{path.name}'.")from exc
        finally:
            if workbook is not None:
                workbook.close()

    def process_document(self, document: Document) -> dict[str, int | str]:
        """Replace a document's chunks with chunks generated from its current file.

        Parsing happens before any database mutation so a parsing failure leaves the
        previously ingested chunks intact.  Database changes are committed together;
        an error while replacing chunks rolls the session back.
        """
        raw_text = self.parse_document(document.storage_path)

        if not raw_text.strip():
            raise ValueError("The document contains no extractable text.")

        chunks = self.chunk_text(raw_text)
        if not chunks:
            raise ValueError("The document contains no extractable text.")

        try:
            existing_chunks = (
                self.db.query(DocumentChunk)
                .filter(DocumentChunk.document_id == document.id)
                .all()
            )
            for chunk in existing_chunks:
                self.db.delete(chunk)

            current_page: int | None = None
            current_sheet: str | None = None
            current_section: str | None = None
            for index, content in enumerate(chunks):
                page_numbers = [
                    int(match)
                    for match in re.findall(r"^Page (\d+):", content, re.MULTILINE)
                ]
                sheet_names = re.findall(r"^Sheet: (.+)$", content, re.MULTILINE)
                headings = re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
                if page_numbers:
                    current_page = page_numbers[-1]
                if sheet_names:
                    current_sheet = sheet_names[-1]
                if headings:
                    current_section = headings[-1]

                self.db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=content,
                        source_metadata={
                            "filename": document.filename,
                            "source_type": document.source_type,
                            "file_type": Path(document.filename).suffix.lower(),
                            "chunk_index": index,
                            "page_numbers": page_numbers or (
                                [current_page] if current_page is not None else []
                            ),
                            "sheet_name": current_sheet,
                            "section": current_section,
                        },
                    )
                )
            self.db.commit()

        except Exception:
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
        if suffix == ".xlsx":
            return self._parse_xlsx(path)

        raise ValueError(f"Unsupported document format: '{suffix or 'no extension'}'.")

    def normalize_text(self, text: str) -> str:
        text = text.replace("\x00", "")
        lines = [
            re.sub(r"[^\S\r\n]+", " ", line).strip()
            for line in text.splitlines()
        ]
        return "\n".join(lines).strip()

    def chunk_text(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        chunk_size = settings.CHUNK_SIZE_WORDS if chunk_size is None else chunk_size
        overlap = settings.CHUNK_OVERLAP_WORDS if overlap is None else overlap
        if chunk_size < 1:
            raise ValueError("Chunk size must be at least one word.")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("Chunk overlap must be non-negative and smaller than chunk size.")

        normalized = self.normalize_text(text)
        if not normalized:
            return []

        chunks: list[str] = []
        current_lines: list[str] = []
        current_words: list[str] = []

        def flush() -> list[str]:
            if not current_words:
                return []
            chunks.append("\n".join(current_lines))
            return current_words[-overlap:] if overlap else []

        for line in normalized.splitlines():
            words = line.split()
            if not words:
                continue

            if len(words) > chunk_size:
                carry = flush()
                current_lines.clear()
                current_words.clear()
                step = chunk_size - overlap
                for start in range(0, len(words), step):
                    window = words[start : start + chunk_size]
                    chunks.append(" ".join(window))
                    if start + chunk_size >= len(words):
                        break
                continue

            if current_words and len(current_words) + len(words) > chunk_size:
                carry = flush()
                current_lines.clear()
                current_words.clear()
                available_overlap = chunk_size - len(words)
                carry = carry[-available_overlap:] if available_overlap else []
                if carry:
                    current_lines.append(" ".join(carry))
                    current_words.extend(carry)

            current_lines.append(line)
            current_words.extend(words)

        flush()
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
                text = "\n".join(
                    f"Page {index + 1}:\n{page.get_text('text')}"
                    for index, page in enumerate(document)
                )
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
            extracted_text = []
            for item in document.iter_inner_content():
                if hasattr(item, "style") and hasattr(item, "text"):
                    text = item.text.strip()
                    if not text:
                        continue
                    if item.style.name.startswith("Heading"):
                        extracted_text.append(f"## {text}")
                    else:
                        extracted_text.append(text)
                elif hasattr(item, "rows"):
                    for row in item.rows:
                        values = [cell.text.strip() for cell in row.cells]
                        if any(values):
                            extracted_text.append(" | ".join(values))
            return "\n".join(extracted_text)
        except Exception as exc:
            raise RuntimeError(f"Failed to extract text from DOCX '{path.name}'.") from exc
