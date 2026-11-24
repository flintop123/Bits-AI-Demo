# Reproducible database dump

Run `python db/export_dump.py` while the local `bihar-mongodb` container is available. This writes UTF-8 JSONL files for the four documented collections.

- `python db/load_dump.py --validate-only` validates without opening a database.
- `python db/load_dump.py --mongo` seeds the empty local MongoDB demo database
  and reports read-back counts. Keep writers and the app stopped until it
  completes. The loader refuses existing records and does not delete anything.
- `python db/load_dump.py --sqlite path/to/mirror.sqlite` rebuilds the SQLite
  mirror at the specified path using `db/schema.sql`; use a new path.
