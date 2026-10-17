# Bits-AI-Demo-For-BIHAR

# Data Collection link -
                       - https://statedata.bihar.gov.in/dataLab/
                       - https://www.biharkrishi.in/
                       - https://horticulture.bihar.gov.in/
                       - https://bssca.co.in/SeedReports.aspx

                       - https://appeears.earthdatacloud.nasa.gov/
                       - https://www.earthdata.nasa.gov/data/catalog/lpcloud-mcd12q1-061#documents-and-resources

''' Agriculture information is already existing, such as MODIS LC, GLC and Globcover data sets.'''

# Some link of learing research paper -

### Satellite Data in Agricultural and EnvironmentalEconomics: Theory and Practice -
https://onlinelibrary.wiley.com/doi/epdf/10.1111/agec.70006

### Monitoring Horizontal and Vertical Cropping Pattern and Dynamics in Bihar
 https://www.academia.edu/44745746/Kumar_Jeganathan_2017_MonitoringHorizontalAndVertical_cropping_pattern_ISRS





 # Mongodb
 ''' To start the monogdb in local system, execute the command - sudo systemctl start mongod.
     To check the status use the command -  sudo systemctl status mongod '''

''' To create database in mongodb, run the command - mongosh (It will open mongodb shell)
                                   to show the database - show dbs
                                   To use specific database - use bitsAiDemoForBihar'''


## Running the mandi ingestion on Windows

Start Docker Desktop and ensure the MongoDB container is running:

```powershell
docker start bihar-mongodb
docker ps --filter "name=bihar-mongodb"
```

Activate the Python environment and run ingestion:

```powershell
.\.venv\Scripts\Activate.ps1
python ingest_mandi.py
```

A repeated run should process the available records but insert zero duplicates.

## Ingesting the crop statistics workbook

The supplied DA&FW workbook contains crop-wise area, production and yield data from 1966-67 to 2024-25. Validate it without changing the database:

```powershell
python ingest_crop_statistics.py --dry-run
```

Load the normalized records into MongoDB:

```powershell
python ingest_crop_statistics.py
```

The records are stored in `bihar_agriculture.crop_statistics`. Repeated runs update existing crop-season-year records without creating duplicates.
## Querying stored agriculture data

The read-only Flask API exposes the mandi prices and normalized crop statistics
stored in MongoDB. Start Docker Desktop, ensure `bihar-mongodb` is running, and
run:

```powershell
python data_api.py
```

Available endpoints:

- `GET /health`
- `GET /api/v1/mandi-prices?limit=10`
- `GET /api/v1/crop-statistics?crop=Rice&year=2024-25&limit=10`
- `GET /api/v1/catalog`

The API binds to `127.0.0.1:5000` by default. Query limits must be between 1
and 100.
## Asking grounded natural-language questions

The `POST /api/v1/ask` endpoint uses the local `qwen3:4b` Ollama model to
convert a natural-language question into an allowlisted query plan. MongoDB is
then queried through the read-only service, and the answer is generated only
from the retrieved records.

Start the API:

```powershell
python data_api.py
```

Example request:

```powershell
$body = @{ question = "What was Rice production in 2024-25?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:5000/api/v1/ask" -ContentType "application/json" -Body $body
```

The response includes the answer, interpreted intent and filters, supporting
database records, source information, and model name. The language model never
receives permission to create arbitrary MongoDB queries.

## Ingesting the official Bihar agriculture PDF

The PDF ingestion command downloads the official Bihar Annual Scheme 2022-23
document and extracts only pages 11-30, which contain the Agriculture and Allied
Sector chapter. Each chunk retains its document title, page number, source URL,
source filename, and content hash.

```powershell
python ingest_agriculture_pdf.py --dry-run
python ingest_agriculture_pdf.py
```

Downloaded PDFs are stored under `data/pdfs/` and are excluded from Git. Repeated
ingestion is duplicate-safe because MongoDB upserts each source/page/chunk identity.

## Searching and asking questions about PDF sources

Search the indexed official document directly:

```text
GET /api/v1/documents/search?q=organic%20farming&limit=5
```

The existing natural-language endpoint also routes scheme, policy, programme,
seed, mechanization, horticulture and similar questions to the PDF collection:

```text
POST /api/v1/ask
{"question": "What does the report say about the organic farming corridor?"}
```

Responses contain the retrieved text, source URL, document title and PDF page
number so that generated answers can be checked against the official source.
## Browser demo

Start MongoDB and ensure the local Qwen model is available, then run:

```powershell
python data_api.py
```

Open `http://127.0.0.1:5000` in a browser. The demo displays collection counts,
accepts natural-language questions, and presents the grounded answer together
with its applied filters, retrieved records, and page-aware source links.

## Multilingual source expansion

The source manifest at `sources/agriculture_sources.yaml` contains an
allowlisted collection of official Bihar and Government of India agriculture
PDFs. It includes English, Hindi, and mixed-language sources. List them with:

```powershell
python ingest_agriculture_sources.py --list-sources
```

Validate extraction without writing to MongoDB:

```powershell
python ingest_agriculture_sources.py --dry-run
```

Ingest all enabled sources and verify duplicate protection by repeating the
same command:

```powershell
python ingest_agriculture_sources.py
python ingest_agriculture_sources.py
```

The extractor first uses the PDF text layer. Pages with missing or unusable
text automatically fall back to local Tesseract OCR with `hin+eng`. Every
stored chunk retains the detected language, extraction method, source
organization, document title, page number and source URL. Original Hindi text
is preserved; it is not replaced by a translation.

Use `--no-ocr` to disable fallback or `--force-ocr` to OCR every selected page.
Downloaded documents and OCR language files are reproducible local artifacts
under `data/` and are excluded from Git.
