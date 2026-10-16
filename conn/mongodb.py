# from pymongo import MongoClient

# client = MongoClient("mongodb://localhost:27017/")
# print(client.list_database_names())


import json
import re
from datetime import datetime
from pymongo import MongoClient
from tools.translateEngToHindi.translate import translate_text

# MongoDB connection
client = MongoClient("mongodb://localhost:27017/")
db = client["bihar_agriculture"]
collection = db["mandi_prices"]



def extract_price(value):
    # Example: "1600.00/क्विंटल" -> 1600.0
    match = re.search(r"\d+(?:,\d{3})*(?:\.\d+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def prepare_mandi_record(record, source_url):
    # Translate only text fields; don't translate numbers or dates.
    district = translate_text(record.get("district", ""))
    market = translate_text(record.get("market", ""))
    crop = translate_text(record.get("crop", ""))
    variety = translate_text(record.get("variety", ""))

    raw_date = record.get("date", "")
    try:
        parsed_date = datetime.strptime(
            raw_date, "%d/%m/%Y"
        ).strftime("%Y-%m-%d")
    except ValueError:
        parsed_date = raw_date

    return {
        "district": district,
        "market": market,
        "date": parsed_date,
        "crop": crop,
        "variety": variety,
        "price": extract_price(record.get("price", "")),
        "minimum_price": extract_price(
            record.get("minimum_price", "")
        ),
        "maximum_price": extract_price(
            record.get("maximum_price", "")
        ),
        "unit": "quintal",
        "source_language": "hi",
        "source_url": source_url,
        "scraped_at": datetime.now()
    }


# Read records from your existing scraper output.
source_url = "https://www.biharkrishi.in/mandi"
records = []

for doc in loaded_documents:
    records.extend(json.loads(doc.page_content))

print("Scraped records:", len(records))

translated_records = [
    prepare_mandi_record(record, source_url)
    for record in records
]

# Insert records into MongoDB.
if translated_records:
    result = collection.insert_many(translated_records)
    print("Inserted records:", len(result.inserted_ids))
else:
    print("No records to insert.")

# Verify the saved data.
for document in collection.find().limit(3):
    document["_id"] = str(document["_id"])
    print(document)

client.close()
