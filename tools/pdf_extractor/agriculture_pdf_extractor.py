"""Extract multilingual, page-aware chunks from agriculture PDFs.

Text-layer extraction is attempted first. Sparse or unusable pages can fall
back to local Tesseract OCR with Hindi and English language data.
"""

import hashlib
import io
import os
import re
import shutil
import unicodedata
from collections import Counter
from pathlib import Path

from pypdf import PdfReader


class OCRUnavailableError(RuntimeError):
    """Raised when OCR is explicitly required but is not available."""


class AgriculturePDFExtractor:
    def __init__(
        self,
        chunk_size=1400,
        chunk_overlap=180,
        *,
        ocr_enabled=True,
        ocr_language="hin+eng",
        ocr_dpi=200,
        min_direct_text_chars=80,
    ):
        if chunk_size < 200:
            raise ValueError("chunk_size must be at least 200 characters")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError(
                "chunk_overlap must be non-negative and smaller than chunk_size"
            )
        if ocr_dpi < 100:
            raise ValueError("ocr_dpi must be at least 100")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.ocr_enabled = ocr_enabled
        self.ocr_language = ocr_language
        self.ocr_dpi = ocr_dpi
        self.min_direct_text_chars = min_direct_text_chars
        self.last_report = {}

    def load(
        self,
        pdf_path,
        *,
        source_url,
        document_title,
        start_page=1,
        end_page=None,
        declared_language=None,
        force_ocr=False,
    ):
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")

        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        end_page = page_count if end_page is None else end_page
        self._validate_page_range(start_page, end_page, page_count)

        report = {
            "pages_requested": end_page - start_page + 1,
            "pages_extracted": 0,
            "direct_pages": 0,
            "ocr_pages": 0,
            "skipped_pages": 0,
            "language_counts": Counter(),
        }
        records = []
        for page_number in range(start_page, end_page + 1):
            raw_text = reader.pages[page_number - 1].extract_text() or ""
            page_text = self.normalize_text(raw_text)
            extraction_method = "pypdf"

            should_ocr = force_ocr or self._needs_ocr(page_text)
            if self.ocr_enabled and should_ocr:
                try:
                    ocr_text = self.normalize_text(
                        self._ocr_page(path, page_number)
                    )
                except OCRUnavailableError:
                    if force_ocr:
                        raise
                    ocr_text = ""
                except Exception:
                    if force_ocr:
                        raise
                    ocr_text = ""
                if ocr_text and (
                    force_ocr or len(ocr_text) > len(page_text)
                ):
                    page_text = ocr_text
                    extraction_method = "tesseract_ocr"

            if not page_text:
                report["skipped_pages"] += 1
                continue

            language = self.detect_language(
                page_text,
                fallback=declared_language,
            )
            report["pages_extracted"] += 1
            report["language_counts"][language] += 1
            if extraction_method == "tesseract_ocr":
                report["ocr_pages"] += 1
            else:
                report["direct_pages"] += 1

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
                    "language": language,
                    "extraction_method": extraction_method,
                    "source_type": "pdf",
                    "source_url": source_url,
                    "source_file": path.name,
                    "content_hash": hashlib.sha256(
                        identity.encode("utf-8")
                    ).hexdigest(),
                })

        report["language_counts"] = dict(report["language_counts"])
        self.last_report = report
        return records

    def _ocr_page(self, pdf_path, page_number):
        try:
            import pymupdf
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise OCRUnavailableError(
                "OCR requires PyMuPDF, pytesseract, and Pillow"
            ) from exc

        tesseract_cmd = self._find_tesseract()
        if not tesseract_cmd:
            raise OCRUnavailableError(
                "Tesseract OCR was not found. Install Tesseract or set "
                "TESSERACT_CMD."
            )
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        tessdata = self._find_tessdata()
        if tessdata:
            # Let Tesseract read its language directory from the environment.
            # Passing a quoted --tessdata-dir through pytesseract causes the
            # quote characters to become part of the path on Windows.
            os.environ["TESSDATA_PREFIX"] = tessdata

        with pymupdf.open(str(pdf_path)) as document:
            page = document.load_page(page_number - 1)
            scale = self.ocr_dpi / 72
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                alpha=False,
            )
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            return pytesseract.image_to_string(
                image,
                lang=self.ocr_language,
            )

    @staticmethod
    def _find_tesseract():
        configured = os.getenv("TESSERACT_CMD")
        candidates = [
            configured,
            shutil.which("tesseract"),
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(candidate)
        return None

    @staticmethod
    def _find_tessdata():
        configured = os.getenv("TESSDATA_PREFIX")
        project_data = (
            Path(__file__).resolve().parents[2] / "data" / "tessdata"
        )
        for candidate in (configured, project_data):
            if candidate and Path(candidate).is_dir():
                return str(Path(candidate).resolve())
        return None

    def _needs_ocr(self, text):
        text = str(text or "").strip()
        if not text:
            return True
        replacements = text.count("\ufffd")
        controls = sum(
            1 for character in text
            if unicodedata.category(character) == "Cc"
            and character not in "\n\t\r"
        )
        return (replacements + controls) / max(len(text), 1) > 0.02

    @staticmethod
    def detect_language(text, fallback=None):
        devanagari = len(re.findall(r"[\u0900-\u097F]", str(text or "")))
        latin = len(re.findall(r"[A-Za-z]", str(text or "")))
        if devanagari and latin:
            if min(devanagari, latin) / max(devanagari, latin) >= 0.08:
                return "mixed"
            return "hi" if devanagari > latin else "en"
        if devanagari:
            return "hi"
        if latin:
            return "en"
        return fallback or "und"

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
        value = unicodedata.normalize("NFC", str(value or ""))
        lines = []
        for line in value.replace("\u00a0", " ").splitlines():
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
