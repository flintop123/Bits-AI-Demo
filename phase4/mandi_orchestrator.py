"""Auditable agent orchestration for daily Bihar mandi collection."""

import time
import uuid
from datetime import datetime, timezone

from phase4.mandi_api_client import PAGE_URL, BiharMandiApiClient


AGENT_ID = "daily_mandi_api_agent"
TOOL_NAME = "bihar_mandi_paginated_api"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_api_record(record, *, run_id, collected_at):
    arrival = datetime.fromtimestamp(
        record["arrivalDate"] / 1000, tz=timezone.utc
    )
    additional = record.get("additionalFields") or {}
    audit = record.get("auditDetails") or {}
    extraction_time = (
        collected_at.isoformat()
        if isinstance(collected_at, datetime)
        else str(collected_at)
    )
    return {
        "source_record_id": str(record["id"]),
        "district_code": str(additional.get("districtLg") or ""),
        "district": str(additional.get("district") or "").strip(),
        "market_code": record.get("marketCenterCode"),
        "market": str(record.get("marketCenter") or "").strip(),
        "date": arrival.date().isoformat(),
        "arrival_date_epoch_ms": record["arrivalDate"],
        "arrival_quantity": record.get("arrivalQuantity"),
        "arrival_unit": record.get("arrivalUnit"),
        "crop_code": record.get("commodityCode"),
        "crop": str(record.get("commodity") or "").strip(),
        "variety_code": record.get("varietyCode"),
        "variety": str(record.get("variety") or "").strip(),
        "grade_code": record.get("gradeCode"),
        "grade": record.get("grade"),
        "price": record.get("modalPrice"),
        "minimum_price": record.get("minPrice"),
        "maximum_price": record.get("maxPrice"),
        "price_trend": record.get("priceTrend"),
        "unit": "quintal",
        "source_price_unit": record.get("priceUnit"),
        "source_language": "hi",
        "source_url": PAGE_URL,
        "source_api": "Bihar Krishi agriMarket staticData API",
        "source_created_at_epoch_ms": audit.get("createdTime"),
        "source_modified_at_epoch_ms": audit.get("lastModifiedTime"),
        "scraped_at": collected_at,
        "extraction_run_id": run_id,
        "extracting_agent": AGENT_ID,
        "source_type": "government_mandi_api",
        "extracted_at": extraction_time,
        "temporal_granularity": "day",
        "spatial_granularity": "market",
        "metadata": {
            "tenant_id": record.get("tenantId"),
            "row_version": record.get("rowVersion"),
            "official_district_code": additional.get("districtLg"),
            "official_market_code": record.get("marketCenterCode"),
            "official_commodity_code": record.get("commodityCode"),
        },
    }


class DailyMandiOrchestrator:
    """Route each day to the API agent, retry, validate, and persist."""

    def __init__(
        self,
        *,
        client=None,
        database=None,
        page_size=100,
        max_retries=1,
        sleeper=None,
    ):
        self.client = client or BiharMandiApiClient()
        self.database = database
        self.page_size = page_size
        self.max_retries = max_retries
        self.sleeper = sleeper or time.sleep

    def run(self, collection_dates, *, dry_run=False):
        dates = [str(value) for value in dict.fromkeys(collection_dates)]
        if not dates:
            raise ValueError("At least one collection date is required")
        run_id = str(uuid.uuid4())
        run = {
            "run_id": run_id,
            "orchestrator": "phase4_daily_mandi_supervisor",
            "agent_id": AGENT_ID,
            "tool_name": TOOL_NAME,
            "routing_strategy": "one_date_per_agent_tool_invocation",
            "collection_dates": dates,
            "dry_run": dry_run,
            "status": "running",
            "started_at": utc_now(),
            "events": [],
        }
        if not dry_run:
            if self.database is None:
                from conn.mandi_observations import MandiObservationMongo
                self.database = MandiObservationMongo()
            self.database.start_run(run)

        results = []
        total_retries = 0
        for selected_date in dates:
            item = None
            for attempt in range(1, self.max_retries + 2):
                event = {
                    "event": "tool_invoked",
                    "timestamp": utc_now(),
                    "agent_id": AGENT_ID,
                    "tool_name": TOOL_NAME,
                    "date": selected_date,
                    "attempt": attempt,
                }
                run["events"].append(event)
                try:
                    fetched = self.client.fetch_day(
                        selected_date, page_size=self.page_size
                    )
                    collected_at = datetime.now(timezone.utc)
                    records = [
                        normalize_api_record(
                            record,
                            run_id=run_id,
                            collected_at=collected_at,
                        )
                        for record in fetched["records"]
                    ]
                    write = {"inserted": 0, "matched": 0, "modified": 0}
                    count_before = count_after = None
                    if not dry_run:
                        count_before = self.database.collection.count_documents({})
                        write = self.database.upsert_records(records)
                        count_after = self.database.collection.count_documents({})
                    item = {
                        "date": selected_date,
                        "status": "completed",
                        "attempts": attempt,
                        "pages_fetched": fetched["pages_fetched"],
                        "records_reported": fetched["total_count"],
                        "records_processed": len(records),
                        "districts": len({r["district_code"] for r in records}),
                        "markets": len({r["market_code"] for r in records}),
                        "commodities": len({r["crop_code"] for r in records}),
                        "count_before": count_before,
                        "count_after": count_after,
                        **write,
                    }
                    run["events"].append({
                        "event": "tool_result",
                        "timestamp": utc_now(),
                        "date": selected_date,
                        "attempt": attempt,
                        "status": "success",
                        "records_processed": len(records),
                    })
                    break
                except Exception as exc:
                    retrying = attempt <= self.max_retries
                    run["events"].append({
                        "event": "tool_result",
                        "timestamp": utc_now(),
                        "date": selected_date,
                        "attempt": attempt,
                        "status": "failed",
                        "retrying": retrying,
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                    if retrying:
                        total_retries += 1
                        self.sleeper(2 ** (attempt - 1))
                        continue
                    item = {
                        "date": selected_date,
                        "status": "failed",
                        "attempts": attempt,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
            results.append(item)

        completed = sum(item["status"] == "completed" for item in results)
        status = (
            "completed" if completed == len(results)
            else "partial_failure" if completed else "failed"
        )
        updates = {
            "status": status,
            "completed_at": utc_now(),
            "results": results,
            "metrics": {
                "dates_requested": len(dates),
                "dates_completed": completed,
                "automation_rate": round(completed / len(dates), 4),
                "manual_interventions": 0,
                "retries": total_retries,
                "records_processed": sum(
                    item.get("records_processed", 0) for item in results
                ),
                "inserted": sum(item.get("inserted", 0) for item in results),
                "matched": sum(item.get("matched", 0) for item in results),
                "modified": sum(item.get("modified", 0) for item in results),
            },
        }
        run.update(updates)
        if not dry_run:
            self.database.finish_run(run_id, updates)
        return run
