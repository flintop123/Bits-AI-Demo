import pandas as pd
from pymongo import MongoClient, UpdateOne
from typing import Any


def clean_value(value: Any):
    """
    Convert pandas NaN values to None and
    numpy values to normal Python values.
    """
    if pd.isna(value):
        return None

    if hasattr(value, "item"):
        return value.item()

    return value


def extract_excel_data(file_path: str):
    """
    Extract Area, Production and Yield data from
    the crop-wise Excel file.
    """

    raw_df = pd.read_excel(
        file_path,
        sheet_name="Data Sheet",
        header=None
    )

    # ---------------------------------------------------------
    # Find the row containing Area / Production / Yield
    # ---------------------------------------------------------

    metric_row = None

    for row_index in range(len(raw_df)):
        row_values = raw_df.iloc[row_index].tolist()

        if (
            "Area" in row_values
            and "Production" in row_values
            and "Yield" in row_values
        ):
            metric_row = row_index
            break

    if metric_row is None:
        raise ValueError(
            "Could not find Area/Production/Yield header row"
        )

    # ---------------------------------------------------------
    # Header containing years
    # ---------------------------------------------------------

    year_row = metric_row + 1

    headers = raw_df.iloc[year_row].tolist()

    # Find metric starting columns
    area_start = headers.index("1966-67")

    # Find Production and Yield starting columns
    production_start = None
    yield_start = None

    metric_headers = raw_df.iloc[metric_row].tolist()

    for index, value in enumerate(metric_headers):
        if value == "Production":
            production_start = index

        elif value == "Yield":
            yield_start = index

    if production_start is None or yield_start is None:
        raise ValueError(
            "Could not determine Production/Yield columns"
        )

    # Area starts after Crop + Season
    area_start = 2

    # Number of years
    production_years = [
        value
        for value in headers[production_start:]
        if isinstance(value, str) and "-" in value
    ]

    years = production_years

    print("Metric row:", metric_row)
    print("Year row:", year_row)
    print("Area start:", area_start)
    print("Production start:", production_start)
    print("Yield start:", yield_start)
    print("Number of years:", len(years))

    # ---------------------------------------------------------
    # Data starts after year row
    # ---------------------------------------------------------

    data_start = year_row + 1

    data_df = raw_df.iloc[data_start:].copy()

    # Crop names are merged cells in Excel.
    # Forward-fill them.
    data_df.iloc[:, 0] = data_df.iloc[:, 0].ffill()

    documents = []

    for _, row in data_df.iterrows():

        crop = clean_value(row.iloc[0])
        season = clean_value(row.iloc[1])

        # Ignore explanatory text / empty rows
        if not crop or not season:
            continue

        # Only valid seasons
        if season not in {
            "Kharif",
            "Rabi",
            "Summer",
            "Total"
        }:
            continue

        for offset, year in enumerate(years):

            area_index = area_start + offset
            production_index = production_start + offset
            yield_index = yield_start + offset

            area = clean_value(row.iloc[area_index])
            production = clean_value(row.iloc[production_index])
            crop_yield = clean_value(row.iloc[yield_index])

            # Skip completely empty records
            if (
                area is None
                and production is None
                and crop_yield is None
            ):
                continue

            document = {
                "crop": crop,
                "season": season,
                "year": year,
                "area": area,
                "production": production,
                "yield": crop_yield
            }

            documents.append(document)

    return documents