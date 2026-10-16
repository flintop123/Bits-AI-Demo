
import asyncio
import json
import datetime as dt
from playwright.async_api import async_playwright
from document import Documents


async def get_mandi_table_data(page, url):
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


async def load_bihar_krishi_mandi_pages(urls):
    documents = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        try:
            page = await browser.new_page(locale="hi-IN")

            for index, url in enumerate(urls):
                records = await get_mandi_table_data(page, url)

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


if __name__ == "__main__":
    urls = ["https://www.biharkrishi.in/mandi"]

    loaded_documents = asyncio.run(
        load_bihar_krishi_mandi_pages(urls)
    )

    print("Total documents:", len(loaded_documents))

    if loaded_documents:
        print(loaded_documents[0].page_content[:3000])




# import asyncio
# import datetime as dt
# from playwright.async_api import async_playwright
# from document import Documents


# async def get_text_from_page(page, url):
#     response = await page.goto(
#         url,
#         wait_until="domcontentloaded",
#         timeout=60000
#     )

#     if response and response.status >= 400:
#         print(f"HTTP error {response.status}: {url}")
#         return None

#     # Wait briefly for JavaScript-rendered content.
#     await page.wait_for_timeout(2000)

#     # Extract text from headings, paragraphs, lists and tables.
#     text = await page.locator(
#         "h1, h2, h3, h4, h5, h6, p, li, "
#         "table, table tr, table th, table td"
#     ).evaluate_all("""
#         elements => elements
#             .map(el => el.innerText.trim())
#             .filter(text => text.length > 0)
#     """)

#     # Remove duplicate strings while preserving order.
#     text = list(dict.fromkeys(text))
#     result = "\\n".join(text).strip()

#     if result:
#         print(f"Extracted {len(result)} characters from {url}")
#         print(result[:1000])
#         return result

#     print(f"No text extracted from {url}")
#     return None


# def create_document(text, url, name, resolve_id):
#     return Documents(
#         page_content=text,
#         metadata={
#             "source": url,
#             "CSH_ID": name,
#             "resolve_id": resolve_id,
#             "date": dt.datetime.now().strftime(
#                 "%Y-%m-%d %H:%M:%S"
#             )
#         },
#         source=url
#     )


# async def load_bihar_krishi_mandi_pages(urls):
#     all_documents = []

#     async with async_playwright() as p:
#         browser = await p.chromium.launch(headless=True)

#         try:
#             context = await browser.new_context(
#                 locale="hi-IN"
#             )
#             page = await context.new_page()

#             for index, url in enumerate(urls):
#                 try:
#                     text = await get_text_from_page(page, url)

#                     if text:
#                         doc = create_document(
#                             text=text,
#                             url=url,
#                             name=f"bihar_krishi_{index}",
#                             resolve_id=1000 + index
#                         )
#                         all_documents.append(doc)

#                 except Exception as exc:
#                     print(f"Failed to process {url}: {exc}")

#         finally:
#             await browser.close()

#     return all_documents


# if __name__ == "__main__":
#     urls = [
#         "https://www.biharkrishi.in/mandi"
#     ]

#     loaded_documents = asyncio.run(
#         load_bihar_krishi_mandi_pages(urls)
#     )

#     print("Total documents:", len(loaded_documents))

#     if loaded_documents:
#         print("First document preview:")
#         print(loaded_documents[0].page_content[:2000])
#         print("Metadata:", loaded_documents[0].metadata)