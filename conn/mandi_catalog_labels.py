"""Persistent bilingual display labels for values observed in mandi data."""

from datetime import datetime, timezone

from pymongo import UpdateOne

from services.mandi_term_normalizer import MandiTermNormalizer


class MandiCatalogLabelMongo:
    """Cache generated labels without changing source-record values."""

    IDENTITY_FIELDS = ("entity_type", "official_value")
    SUPPORTED_FIELDS = ("crop", "district", "market")
    LABEL_POLICY_VERSION = 3

    def __init__(self, database, normalizer=None):
        self.collection = database["mandi_catalog_labels"]
        self.normalizer = normalizer or MandiTermNormalizer()
        self._index_ready = False

    def _ensure_index(self):
        if self._index_ready:
            return
        self.collection.create_index(
            [(field, 1) for field in self.IDENTITY_FIELDS],
            unique=True,
            name="unique_mandi_catalog_label",
        )
        self._index_ready = True

    def sync(self, field, values):
        """Create missing English/Hindi labels and return cache statistics."""
        if field not in self.SUPPORTED_FIELDS:
            raise ValueError("catalog field must be crop, district or market")
        self._ensure_index()
        official_values = sorted({
            str(value).strip()
            for value in values
            if str(value or "").strip()
        })
        existing = {
            item["official_value"]: item
            for item in self.collection.find({
                "entity_type": field,
                "official_value": {"$in": official_values},
            })
        }
        missing = [
            value for value in official_values
            if value not in existing
            or existing[value].get("label_policy_version")
            != self.LABEL_POLICY_VERSION
        ]
        if not missing:
            return {"observed": len(official_values), "created": 0}

        english = {
            item["value"]: item
            for item in self.normalizer.localized_options(missing, field, "en")
        }
        hindi = {
            item["value"]: item
            for item in self.normalizer.localized_options(missing, field, "hi")
        }
        generated_at = datetime.now(timezone.utc)
        operations = []
        for value in missing:
            en = english[value]
            hi = hindi[value]
            operations.append(UpdateOne(
                {"entity_type": field, "official_value": value},
                {"$set": {
                    "entity_type": field,
                    "official_value": value,
                    "official_language": self.normalizer._language(value),
                    "labels": {"en": en["label"], "hi": hi["label"]},
                    "label_languages": {
                        "en": en["label_language"],
                        "hi": hi["label_language"],
                    },
                    "methods": {"en": en["method"], "hi": hi["method"]},
                    "source_collection": "mandi_prices",
                    "label_policy_version": self.LABEL_POLICY_VERSION,
                    "generated_at": generated_at,
                }},
                upsert=True,
            ))
        self.collection.bulk_write(operations, ordered=False)
        return {"observed": len(official_values), "created": len(missing)}

    def options(self, field, values, language="all", sync_missing=True):
        """Read labels in live-catalog order, retaining official values."""
        if language not in {"all", "en", "hi"}:
            raise ValueError("catalog language must be all, en or hi")
        official_values = sorted({
            str(value).strip()
            for value in values
            if str(value or "").strip()
        })
        if sync_missing:
            self.sync(field, official_values)
        documents = {
            item["official_value"]: item
            for item in self.collection.find({
                "entity_type": field,
                "official_value": {"$in": official_values},
            }, {"_id": 0})
        }
        options = []
        for value in official_values:
            item = documents.get(value)
            if item is None:
                labels = {"en": value, "hi": value}
                methods = {"en": "cache_miss", "hi": "cache_miss"}
                label_languages = {
                    "en": self.normalizer._language(value),
                    "hi": self.normalizer._language(value),
                }
            else:
                labels = item.get("labels", {})
                methods = item.get("methods", {})
                label_languages = item.get("label_languages", {})
            option = {
                "value": value,
                "labels": {
                    "en": labels.get("en", value),
                    "hi": labels.get("hi", value),
                },
                "methods": {
                    "en": methods.get("en", "cache_miss"),
                    "hi": methods.get("hi", "cache_miss"),
                },
            }
            if language != "all":
                option.update({
                    "label": option["labels"][language],
                    "label_language": label_languages.get(language, language),
                    "method": option["methods"][language],
                })
            options.append(option)
        label_key = (
            (lambda item: item["labels"].get("en", item["value"]).casefold())
            if language == "all"
            else (lambda item: item["label"].casefold())
        )
        return sorted(options, key=label_key)
