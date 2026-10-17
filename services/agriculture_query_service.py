"""Read-only MongoDB queries for agriculture data."""

import os
import re

from pymongo import MongoClient


class AgricultureQueryService:
    def __init__(self, database=None, uri=None):
        if database is None:
            uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
            self.client = MongoClient(uri)
            self.database = self.client["bihar_agriculture"]
        else:
            self.database = database
            self.client = database.client

        self.mandi_prices = self.database["mandi_prices"]
        self.crop_statistics = self.database["crop_statistics"]
        self.agriculture_documents = self.database["agriculture_documents"]

    def health(self):
        self.client.admin.command("ping")
        return {
            "status": "ok",
            "database": "bihar_agriculture",
            "collections": {
                "mandi_prices": self.mandi_prices.count_documents({}),
                "crop_statistics": self.crop_statistics.count_documents({}),
                "agriculture_documents": (
                    self.agriculture_documents.count_documents({})
                ),
            },
        }

    def find_mandi_prices(self, filters, limit):
        query = {}
        for field in ("district", "market", "crop", "variety"):
            value = filters.get(field)
            if value:
                query[field] = self._exact_text(value)
        if filters.get("date"):
            query["date"] = filters["date"]

        cursor = self.mandi_prices.find(query, {"_id": 0})
        cursor = cursor.sort([("date", -1), ("district", 1), ("crop", 1)])
        return list(cursor.limit(limit))

    def find_crop_statistics(self, filters, limit):
        query = {}
        for field in ("crop", "season"):
            value = filters.get(field)
            if value:
                query[field] = self._exact_text(value)
        if filters.get("year"):
            query["year"] = filters["year"]

        cursor = self.crop_statistics.find(query, {"_id": 0})
        cursor = cursor.sort([("year", -1), ("crop", 1), ("season", 1)])
        return list(cursor.limit(limit))

    def search_agriculture_documents(self, search_terms, limit):
        search_terms = str(search_terms or "").strip()
        if not search_terms:
            raise ValueError("search terms are required")
        if len(search_terms) > 200:
            raise ValueError("search terms must not exceed 200 characters")

        projection = {
            "_id": 0,
            "document_title": 1,
            "page_number": 1,
            "chunk_index": 1,
            "content": 1,
            "source_url": 1,
            "source_file": 1,
            "score": {"$meta": "textScore"},
        }
        cursor = self.agriculture_documents.find(
            {"$text": {"$search": search_terms}},
            projection,
        )
        cursor = cursor.sort([("score", {"$meta": "textScore"})])
        return list(cursor.limit(limit))

    def list_values(self):
        return {
            "mandi_crops": sorted(self.mandi_prices.distinct("crop")),
            "districts": sorted(self.mandi_prices.distinct("district")),
            "statistical_crops": sorted(
                self.crop_statistics.distinct("crop")
            ),
            "seasons": sorted(self.crop_statistics.distinct("season")),
        }

    @staticmethod
    def _exact_text(value):
        return {
            "$regex": f"^{re.escape(value.strip())}$",
            "$options": "i",
        }
