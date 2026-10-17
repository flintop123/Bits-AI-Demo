"""Extract and normalize DA&FW crop statistics from the supplied workbook."""

from pathlib import Path

import pandas as pd


class CropStatisticsExcelExtractor:
    HEADER_ROW = 6
    MEASURE_ROW = 5
    DATA_START_ROW = 7
    VALID_SEASONS = {"Kharif", "Rabi", "Summer", "Total"}
    REQUIRED_MEASURES = {
        "Area": "area_hectares",
        "Production": "production",
        "Yield": "yield_kg_per_hectare",
    }

    def load(self, workbook_path, sheet_name="Data Sheet"):
        path = Path(workbook_path)
        if not path.is_file():
            raise FileNotFoundError(f"Excel data file not found: {path}")

        frame = pd.read_excel(path, sheet_name=sheet_name, header=None)
        return self.normalize(frame, source_file=path.name)

    def normalize(self, frame, source_file="unknown.xlsx"):
        if len(frame.index) <= self.DATA_START_ROW:
            raise ValueError("Workbook does not contain crop data rows")

        blocks = self._measure_blocks(frame)
        common_years = self._common_years(blocks)
        records = []
        current_crop = None

        for row_index in range(self.DATA_START_ROW, len(frame.index)):
            crop_value = frame.iat[row_index, 0]
            if not self._is_blank(crop_value):
                current_crop = str(crop_value).strip()

            season_value = frame.iat[row_index, 1]
            if self._is_blank(season_value):
                continue

            season = str(season_value).strip()
            if season not in self.VALID_SEASONS or not current_crop:
                continue

            for year in common_years:
                values = {
                    field: self._number(frame.iat[row_index, columns[year]])
                    for field, columns in blocks.items()
                }
                if all(value is None for value in values.values()):
                    continue

                records.append({
                    "crop": current_crop,
                    "season": season,
                    "year": year,
                    **values,
                    "area_unit": "hectare",
                    "production_unit": self._production_unit(current_crop),
                    "yield_unit": "kg_per_hectare",
                    "is_advance_estimate": year == "2024-25",
                    "source": "Department of Agriculture & Farmers Welfare",
                    "source_file": source_file,
                    "source_row": row_index + 1,
                })

        if not records:
            raise ValueError("No crop statistics were extracted from the workbook")
        return records

    def _measure_blocks(self, frame):
        markers = {}
        for column_index, value in enumerate(frame.iloc[self.MEASURE_ROW]):
            if self._is_blank(value):
                continue
            marker = str(value).strip()
            if marker in self.REQUIRED_MEASURES:
                markers[marker] = column_index

        missing = set(self.REQUIRED_MEASURES) - markers.keys()
        if missing:
            raise ValueError(
                "Workbook is missing measure blocks: "
                + ", ".join(sorted(missing))
            )

        ordered_starts = sorted(markers.values())
        blocks = {}
        for marker, start in markers.items():
            later_starts = [value for value in ordered_starts if value > start]
            end = min(later_starts) if later_starts else len(frame.columns)
            year_columns = {}
            for column_index in range(start, end):
                year_value = frame.iat[self.HEADER_ROW, column_index]
                if self._is_blank(year_value):
                    continue
                year_columns[str(year_value).strip()] = column_index
            blocks[self.REQUIRED_MEASURES[marker]] = year_columns
        return blocks

    @staticmethod
    def _common_years(blocks):
        year_sets = [set(columns) for columns in blocks.values()]
        common = set.intersection(*year_sets)
        if not common:
            raise ValueError("Measure blocks do not share any year columns")
        return sorted(common, key=lambda year: int(year.split("-")[0]))

    @staticmethod
    def _number(value):
        if CropStatisticsExcelExtractor._is_blank(value):
            return None
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        number = float(value)
        return int(number) if number.is_integer() else number

    @staticmethod
    def _is_blank(value):
        return value is None or pd.isna(value) or str(value).strip() == ""

    @staticmethod
    def _production_unit(crop):
        if crop == "Cotton":
            return "bale_170_kg"
        if crop in {"Jute", "Mesta", "Jute & Mesta", "Sannhemp"}:
            return "bale_180_kg"
        return "tonne"
