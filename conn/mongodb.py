import json
import re
from datetime import datetime
from pymongo import MongoClient
from tools.api_extractor.document import Documents


class BiharCropMongo:
    def __init__(self):
        self.client = MongoClient("mongodb://localhost:27017/")
        self.db = self.client["bihar_agriculture"]
        self.collection = self.db["mandi_prices"]

    def insert_records(self, records):
        if records:
            result = self.collection.insert_many(records)
            return len(result.inserted_ids)
        return 0

    def find_records(self, limit=3):
        return list(self.collection.find().limit(limit))

    def extract_price(self, value):
        # Example: "1600.00/क्विंटल" -> 1600.0
        match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value))
        return float(match.group(0).replace(",", "")) if match else None


    def write_mandi_records(self, documents: list[Documents], source_url: str):
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

                records.append({
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
                })

        return self.insert_records(records)