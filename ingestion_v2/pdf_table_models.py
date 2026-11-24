"""Strict contracts for read-only PDF table evidence."""

from typing import Literal

from pydantic import Field, FiniteFloat, field_validator, model_validator

from ingestion_v2.models import InspectFileOutput, StrictModel


SHA256 = r"^[a-fA-F0-9]{64}$"


class ContextAnchor(StrictModel):
    page: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=250)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value):
        if not value.strip():
            raise ValueError("context anchor must not be blank")
        return value


class TableColumn(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    header: str = Field(min_length=1, max_length=150)
    unit_text: str = Field(min_length=1, max_length=60)
    unit_context: str | None = None


class PdfTableProfile(StrictModel):
    expected_sha256: str = Field(pattern=SHA256)
    page: int = Field(ge=1)
    strategy: Literal["lines", "lines_strict", "text", "positioned"] = "lines"
    clip: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat] | None = None
    x_edges: list[FiniteFloat] | None = Field(default=None, min_length=3, max_length=31)
    header_rows: int = Field(default=1, ge=1, le=4)
    row_label_header: str = Field(min_length=1, max_length=150)
    rows: list[str] = Field(min_length=1, max_length=500)
    columns: list[TableColumn] = Field(min_length=1, max_length=20)
    context: dict[str, ContextAnchor] = Field(min_length=1, max_length=12)

    @field_validator("row_label_header")
    @classmethod
    def nonblank_header(cls, value):
        if not value.strip():
            raise ValueError("row label header must not be blank")
        return value

    @model_validator(mode="after")
    def valid_selectors(self):
        def key(value):
            return " ".join(value.split()).casefold()

        groups = (
            self.rows,
            [self.row_label_header, *(column.header for column in self.columns)],
            [column.key for column in self.columns],
        )
        for group in groups:
            keys = [key(value) for value in group]
            if "" in keys or len(keys) != len(set(keys)):
                raise ValueError("row labels, headers, and column keys must be nonblank and unique")
        if "report" not in self.context:
            raise ValueError("context must include a source-backed 'report' anchor")
        for column in self.columns:
            if column.unit_context is not None and column.unit_context not in self.context:
                raise ValueError(f"unknown unit context: {column.unit_context}")
        if self.clip is not None:
            x0, y0, x1, y1 = self.clip
            if not (x0 < x1 and y0 < y1):
                raise ValueError("clip must have positive width and height")
        if self.strategy == "positioned":
            if self.clip is None or self.x_edges is None:
                raise ValueError("positioned layout requires clip and x_edges")
            if any(a >= b for a, b in zip(self.x_edges, self.x_edges[1:])):
                raise ValueError("x_edges must be strictly increasing")
            if (self.x_edges[0], self.x_edges[-1]) != (self.clip[0], self.clip[2]):
                raise ValueError("outer x_edges must match clip x limits")
        elif self.x_edges is not None:
            raise ValueError("x_edges apply only to the positioned layout")
        return self


class ExtractPdfTableInput(StrictModel):
    file_path: str
    profile: PdfTableProfile


class TableEvidence(StrictModel):
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    boxes: list[tuple[float, float, float, float]] = Field(min_length=1)


class PdfTableValue(StrictModel):
    row_label: TableEvidence
    column_key: str
    column_header: TableEvidence
    cell: TableEvidence
    value_decimal: str
    unit_as_reported: str
    unit_evidence: TableEvidence


class ExtractPdfTableOutput(StrictModel):
    source: InspectFileOutput
    expected_sha256: str = Field(pattern=SHA256)
    source_hash_match: Literal[True] = True
    coordinate_system: Literal["unrotated_pdf_points_top_left"] = "unrotated_pdf_points_top_left"
    table_page: int = Field(ge=1)
    table_bbox: tuple[float, float, float, float]
    strategy: Literal["lines", "lines_strict", "text", "positioned"]
    context: dict[str, TableEvidence]
    values: list[PdfTableValue]
