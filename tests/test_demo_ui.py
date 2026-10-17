import unittest

from data_api import create_app


class FakeQueryService:
    def health(self):
        return {
            "status": "ok",
            "database": "bihar_agriculture",
            "collections": {
                "mandi_prices": 10,
                "crop_statistics": 4372,
                "agriculture_documents": 54,
            },
        }


class DemoUiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app(FakeQueryService()).test_client()

    def test_home_page_renders_demo_interface(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Bihar Agriculture Intelligence", response.data)
        self.assertIn(b'id="question-form"', response.data)
        self.assertIn(b'/static/app.js', response.data)

    def test_static_assets_are_available(self):
        css_response = self.client.get("/static/app.css")
        js_response = self.client.get("/static/app.js")

        self.assertEqual(css_response.status_code, 200)
        self.assertEqual(js_response.status_code, 200)
        self.assertIn(b"--forest", css_response.data)
        self.assertIn(b"loadHealth", js_response.data)


if __name__ == "__main__":
    unittest.main()
