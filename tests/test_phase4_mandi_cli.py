import unittest
from datetime import date

from run_phase4_mandi_pipeline import resolve_dates


class Phase4MandiCliTests(unittest.TestCase):
    def test_default_day_window_ends_on_today(self):
        self.assertEqual(
            resolve_dates(None, 3, today=date(2026, 10, 18)),
            [date(2026, 10, 16), date(2026, 10, 17), date(2026, 10, 18)],
        )

    def test_explicit_dates_are_validated_and_deduplicated(self):
        self.assertEqual(
            resolve_dates(["2026-10-18", "2026-10-18"], 1),
            [date(2026, 10, 18)],
        )

    def test_excessive_catch_up_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 366"):
            resolve_dates(None, 500, today=date(2026, 10, 18))


if __name__ == "__main__":
    unittest.main()
