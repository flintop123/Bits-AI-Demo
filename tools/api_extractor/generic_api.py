"""Read JSON, HTML-table, and text responses from HTTP API endpoints."""

import asyncio
import json

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright


_RECORD_KEYS = ("data", "records", "results", "items")


def _json_records(payload):
    if isinstance(payload, list):
        return [
            item if isinstance(item, dict) else {"value": item}
            for item in payload
        ]
    if isinstance(payload, dict):
        for key in _RECORD_KEYS:
            values = payload.get(key)
            if isinstance(values, list):
                metadata = {
                    name: value
                    for name, value in payload.items()
                    if name != key
                }
                return [
                    (
                        {"record": item, "response_metadata": metadata}
                        if metadata
                        else item if isinstance(item, dict)
                        else {"value": item}
                    )
                    for item in values
                ]
        return [payload]
    return [{"value": payload}]


def _html_table_records(soup):
    records = []
    for table_index, table in enumerate(soup.find_all("table")):
        rows = []
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if values and any(values):
                rows.append((values, any(cell.name == "th" for cell in cells)))
        if not rows:
            continue

        headers, has_header = rows[0]
        if has_header:
            data_rows = rows[1:]
        else:
            headers = [f"column_{index + 1}" for index in range(len(headers))]
            data_rows = rows

        for values, _ in data_rows:
            record = {
                headers[index] if index < len(headers) and headers[index]
                else f"column_{index + 1}": value
                for index, value in enumerate(values)
            }
            if record:
                record["_table_index"] = table_index
                records.append(record)
    return records


def parse_api_response(body, content_type=""):
    """Return a content-kind label and records without assuming a schema."""
    content_type = content_type.lower()
    stripped = body.lstrip()
    looks_like_json = stripped.startswith(("{", "["))

    if "json" in content_type or looks_like_json:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            if "json" in content_type:
                raise ValueError("API response declared JSON but is invalid")
        else:
            return "json", _json_records(payload)

    if "html" in content_type or stripped.lower().startswith(
        ("<!doctype html", "<html")
    ):
        soup = BeautifulSoup(body, "html.parser")
        records = _html_table_records(soup)
        if records:
            return "html_table", records
        text = soup.get_text(" ", strip=True)
        if text:
            return "html_text", [{"text": text}]
        raise ValueError("HTML response contains no text or table data")

    text = body.strip()
    if not text:
        raise ValueError("API response is empty")
    return "text", [{"text": text}]


class PlaywrightApiReader:
    def __init__(self, *, headers=None, timeout_ms=60000, render_wait_ms=2000):
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be at least 1")
        if render_wait_ms < 0:
            raise ValueError("render_wait_ms cannot be negative")
        self.headers = headers or {}
        self.timeout_ms = timeout_ms
        self.render_wait_ms = render_wait_ms

    def load(self, urls):
        return asyncio.run(self._load(urls))

    async def _load(self, urls):
        responses = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    locale="hi-IN",
                    extra_http_headers=self.headers,
                )
                page = await context.new_page()
                for url in urls:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    if response is None:
                        raise RuntimeError(
                            f"Playwright received no response from {url}"
                        )
                    if not response.ok:
                        raise RuntimeError(
                            f"Request to {url} failed with HTTP "
                            f"{response.status}"
                        )

                    content_type = response.headers.get("content-type", "")
                    if "html" in content_type.lower():
                        await page.wait_for_timeout(self.render_wait_ms)
                        body = await page.content()
                    else:
                        body = await response.text()

                    kind, records = parse_api_response(body, content_type)
                    responses.append({
                        "source_url": url,
                        "response_kind": kind,
                        "records": records,
                    })
            finally:
                await browser.close()
        return responses
