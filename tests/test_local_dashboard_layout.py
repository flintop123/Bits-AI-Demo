"""Keep one accessible floating QA form and preserve dashboard deep links."""

from unittest import TestCase
from unittest.mock import Mock

from bs4 import BeautifulSoup

from data_api import create_app


class LocalDashboardLayoutTests(TestCase):
    def setUp(self):
        self.client = create_app(Mock(), Mock()).test_client()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.page = BeautifulSoup(response.get_data(as_text=True), "html.parser")

    def test_one_floating_dialog_owns_existing_question_and_evidence_controls(self):
        launcher = self.page.select_one("#ask-agriagent")
        self.assertEqual(launcher.name, "button")
        self.assertEqual(launcher["aria-haspopup"], "dialog")
        self.assertEqual(launcher["aria-controls"], "agri-chat")
        panel = self.page.select_one("dialog#agri-chat")
        self.assertEqual(panel["aria-labelledby"], "ask-heading")
        self.assertIn("autofocus", panel.select_one("[data-chat-close]").attrs)
        self.assertEqual(len(self.page.select("#question-form")), 1)
        self.assertEqual(len(self.page.select("#result-section")), 1)
        for selector in ("#question-form", "#answer-text", "#source-list", "#record-list",
                         "#react-trace", "#document-chat-trace"):
            self.assertIsNotNone(panel.select_one(selector))
        self.assertEqual(
            [option["value"] for option in panel.select("#question-mode option")],
            ["direct", "react", "document_chat"],
        )
        self.assertEqual(
            [option["value"] for option in panel.select("#answer-language option")],
            ["auto", "en", "hi"],
        )

    def test_overview_exploration_and_intake_keep_their_real_tools(self):
        primary = self.page.select_one("nav[aria-label='Primary navigation']")
        self.assertEqual([link["href"] for link in primary.select("a")],
                         ["#dashboard", "#explore", "#intake", "/extractor/"])
        for selector in ("#daily-chart", ".coverage-details #run-history", ".coverage-details #quality-meters"):
            self.assertIsNotNone(self.page.select_one("#dashboard").select_one(selector))
        for selector in ("#market-map", "#intelligence-form", "#nearby-form", "#district-trends-form"):
            self.assertIsNotNone(self.page.select_one("#explore").select_one(selector))
        for selector in ("#viva-upload-form", "#viva-react-preview", "#viva-doc-question-form",
                         "[data-period-preview='weekly']", "[data-period-preview='monthly']"):
            self.assertIsNotNone(self.page.select_one("#intake").select_one(selector))
        for link in self.page.select("a[href^='#']"):
            if len(link["href"]) > 1:
                self.assertIsNotNone(self.page.find(id=link["href"][1:]), link["href"])

    def test_extractor_is_reachable_from_the_header_and_file_intake(self):
        for nav_label in ("Primary navigation", "File intake tools"):
            links = self.page.select(f"nav[aria-label='{nav_label}'] a[href='/extractor/']")
            self.assertEqual([link.get_text(strip=True) for link in links], ["Extractor agent"])
        page = self.client.get("/extractor/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Past runs", page.get_data())
        page.close()

    def test_overview_has_six_collapsed_keyboard_reachable_drilldowns(self):
        buttons = self.page.select("#dashboard button[data-kpi]")
        self.assertEqual([button["data-kpi"] for button in buttons],
                         ["observations", "dates", "markets", "locations", "crop_statistics", "documents"])
        for button in buttons:
            self.assertEqual(button["aria-expanded"], "false")
            self.assertEqual(button["aria-controls"], "kpi-details")
        self.assertIn("hidden", self.page.select_one("#kpi-details").attrs)
        self.assertIsNotNone(self.page.select_one("#open-date-details"))
        self.assertIsNotNone(self.page.select_one("#daily-insight"))
        art = self.page.select_one(".crop-illustration")
        self.assertEqual(art["alt"], "")
        self.assertTrue(art["src"].startswith("/static/"))
