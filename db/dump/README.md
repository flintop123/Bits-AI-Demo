# Reproducible database dump

Run `python db/export_dump.py` while the local `bihar-mongodb` container is available. This writes UTF-8 JSONL files for the four documented collections. Run `python db/load_dump.py` to validate every record and load an SQLite relational mirror using `db/schema.sql`. Use `--validate-only` when a second database file is not required.
