# AsOf Retrieval

[CLICK HERE FOR FINALIZED LIST OF DOCUMENTS](data/processed/corpus.jsonl)

Scripts specific to just getting the data for the project / explanation / source code as to how this corpus was built in the first place:

## Data Sources

Documents that were collected

FOMC statements from Federal Reserve: 
- Automated Collection (but the dates were hard coded manually in the script from https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm - TODO: get this dynamically??) 

GDP news releases and Personal Consumption Expenditures (PCE) from Bureau of Economic Analysis (BEA)
- Automated archive discovery and document extraction (two scripts)
- GDP release dates also fetched and hard coded from https://www.bea.gov/news/schedule/full-2025 

CPI and Unemployment news releases from Bureau of Labor Statistics (BLS)
- Manually downloaded HTML files, and parsed via script (two scripts)

Liberty Street Economics articles from Federal Reserve Bank of New York
- Automated archive discovery and document extraction (combined singular script)

Collection is currently configured for 2025.

## Setup

Install Python dependencies from the repository root:

```bash
pip install -r requirements.txt
```

Run all commands below from the repository root so the relative data paths resolve correctly.

## Data Collection

### Federal Reserve

```bash
python scripts/fetch_fed.py
```

Fetches FOMC statements for the configured meeting dates and extracts their text and publication timestamps.

Output: `data/processed/fed_documents.jsonl`

### Bureau of Economic Analysis (BEA)

First, discover GDP releases from the BEA archive:

```bash
python scripts/discover_bea.py
```

Output: `data/raw/bea_releases_2025.json`

Then fetch and extract the discovered releases:

```bash
python scripts/fetch_bea.py
```

Output: `data/processed/bea_documents.jsonl`

### Bureau of Labor Statistics (BLS)

We were not able to fetch BLS releases because of access restrictions and timeouts so just went to https://www.bls.gov/bls/news-release/cpi.htm

Download and save the relevant CPI release HTML pages in:

`data/raw/bls/`

Then run:

```bash
python scripts/import_bls.py
```

The importer extracts the release text and publication information from the saved HTML files.

Output: `data/processed/bls_documents.jsonl`

### New York Fed

```bash
python scripts/fetch_nyfed.py
```

Discovers articles from the configured year's monthly Liberty Street Economics archives, extracts article text, and reads publication timestamps from page metadata.

Output: `data/processed/nyfed_documents.jsonl`

## Building the Corpus

After collecting the source documents, run:

```bash
python scripts/build_corpus.py
```

Output: `data/processed/corpus.jsonl`


## Doc Format

Documents are stored as JSON Lines (`.jsonl`), with one JSON object per line.

Common fields include:

| Field | Description |
|---|---|
| `doc_id` | Unique document identifier |
| `title` | Document title |
| `body` | Extracted text |
| `source` | Source website |
| `source_type` | Document category |
| `url` | Original document URL |
| `published_at` | Publication timestamp with timezone |
| `published_at_verified` | whether the source-specific collector marked the timestamp as verified (verification methods vary by source) |

Some docs contain additional source-specific metadata.

