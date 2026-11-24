import copy
import unittest
from unittest.mock import MagicMock

from eval.round2_demo import (
    HERE, check_case, distance_km, dump_query, load_cases, load_dump, mongo_query,
)


class Round2DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {case["id"]: case for case in load_cases()}
        cls.dump, cls.hashes = load_dump(HERE.parent / "db" / "dump")

    def test_all_ten_rehearse_against_committed_dump(self):
        self.assertEqual(len(self.cases), 10)
        categories = [case["category"] for case in self.cases.values()]
        self.assertGreaterEqual(categories.count("spatial"), 2)
        self.assertGreaterEqual(categories.count("temporal"), 2)
        self.assertGreaterEqual(categories.count("provenance"), 1)
        self.assertEqual(len(self.hashes), 4)
        for case in self.cases.values():
            with self.subTest(case=case["id"]):
                result = check_case(case, dump_query(self.dump, case))
                self.assertEqual(result["status"], "PASS", result["errors"])

    def test_wrong_value_and_duplicate_both_fail(self):
        case = self.cases["Q01"]
        records = dump_query(self.dump, case)
        wrong = {**records[0], "price": 999}
        self.assertEqual(check_case(case, [wrong])["status"], "FAIL")
        self.assertEqual(check_case(case, records * 2)["status"], "FAIL")

    def test_wrong_excerpt_fails_despite_correct_source_fields(self):
        case = self.cases["Q07"]
        records = dump_query(self.dump, case)
        wrong = {**records[0], "content": "Different content"}
        self.assertEqual(check_case(case, [wrong])["status"], "FAIL")

    def test_nearby_excludes_unverified_and_distant_points(self):
        case = self.cases["Q02"]
        row = dump_query(self.dump, case)[0]
        distant = copy.deepcopy(row)
        distant["location"]["coordinates"][0] += 1.0
        unverified = {**row, "verification_status": "unresolved"}
        records = dump_query({"mandi_locations": [row, distant, unverified]}, case)
        self.assertEqual(records, [row])
        self.assertAlmostEqual(distance_km((84, 25), (84, 25)), 0)
        self.assertGreater(distance_km((84, 25), (85, 25)), 100)

    def test_nearby_live_pipeline_is_bounded_and_read_only(self):
        database = MagicMock()
        collection = database["mandi_locations"]
        collection.aggregate.return_value = []
        self.assertEqual(mongo_query(database, self.cases["Q02"]), [])
        pipeline = collection.aggregate.call_args.args[0]
        self.assertEqual([next(iter(stage)) for stage in pipeline],
                         ["$geoNear", "$limit", "$project"])
        self.assertEqual(pipeline[0]["$geoNear"]["query"], {"verification_status": "verified"})
        self.assertEqual(pipeline[0]["$geoNear"]["maxDistance"], 1000)
        self.assertEqual(pipeline[0]["$geoNear"]["near"]["coordinates"], [84.662895, 25.24324])

    def test_exact_live_filter_and_projection(self):
        database = MagicMock()
        case = self.cases["Q07"]
        collection = database["agriculture_documents"]
        collection.find.return_value.max_time_ms.return_value.limit.return_value = []
        self.assertEqual(mongo_query(database, case), [])
        filters, projection = collection.find.call_args.args
        self.assertEqual(filters, case["filters"])
        self.assertEqual(projection["content"], 1)
        self.assertEqual(projection["_id"], 0)


if __name__ == "__main__":
    unittest.main()
