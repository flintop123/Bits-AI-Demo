import asyncio
import json
import datetime as dt
from playwright.async_api import async_playwright
from tools.api_extractor.document import Documents

class ReadMundiData:
    def __init__(self) -> None:
        pass

    def load_bihar_krishi_mandi_pages(self, urls):
        documents = asyncio.run(self._load_bihar_krishi_mandi_pages(urls))
        return documents

    async def _get_mandi_table_data(self, page, url):
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        await page.wait_for_timeout(2000)

        # Extract rows from each HTML table.
        tables = await page.locator("table").evaluate_all("""
            tables => tables.map(table =>
                Array.from(table.querySelectorAll("tr")).map(row =>
                    Array.from(row.querySelectorAll("th, td"))
                        .map(cell => cell.innerText.trim())
                )
            )
        """)

        expected_headers = [
            "जिला",
            "बाजार",
            "तारीख",
            "फसल",
            "विविधता",
            "कीमत",
            "न्यूनतम कीमत",
            "अधिकतम कीमत"
        ]

        records = []

        for rows in tables:
            # Find the actual header row.
            header_index = next(
                (
                    i for i, row in enumerate(rows)
                    if len(row) >= 8
                    and "तारीख" in row
                    and "फसल" in row
                    and "विविधता" in row
                ),
                None
            )

            if header_index is None:
                continue

            # Read data rows after the header.
            for row in rows[header_index + 1:]:
                if len(row) < 8:
                    continue

                values = [value.strip() for value in row[:8]]

                # Skip repeated headers and empty rows.
                if "तारीख" in values or not any(values):
                    continue

                records.append({
                    "district": values[0],
                    "bajar": values[1],
                    "tarikh": values[2],
                    "phasal": values[3],
                    "vividhata": values[4],
                    "kimat": values[5],
                    "nuntamkimat": values[6],
                    "adhikatamkimat": values[7]
                })

        return records


    async def _load_bihar_krishi_mandi_pages(self, urls):
        documents = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            try:
                page = await browser.new_page(locale="hi-IN")

                for index, url in enumerate(urls):
                    records = await self._get_mandi_table_data(page, url)

                    print(f"URL: {url}")
                    print(f"Total mandi records: {len(records)}")

                    if records:
                        # Store only the table data in page_content.
                        text = json.dumps(
                            records,
                            ensure_ascii=False,
                            indent=2
                        )

                        documents.append(
                            Documents(
                                page_content=text,
                                metadata={
                                    "source": url,
                                    "CSH_ID": f"bihar_mandi_{index}",
                                    "resolve_id": 1000 + index,
                                    "date": dt.datetime.now().strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    )
                                },
                                source=url
                            )
                        )

                        print(json.dumps(
                            records[:3],
                            ensure_ascii=False,
                            indent=2
                        ))

            finally:
                await browser.close()

        return documents