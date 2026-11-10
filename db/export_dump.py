import argparse
import json
from pathlib import Path
from pymongo import MongoClient


COLLECTIONS = ("mandi_prices", "crop_statistics", "agriculture_documents", "mandi_locations")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="mongodb://localhost:27017/")
    parser.add_argument("--output", default="db/dump")
    args = parser.parse_args()
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    client = MongoClient(args.uri)
    try:
        database = client["bihar_agriculture"]
        for name in COLLECTIONS:
            count = 0
            with (target / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
                for document in database[name].find({}, {"_id": 0}):
                    handle.write(json.dumps(document, ensure_ascii=False, default=str) + "\n")
                    count += 1
            print(f"{name}: {count}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
