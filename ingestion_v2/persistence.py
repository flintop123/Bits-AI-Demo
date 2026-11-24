"""Allowlisted persistence for records that already passed validation."""

from collections import Counter

from ingestion_v2.models import (
    PersistInput,
    PersistOutput,
    TargetCollection,
    WriteMode,
)


CONNECTORS = {
    TargetCollection.AGRICULTURE_DOCUMENTS: (
        "conn.agriculture_documents_mongodb",
        "AgricultureDocumentsMongo",
    ),
    TargetCollection.AGRICULTURE_FACTS: (
        "conn.agriculture_facts_mongodb",
        "AgricultureFactsMongo",
    ),
    TargetCollection.CROP_STATISTICS: (
        "conn.crop_statistics_mongodb",
        "CropStatisticsMongo",
    ),
    TargetCollection.MANDI_PRICES: (
        "conn.mandi_observations",
        "MandiObservationMongo",
    ),
    TargetCollection.MANDI_LOCATIONS: (
        "conn.mandi_locations",
        "MandiLocationMongo",
    ),
}


def _connector(target):
    import importlib

    module_name, class_name = CONNECTORS[target]
    return getattr(importlib.import_module(module_name), class_name)()


def persist_validated_records(payload: PersistInput, database=None):
    valid = [item for item in payload.records if item.valid]
    eligible = [
        item for item in valid
        if (
            item.mapping_confidence >= payload.minimum_confidence
            and item.data.get("review_status") != "human_review_required"
        )
    ]
    rejected = len(payload.records) - len(valid)
    quarantined = len(valid) - len(eligible)
    targets = Counter(item.target_collection for item in eligible)
    if len(targets) > 1:
        raise ValueError("One persistence call may target only one collection")
    target = next(iter(targets), TargetCollection.QUARANTINE)
    if target not in CONNECTORS and eligible:
        raise ValueError(f"Collection is not allowlisted for writes: {target.value}")
    if payload.write_mode == WriteMode.DRY_RUN or not eligible:
        return PersistOutput(
            write_mode=payload.write_mode,
            target_collection=target,
            attempted=len(payload.records),
            eligible=len(eligible),
            inserted=0,
            matched=0,
            modified=0,
            rejected=rejected,
            quarantined=quarantined,
        )

    database = database or _connector(target)
    values = [item.data for item in eligible]
    if target == TargetCollection.MANDI_LOCATIONS:
        result = database.upsert_verified(values)
    else:
        result = database.upsert_records(values)
    return PersistOutput(
        write_mode=payload.write_mode,
        target_collection=target,
        attempted=len(payload.records),
        eligible=len(eligible),
        inserted=result.get("inserted", 0),
        matched=result.get("matched", 0),
        modified=result.get("modified", 0),
        rejected=rejected,
        quarantined=quarantined,
    )
