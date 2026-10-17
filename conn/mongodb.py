import json
import re
from datetime import datetime

from pymongo import MongoClient, UpdateOne

from tools.api_extractor.document import Documents


class BiharCropMongo:
    IDENTITY_FIELDS = (
        "district",
        "market",
        "date",
        "crop",
        "variety",
        "source_url",
    )

    def __init__(self):
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["bihar_agriculture"]
        self.collection = self.db["mandi_prices"]
        self.collection.create_index(
            [(field, 1) for field in self.IDENTITY_FIELDS],
            unique=True,
            name="unique_mandi_record",
        )

    def insert_records(self, records):
        if not records:
            return 0

        operations = [
            UpdateOne(
                {field: record[field] for field in self.IDENTITY_FIELDS},
                {"$set": record},
                upsert=True,
            )
            for record in records
        ]

        result = self.collection.bulk_write(operations)
        return result.upserted_count

    def find_records(self, limit=3):
        return list(self.collection.find().limit(limit))

    def extract_price(self, value):
        match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value))
        return float(match.group(0).replace(",", "")) if match else None

    def write_mandi_records(
        self,
        documents: list[Documents],
        source_url: str,
        provenance=None,
    ):
        records = []
        required_fields = (
            "district",
            "bajar",
            "tarikh",
            "phasal",
            "vividhata",
            "kimat",
            "nuntamkimat",
            "adhikatamkimat",
        )

        for document in documents:
            page_records = json.loads(document.page_content)
            if not isinstance(page_records, list):
                raise ValueError("Mandi document content must be a JSON list")

            for record_index, record in enumerate(page_records):
                if not isinstance(record, dict):
                    raise ValueError(
                        f"Mandi record {record_index} must be a JSON object"
                    )

                missing_fields = set(required_fields) - record.keys()
                if missing_fields:
                    raise ValueError(
                        "Mandi record is missing required fields: "
                        + ", ".join(sorted(missing_fields))
                    )

                raw_date = record["tarikh"]
                try:
                    parsed_date = datetime.strptime(
                        raw_date, "%d/%m/%Y"
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    parsed_date = raw_date

                stored_record = {
                    "district": record["district"],
                    "market": record["bajar"],
                    "date": parsed_date,
                    "crop": record["phasal"],
                    "variety": record["vividhata"],
                    "price": self.extract_price(record["kimat"]),
                    "minimum_price": self.extract_price(
                        record["nuntamkimat"]
                    ),
                    "maximum_price": self.extract_price(
                        record["adhikatamkimat"]
                    ),
                    "unit": "quintal",
                    "source_language": "hi",
                    "source_url": source_url,
                    "scraped_at": datetime.now(),
                    "metadata": document.metadata,
                }
                stored_record.update(provenance or {})
                records.append(stored_record)

        return self.insert_records(records)
