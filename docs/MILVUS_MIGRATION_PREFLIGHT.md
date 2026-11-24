# MongoDB-to-Milvus expansion: read-only preflight

The dashboard's Milvus pilot supports one preset question on the 54 exact
reviewed passages from the public Bihar Annual Scheme report. Indexing more
data does not add support for that data to this pilot. Market-price, crop and
spatial questions should keep using their existing structured MongoDB path.

Do **not** run the older database-wide sync to extend this pilot. It enumerates
every collection and serializes entire Mongo documents, including identifiers
and metadata. A live database may also contain examiner PDF uploads, user
requests, job history, retries, errors and audit traces. Those are excluded,
along with unknown collections, local files/paths, operational identifiers,
and unreviewed passages. The preflight reads only aggregate counts from
known internal collections, and opens no unknown collection.

From Windows CMD in the repository:

```bat
.venv\Scripts\python.exe -m scripts.milvus_migration_preflight --live
```

On macOS/Linux:

```sh
.venv/bin/python -m scripts.milvus_migration_preflight --live
```

Without `--live`, the command uses the bundled reproducibility dump and
contacts no service. With `--live` it reads only the local loopback MongoDB;
use `--port` only for a different local port. It does not read the Milvus
config or any secret, export records, compute embeddings, write to Mongo,
or contact Milvus. Output contains counts and whether exact current matches
for the existing pinned passages are present; record text is not printed.

The checked-in snapshot has 221 PDF passages (54 match the current pilot),
7,713 mandi-price rows, 4,372 crop-statistics rows and 42 coordinate records.
The live counts may differ. Source labels and a verified-coordinate label are
inventory checks only, not proofs of public provenance, licence or approval
to upload. The nonreport structured collections are not included in a vector
export by this tool.

Before a separate migration, establish source ownership/licence, review the
precise outbound fields and passage bytes, leave internal rows out, and get
approval for a dedicated collection and credential. Use an audited, bounded
public-document selector and citation checks for each additional source.
Keep structured facts on their deterministic lookup path unless a separate
use case and approved design justify duplicating them. Code review and a
repository PR are independent of any later data upload.
