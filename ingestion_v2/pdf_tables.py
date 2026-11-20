"""Extract numeric cells from a reviewed, hash-pinned PDF table. No DB access."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
import hashlib
from pathlib import Path
import re

from ingestion_v2.extraction import inspect_input_file
from ingestion_v2.models import InspectFileInput, SourceModality
from ingestion_v2.pdf_table_models import (
    ExtractPdfTableInput, ExtractPdfTableOutput, PdfTableProfile,
    PdfTableValue, TableEvidence,
)


_NUMBER = re.compile(
    r"[+\-−]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|"
    r"[0-9]{1,2}(?:,[0-9]{2})+,[0-9]{3})(?:\.[0-9]+)?"
)


class PdfTableValidationError(ValueError):
    """The requested table evidence could not be established."""


@dataclass(frozen=True)
class _Cell:
    text: str
    box: tuple[float, float, float, float]


def _text(value):
    return " ".join((value or "").split())


def _literal_pattern(value):
    return re.compile(r"(?<!\w)" + re.escape(_text(value)) + r"(?!\w)", re.IGNORECASE)


def _evidence(page, cells):
    return TableEvidence(
        page=page, text=" ".join(cell.text for cell in cells),
        boxes=[cell.box for cell in cells],
    )


def _context(document, name, anchor):
    import pymupdf as fitz

    page = document[anchor.page - 1]
    pattern = _literal_pattern(anchor.text)
    matches = []
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            text = _text("".join(span["text"] for span in line["spans"]))
            matches.extend(_Cell(text, tuple(line["bbox"])) for _ in pattern.finditer(text))
    if len(matches) != 1:
        raise PdfTableValidationError(
            f"Context {name!r}: expected one matching source line on page "
            f"{anchor.page}, found {len(matches)}"
        )
    return _evidence(anchor.page, matches)


def _ruled_or_text(page, profile):
    if not hasattr(page, "find_tables"):
        raise PdfTableValidationError("This layout requires PyMuPDF with Page.find_tables")
    tables = page.find_tables(clip=profile.clip, strategy=profile.strategy).tables
    for table in tables:
        rows = []
        for raw, row in zip(table.extract(), table.rows, strict=True):
            cells = []
            for raw_text, box in zip(raw, row.cells, strict=True):
                text = _text(raw_text)
                cells.append(_Cell(text, tuple(box)) if text and box is not None else None)
            if any(cells):
                rows.append(cells)
        yield tuple(table.bbox), rows


def _positioned(page, profile):
    # Reviewed column boundaries are tied to the exact PDF fingerprint.
    # Never assign a word that straddles two columns.
    edges = profile.x_edges
    words = page.get_text("words", clip=profile.clip)
    bands = []
    for word in sorted(words, key=lambda item: ((item[1] + item[3]) / 2, item[0])):
        y = (word[1] + word[3]) / 2
        if not bands or y - bands[-1][0] > 2.5:
            bands.append((y, []))
        bands[-1][1].append(word)

    rows = []
    for _, words in bands:
        buckets = [[] for _ in range(len(edges) - 1)]
        for word in words:
            for index, (left, right) in enumerate(zip(edges, edges[1:])):
                if left <= word[0] and word[2] <= right:
                    buckets[index].append(word)
                    break
            else:
                raise PdfTableValidationError(f"Text crosses a reviewed column boundary: {word[4]!r}")
        cells = []
        for bucket in buckets:
            if not bucket:
                cells.append(None)
                continue
            text = " ".join(word[4] for word in sorted(bucket, key=lambda item: item[0]))
            box = (
                min(word[0] for word in bucket), min(word[1] for word in bucket),
                max(word[2] for word in bucket), max(word[3] for word in bucket),
            )
            cells.append(_Cell(text, box))
        rows.append(cells)
    yield tuple(profile.clip), rows


def _header_index(rows, profile):
    selectors = [profile.row_label_header, *(column.header for column in profile.columns)]
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        return None
    columns = [tuple(cell for cell in col if cell) for col in zip(*rows[:profile.header_rows])]
    actual = [" ".join(cell.text for cell in col).casefold() for col in columns]
    if any(actual.count(_text(header).casefold()) != 1 for header in selectors):
        return None
    indexes = [actual.index(_text(header).casefold()) for header in selectors]
    return indexes, columns


def _read_cell(page, cell):
    if _text(page.get_textbox(cell.box)) != cell.text:
        raise PdfTableValidationError(f"Table text cannot be read back from its source box: {cell.text!r}")


def _x_overlap(left, right):
    return min(left[2], right[2]) - max(left[0], right[0]) > 0.25


def _y_overlap(left, right):
    return min(left[3], right[3]) - max(left[1], right[1]) > 0.25


def _extract_values(page, rows, indexes, headers, context, profile):
    page_number = profile.page
    row_index, *value_indexes = indexes
    for index in indexes:
        for cell in headers[index]:
            _read_cell(page, cell)
    data = rows[profile.header_rows:]
    output = []
    for requested in profile.rows:
        matching = [
            row for row in data
            if row[row_index] and row[row_index].text.casefold() == _text(requested).casefold()
        ]
        if len(matching) != 1:
            raise PdfTableValidationError(
                f"Row {requested!r}: expected one matching row, found {len(matching)}"
            )
        row = matching[0]
        label = row[row_index]
        _read_cell(page, label)
        for index, column in zip(value_indexes, profile.columns, strict=True):
            cell = row[index]
            header_cells = headers[index]
            if cell is None or not _NUMBER.fullmatch(cell.text):
                raise PdfTableValidationError(f"{requested!r} / {column.key}: missing or invalid number")
            _read_cell(page, cell)
            wrong_column = profile.strategy != "positioned" and (
                not any(_x_overlap(part.box, cell.box) for part in header_cells)
                or any(
                    _x_overlap(part.box, cell.box)
                    for other in indexes if other != index for part in headers[other]
                )
            )
            if (
                not _y_overlap(label.box, cell.box)
                or _x_overlap(label.box, cell.box)
                or wrong_column
            ):
                raise PdfTableValidationError(f"{requested!r} / {column.key}: ambiguous cell geometry")
            header = _evidence(page_number, header_cells)
            unit_source = header if column.unit_context is None else context[column.unit_context]
            if not _text(column.unit_text):
                raise PdfTableValidationError(f"{column.key}: blank unit selector")
            units = list(_literal_pattern(column.unit_text).finditer(unit_source.text))
            if len(units) != 1:
                raise PdfTableValidationError(f"{column.key}: expected one explicit unit in source")
            if column.unit_context is not None and (
                unit_source.page != page_number
                or unit_source.boxes[0][3] > headers[row_index][0].box[1] + 0.5
            ):
                raise PdfTableValidationError(f"{column.key}: unit legend must precede its table on the same page")
            output.append(PdfTableValue(
                row_label=_evidence(page_number, [label]),
                column_key=column.key, column_header=header,
                cell=_evidence(page_number, [cell]),
                value_decimal=format(Decimal(cell.text.replace(",", "").replace("−", "-")), "f"),
                unit_as_reported=units[0].group(), unit_evidence=unit_source,
            ))
    return output


def extract_pdf_table(payload: ExtractPdfTableInput) -> ExtractPdfTableOutput:
    profile = payload.profile
    source = inspect_input_file(InspectFileInput(file_path=payload.file_path))
    if source.modality != SourceModality.PDF:
        raise PdfTableValidationError("Only PDF input is accepted")
    expected = profile.expected_sha256.lower()
    if source.source_hash != expected:
        raise PdfTableValidationError(f"Source SHA-256 mismatch: got {source.source_hash}")
    data = Path(source.file_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise PdfTableValidationError("PDF changed after source inspection")

    import pymupdf as fitz

    with fitz.open(stream=data, filetype="pdf") as document:
        if not document.is_pdf or document.needs_pass:
            raise PdfTableValidationError("Expected an unencrypted PDF")
        if max(profile.page, *(anchor.page for anchor in profile.context.values())) > len(document):
            raise PdfTableValidationError("Profile references a page outside this PDF")
        page = document[profile.page - 1]
        if page.rotation:
            raise PdfTableValidationError("Rotated pages require a separately supported layout")
        if profile.clip and not page.rect.contains(fitz.Rect(profile.clip)):
            raise PdfTableValidationError("Table clip is outside the page")
        context = {key: _context(document, key, anchor) for key, anchor in profile.context.items()}
        report = context["report"]
        if report.page != profile.page:
            raise PdfTableValidationError("Report heading must be on the table page")
        candidates = []
        layouts = _positioned if profile.strategy == "positioned" else _ruled_or_text
        for bounds, rows in layouts(page, profile):
            if len(rows) <= profile.header_rows or report.boxes[0][3] > bounds[1] + 0.5:
                continue
            match = _header_index(rows, profile)
            if match is not None:
                candidates.append((bounds, rows, *match))
        if len(candidates) != 1:
            raise PdfTableValidationError(
                f"Expected one table with the reviewed headers, found {len(candidates)}"
            )
        bounds, rows, indexes, headers = candidates[0]
        values = _extract_values(page, rows, indexes, headers, context, profile)
        return ExtractPdfTableOutput(
            source=source, expected_sha256=expected, table_page=profile.page,
            table_bbox=bounds, strategy=profile.strategy, context=context, values=values,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="New evidence JSON file; omit for stdout")
    args = parser.parse_args(argv)
    try:
        profile = PdfTableProfile.model_validate_json(args.profile.read_text(encoding="utf-8-sig"))
        output = extract_pdf_table(ExtractPdfTableInput(file_path=args.input, profile=profile))
        body = output.model_dump_json(indent=2) + "\n"
        if args.output is None:
            print(body, end="")
        else:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(body)
            print(f"Verified {len(output.values)} PDF cells. Evidence: {args.output}")
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        parser.exit(1, f"PDF table validation failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
