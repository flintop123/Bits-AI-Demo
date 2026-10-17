"""Extract page-aware, searchable chunks from agriculture PDF documents."""

import hashlib
import re
from pathlib import Path

from pypdf import PdfReader


class AgriculturePDFExtractor:
    def __init__(self, chunk_size=1400, chunk_overlap=180):
        if chunk_size < 200:
            raise ValueError("chunk_size must be at least 200 characters")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError(
                "chunk_overlap must be non-negative and smaller than chunk_size"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load(
        self,
        pdf_path,
        *,
        source_url,
        document_title,
        start_page=1,
        end_page=None,
    ):
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        end_page = page_count if end_page is None else end_page
        self._validate_page_range(start_page, end_page, page_count)

        records = []
        for page_number in range(start_page, end_page + 1):
            raw_text = reader.pages[page_number - 1].extract_text() or ""
            page_text = self.normalize_text(raw_text)
            if not page_text:
                continue

            for chunk_index, content in enumerate(self.chunk_text(page_text)):
                identity = (
                    f"{source_url}|{page_number}|{chunk_index}|{content}"
                )
                records.append({
                    "document_title": document_title,
                    "page_number": page_number,
                    "chunk_index": chunk_index,
                    "content": content,
                    "character_count": len(content),
                    "source_url": source_url,
                    "source_file": path.name,
                    "content_hash": hashlib.sha256(
                        identity.encode("utf-8")
                    ).hexdigest(),
                })
        return records

    @staticmethod
    def _validate_page_range(start_page, end_page, page_count):
        if start_page < 1:
            raise ValueError("start_page must be at least 1")
        if end_page < start_page:
            raise ValueError("end_page must not be before start_page")
        if end_page > page_count:
            raise ValueError(
                f"Requested page {end_page}, but PDF has {page_count} pages"
            )

    @staticmethod
    def normalize_text(value):
        lines = []
        for line in str(value or "").replace("\u00a0", " ").splitlines():
            normalized = re.sub(r"\s+", " ", line).strip()
            if normalized:
                lines.append(normalized)
        return "\n".join(lines)

    def chunk_text(self, text):
        text = str(text or "").strip()
        if not text:
            return []

        chunks = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                boundary = max(
                    text.rfind("\n", start, end),
                    text.rfind(" ", start, end),
                )
                if boundary > start + (self.chunk_size // 2):
                    end = boundary

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + 1)

        return chunks
