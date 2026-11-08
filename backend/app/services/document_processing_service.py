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
        raw_text, line_locations = self.parse_document_with_locations(
            document.storage_path
        )

        if not raw_text.strip():
            raise ValueError("The document contains no extractable text.")

        chunks, chunk_line_indices = self._chunk_text_with_line_indices(raw_text)
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
            suffix = Path(document.filename).suffix.lower()
            parser_names = {
                ".csv": "csv",
                ".docx": "python-docx",
                ".json": "json",
                ".pdf": "pymupdf",
                ".txt": "utf-8-text",
                ".xlsx": "openpyxl",
            }
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

                source_metadata: dict[str, Any] = {
                    "filename": document.filename,
                    "source_type": document.source_type or "document",
                    "file_type": suffix,
                    "chunk_index": index,
                    "extraction": {
                        "format": suffix.lstrip("."),
                        "parser": parser_names.get(suffix, "unknown"),
                    },
                }
                source_location: dict[str, Any] = {}
                if page_numbers or current_page is not None:
                    source_location["page_numbers"] = page_numbers or [current_page]
                if current_sheet is not None:
                    source_location["sheet_name"] = current_sheet
                if current_section is not None:
                    source_location["section"] = current_section
                source_location.update(
                    self._merge_line_locations(
                        chunk_line_indices[index],
                        line_locations,
                    )
                )
                if source_location:
                    source_metadata["source_location"] = source_location
                    source_metadata.update(source_location)

                self.db.add(
                    DocumentChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=content,
                        source_metadata=source_metadata,
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

    def parse_document_with_locations(
        self,
        file_path: str,
    ) -> tuple[str, list[dict[str, Any]]]:
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".txt":
            text = self._parse_text(path)
            return text, [
                {"line_start": line_number, "line_end": line_number}
                for line_number, _ in enumerate(text.splitlines(), start=1)
            ]
        if suffix == ".csv":
            return self._parse_csv_with_locations(path)
        if suffix == ".json":
            return self._parse_json_with_locations(path)

        return self.parse_document(file_path), []

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
        chunks, _ = self._chunk_text_with_line_indices(text, chunk_size, overlap)
        return chunks

    def _chunk_text_with_line_indices(
        self,
        text: str,
        chunk_size: int | None = None,
        overlap: int | None = None,
    ) -> tuple[list[str], list[list[int]]]:
        chunk_size = settings.CHUNK_SIZE_WORDS if chunk_size is None else chunk_size
        overlap = settings.CHUNK_OVERLAP_WORDS if overlap is None else overlap
        if chunk_size < 1:
            raise ValueError("Chunk size must be at least one word.")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("Chunk overlap must be non-negative and smaller than chunk size.")

        chunks: list[str] = []
        chunk_line_indices: list[list[int]] = []
        current_lines: list[str] = []
        current_words: list[str] = []
        current_word_line_indices: list[int] = []

        normalized_lines = [
            re.sub(r"[^\S\r\n]+", " ", line).strip()
            for line in text.replace("\x00", "").splitlines()
        ]
        if not normalized_lines:
            return [], []

        def flush() -> tuple[list[str], list[int]]:
            if not current_words:
                return [], []
            chunks.append("\n".join(current_lines))
            chunk_line_indices.append(list(dict.fromkeys(current_word_line_indices)))
            if not overlap:
                return [], []
            return (
                current_words[-overlap:],
                current_word_line_indices[-overlap:],
            )

        for line_index, line in enumerate(normalized_lines):
            words = line.split()
            if not words:
                continue

            if len(words) > chunk_size:
                flush()
                current_lines.clear()
                current_words.clear()
                current_word_line_indices.clear()
                step = chunk_size - overlap
                for start in range(0, len(words), step):
                    window = words[start : start + chunk_size]
                    chunks.append(" ".join(window))
                    chunk_line_indices.append([line_index])
                    if start + chunk_size >= len(words):
                        break
                continue

            if current_words and len(current_words) + len(words) > chunk_size:
                carry, carry_line_indices = flush()
                current_lines.clear()
                current_words.clear()
                current_word_line_indices.clear()
                available_overlap = chunk_size - len(words)
                carry = carry[-available_overlap:] if available_overlap else []
                carry_line_indices = (
                    carry_line_indices[-available_overlap:]
                    if available_overlap
                    else []
                )
                if carry:
                    current_lines.append(" ".join(carry))
                    current_words.extend(carry)
                    current_word_line_indices.extend(carry_line_indices)

            current_lines.append(line)
            current_words.extend(words)
            current_word_line_indices.extend([line_index] * len(words))

        flush()
        return chunks, chunk_line_indices

    @staticmethod
    def _merge_line_locations(
        line_indices: list[int],
        line_locations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        locations = [
            line_locations[index]
            for index in line_indices
            if index < len(line_locations)
        ]
        merged: dict[str, Any] = {}
        for start_key, end_key in (
            ("line_start", "line_end"),
            ("row_start", "row_end"),
        ):
            starts = [item[start_key] for item in locations if start_key in item]
            ends = [item[end_key] for item in locations if end_key in item]
            if starts and ends:
                merged[start_key] = min(starts)
                merged[end_key] = max(ends)

        json_paths = list(
            dict.fromkeys(
                item["json_path"]
                for item in locations
                if item.get("json_path")
            )
        )
        if json_paths:
            merged["json_paths"] = json_paths
        return merged

    def _parse_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="ignore")

    def _parse_csv(self, path: Path) -> str:
        text, _ = self._parse_csv_with_locations(path)
        return text

    def _parse_csv_with_locations(
        self,
        path: Path,
    ) -> tuple[str, list[dict[str, Any]]]:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.reader(handle)
            rows: list[str] = []
            locations: list[dict[str, Any]] = []
            previous_end_line = 0
            for row in reader:
                end_line = reader.line_num
                rendered_row = " | ".join(row)
                rows.append(rendered_row)
                row_location = {
                    "row_start": previous_end_line + 1,
                    "row_end": end_line,
                }
                locations.extend(
                    dict(row_location)
                    for _ in (rendered_row.splitlines() or [""])
                )
                previous_end_line = end_line
        return "\n".join(rows), locations

    def _parse_json(self, path: Path) -> str:
        text, _ = self._parse_json_with_locations(path)
        return text

    def _parse_json_with_locations(
        self,
        path: Path,
    ) -> tuple[str, list[dict[str, Any]]]:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            payload: Any = json.load(handle)
        rendered_lines = self._render_json_lines(payload, "$", 0)
        line_locations = [
            {"json_path": json_path}
            for line, json_path in rendered_lines
            for _ in (line.splitlines() or [""])
        ]
        return (
            "\n".join(line for line, _ in rendered_lines),
            line_locations,
        )

    @classmethod
    def _render_json_lines(
        cls,
        value: Any,
        json_path: str,
        level: int,
    ) -> list[tuple[str, str]]:
        indentation = "  " * level
        child_indentation = "  " * (level + 1)

        if isinstance(value, dict):
            if not value:
                return [(f"{indentation}{{}}", json_path)]
            lines = [(f"{indentation}{{", json_path)]
            items = list(value.items())
            for index, (key, child) in enumerate(items):
                child_path = f"{json_path}[{json.dumps(key, ensure_ascii=False)}]"
                child_lines = cls._render_json_lines(child, child_path, level + 1)
                key_prefix = (
                    f"{child_indentation}{json.dumps(key, ensure_ascii=False)}: "
                )
                first_line = child_lines[0][0][len(child_indentation):]
                lines.append((key_prefix + first_line, child_lines[0][1]))
                lines.extend(child_lines[1:])
                if index < len(items) - 1:
                    lines[-1] = (lines[-1][0] + ",", lines[-1][1])
            lines.append((f"{indentation}}}", json_path))
            return lines

        if isinstance(value, list):
            if not value:
                return [(f"{indentation}[]", json_path)]
            lines = [(f"{indentation}[", json_path)]
            for index, child in enumerate(value):
                child_lines = cls._render_json_lines(
                    child,
                    f"{json_path}[{index}]",
                    level + 1,
                )
                first_line = child_lines[0][0][len(child_indentation):]
                lines.append((child_indentation + first_line, child_lines[0][1]))
                lines.extend(child_lines[1:])
                if index < len(value) - 1:
                    lines[-1] = (lines[-1][0] + ",", lines[-1][1])
            lines.append((f"{indentation}]", json_path))
            return lines

        return [
            (
                indentation + json.dumps(value, ensure_ascii=False),
                json_path,
            )
        ]

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
