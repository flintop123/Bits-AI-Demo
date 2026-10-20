import unittest

from export_team_contributions import build_report, parse_git_history


class TeamContributionEvidenceTests(unittest.TestCase):
    def test_git_history_is_grouped_without_guessing_contributions(self):
        history = (
            "@@COMMIT@@abc123\x1fAnuj Tomar\x1f2026-10-17\x1fAdd tests\n"
            "tests/test_example.py\n\n"
            "@@COMMIT@@def456\x1fAnuj Tomar\x1f2026-10-17\x1fAdd agent\n"
            "phase2/agents.py\n"
        )

        report = build_report(parse_git_history(history))

        self.assertEqual(len(report["authors"]), 1)
        author = report["authors"][0]
        self.assertEqual(author["commits"], 2)
        self.assertEqual(author["work_areas"]["tests"], 1)
        self.assertEqual(author["work_areas"]["agent_orchestration"], 1)
        self.assertIn("committed repository work only", report["scope_note"])


if __name__ == "__main__":
    unittest.main()
