"""Persistent and in-memory stores for auditable agent runs."""

import os
from copy import deepcopy

from pymongo import MongoClient

from phase2.models import utc_now


class MemoryRunStore:
    """Small test and offline store with the Mongo store interface."""

    def __init__(self):
        self.runs = {}

    def start(self, run):
        self.runs[run["run_id"]] = deepcopy(run)

    def add_event(self, run_id, event):
        self.runs[run_id].setdefault("events", []).append(deepcopy(event))

    def finish(self, run_id, updates):
        self.runs[run_id].update(deepcopy(updates))

    def get(self, run_id):
        return deepcopy(self.runs[run_id])


class MongoRunStore:
    """Store supervisor decisions, tool events, failures, and metrics."""

    def __init__(self, uri=None):
        uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
        self.client = MongoClient(uri)
        self.db = self.client["bihar_agriculture"]
        self.collection = self.db["agent_runs"]
        self.collection.create_index("run_id", unique=True)
        self.collection.create_index([("started_at", -1)])

    def start(self, run):
        self.client.admin.command("ping")
        self.collection.insert_one(deepcopy(run))

    def add_event(self, run_id, event):
        self.collection.update_one(
            {"run_id": run_id},
            {"$push": {"events": deepcopy(event)}},
        )

    def finish(self, run_id, updates):
        self.collection.update_one(
            {"run_id": run_id},
            {"$set": deepcopy(updates)},
        )

    def get(self, run_id):
        result = self.collection.find_one({"run_id": run_id}, {"_id": 0})
        if result is None:
            raise KeyError(run_id)
        return result


def event(event_type, **details):
    return {"event": event_type, "timestamp": utc_now(), **details}
