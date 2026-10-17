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

    def health(self):
        self.client.admin.command("ping")
        return {
            "status": "ok",
            "database": "bihar_agriculture",
            "collections": {
                "mandi_prices": self.mandi_prices.count_documents({}),
                "crop_statistics": self.crop_statistics.count_documents({}),
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
