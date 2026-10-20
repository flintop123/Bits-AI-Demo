import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Phase4MandiSchedulerTests(unittest.TestCase):
    def test_daily_runner_refreshes_seven_day_window(self):
        runner = (
            PROJECT_ROOT / "scripts" / "run_daily_mandi.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "run_phase4_mandi_pipeline.py --days 7",
            runner,
        )


if __name__ == "__main__":
    unittest.main()
