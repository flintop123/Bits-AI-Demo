-- Portable relational mirror of the runtime MongoDB collections.
CREATE TABLE mandi_prices (
  source_record_id TEXT PRIMARY KEY, district_code TEXT, district TEXT NOT NULL,
  market_code TEXT, market TEXT NOT NULL, observation_date TEXT NOT NULL,
  crop_code TEXT, crop TEXT NOT NULL, variety TEXT, price REAL,
  minimum_price REAL, maximum_price REAL, unit TEXT NOT NULL,
  source_url TEXT NOT NULL, extraction_run_id TEXT NOT NULL,
  extracting_agent TEXT NOT NULL, extracted_at TEXT NOT NULL
);
CREATE INDEX idx_mandi_local_time ON mandi_prices(district, market, crop, observation_date);

CREATE TABLE crop_statistics (
  crop TEXT NOT NULL, season TEXT NOT NULL, crop_year TEXT NOT NULL,
  area_hectares REAL, production REAL, yield_kg_per_hectare REAL,
  production_unit TEXT NOT NULL, source_file TEXT NOT NULL,
  source_row INTEGER NOT NULL, extraction_run_id TEXT,
  extracting_agent TEXT, extracted_at TEXT,
  PRIMARY KEY(crop, season, crop_year)
);

CREATE TABLE agriculture_documents (
  content_hash TEXT PRIMARY KEY, document_title TEXT NOT NULL,
  page_number INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL, language TEXT, extraction_method TEXT,
  source_url TEXT NOT NULL, source_file TEXT NOT NULL,
  extraction_run_id TEXT, extracting_agent TEXT, extracted_at TEXT
);

CREATE TABLE mandi_locations (
  market_code TEXT PRIMARY KEY, market_name TEXT NOT NULL, district_name TEXT NOT NULL,
  longitude REAL NOT NULL, latitude REAL NOT NULL, precision TEXT NOT NULL,
  verification_status TEXT NOT NULL CHECK(verification_status = 'verified'),
  coordinate_source_url TEXT NOT NULL
);
