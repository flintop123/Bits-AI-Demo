"""MongoDB history of finished extractor runs.

One document per run in ``extractor_runs``:

    run_id, human_input, is_human_input_overridden, overridden_input,
    dry_run, tool, status, started_at, finished_at, logs, result, error

``human_input`` is what the user typed. ``is_human_input_overridden`` is true
when the user answered the clarification popup, in which case the request the
agent actually received is kept in ``overridden_input``.
"""

COLLECTION = "extractor_runs"
PAGE_SIZE = 10

_LIST_FIELDS = {
    "_id": 0, "run_id": 1, "human_input": 1, "is_human_input_overridden": 1,
    "dry_run": 1, "tool": 1, "status": 1, "started_at": 1, "finished_at": 1,
}


class RunHistoryStore:
    def __init__(self, database_factory, page_size=PAGE_SIZE):
        self._database = database_factory
        self.page_size = page_size
        self._indexed = False

    def _collection(self):
        collection = self._database()[COLLECTION]
        if not self._indexed:
            collection.create_index([("started_at", -1)])
            self._indexed = True
        return collection

    def save(self, document):
        collection = self._collection()
        collection.update_one(
            {"_id": document["run_id"]}, {"$set": document}, upsert=True,
        )

    def page(self, page=1):
        """Newest first, ``page_size`` per page, without the (large) logs."""
        collection = self._collection()
        total = collection.count_documents({})
        pages = max(1, -(-total // self.page_size))
        page = min(max(1, page), pages)
        items = list(
            collection.find({}, _LIST_FIELDS)
            .sort([("started_at", -1), ("_id", -1)])
            .skip((page - 1) * self.page_size)
            .limit(self.page_size)
        )
        return {
            "items": items, "page": page, "pages": pages,
            "page_size": self.page_size, "total": total,
        }

    def get(self, run_id):
        return self._collection().find_one({"_id": run_id}, {"_id": 0})
