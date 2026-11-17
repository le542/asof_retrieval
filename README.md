# AsOf Retrieval

AsOf is a point-in-time search engine for economics prediction-market questions from Kalshi. Given a question and an `as_of` time, it returns the most relevant official releases and NY Fed posts published **before** that time, so a system can't "see the future". We compare four retrieval systems on 59 real 2025 Kalshi questions using graded relevance labels (P@10, NDCG@10).

```
corpus (131 docs) → questions (Kalshi) → index → search (4 systems) → judgments → qrels → evaluation
```

## Quick Start

All commands run from the repo root after [Setup](#setup). Pyserini needs Java 21 (`brew install openjdk@21`).

```bash
source .venv/bin/activate
export JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home

python scripts/fetch_kalshi.py                      # questions -> data/queries.jsonl (already included)
python -m retrieval.build_index --force             # keyword + semantic indexes -> indexes/
for s in bm25 bm25_decay rm3 hybrid; do             # run files -> runs/<system>.txt
  python -m retrieval.search --queries data/queries.jsonl --system $s --run runs/$s.txt
done
python -m retrieval.judgments sheet                 # judgment sheet -> data/labels/judgments.csv
python -m retrieval.llm_label --batch               # Claude grades it (~$12; labels already included, skip this)
python -m retrieval.judgments qrels                 # answer key -> data/qrels.txt
```

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

Create a virtual environment and install the dependencies from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For the Claude API (LLM labeling), either run `ant auth login`, which the SDK picks up automatically, or set `ANTHROPIC_API_KEY`.

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


## Kalshi Questions

`python scripts/fetch_kalshi.py` pulls settled 2025 Kalshi markets (Fed decision, CPI, payrolls, unemployment, GDP, core PCE) from the public API. Each event becomes one question in `data/queries.jsonl`, worded like its highest-volume market. Its `as_of` is the market close, just before the official release; if a market closed after its release, `as_of` is moved to one minute before it.

Questions the corpus can't support are dropped to `data/queries_excluded.jsonl` with the reason: those with no earlier release of their type, and CPI questions past `COVERAGE_END` (CPI releases after Sep 11, 2025 weren't collected). Result: 59 of 72 questions kept.

## Indexing & Retrieval

`python -m retrieval.build_index --force` builds the Lucene index (`indexes/lucene/`), a doc metadata lookup (`indexes/doc_metadata.json`), and passage embeddings for hybrid (`indexes/passage_embeddings.npz`). Rerun it after the corpus changes.

```bash
python -m retrieval.search "Will the Fed cut rates?" --as-of 2025-09-10 --system hybrid
```

```python
from retrieval.search import Retriever
hits = Retriever().search(query, as_of="2025-09-10", system="bm25", k=10)
```

| System | Idea it tests | Defaults |
|---|---|---|
| `bm25` | Baseline: keyword matching | k1=0.9, b=0.4 |
| `bm25_decay` | Recency: BM25 × 0.5^(age_days / 30) | half_life_days=30 |
| `rm3` | Query expansion: RM3 on top of BM25 | fb_docs=10, fb_terms=10, w=0.5 |
| `hybrid` | Meaning: BM25 + semantic search (MiniLM embeddings), merged by reciprocal rank fusion | rrf_k=60 |

- **No future information:** every system drops docs published after `as_of`, and RM3 learns its expansion terms only from earlier docs (pyserini's built-in RM3 can't, so it's implemented in `search.py`). Batch runs report leakage violations; all are 0.
- **Known limitation:** BM25's corpus statistics (IDF, average doc length) include docs after `as_of`.
- Month names and years are stripped from questions (`--no-clean` keeps them), since `as_of` already handles time.

## Relevance Labels

| Grade | Meaning | Example (CPI question) |
|---|---|---|
| 2 | Directly informs the answer | The previous month's CPI release |
| 1 | Same indicator or its direct drivers | An older CPI release; a post on inflation expectations |
| 0 | Not relevant | A jobs report; a post on flood insurance |

Other indicators count as 1 only for Fed questions, and between CPI and core PCE.

- **Full judging, not pooling:** every doc published before a question's `as_of` is graded (4,001 pairs), as Cranfield was. A TREC-style pool of our systems' top 10 would have missed 47% of the relevant judgments.
- **Graded by Claude Sonnet 5.5** (`llm_label.py`, Batch API, about $12), one request per question. On a 177-doc trial it agreed with Opus 5.5 on 98% of grades (kappa 0.97); trial sheets are in `data/labels/trial/`.
- **Output:** `data/qrels.txt`, 977 relevant judgments in mp1's format (`qid doc_id grade`); unlisted docs count as 0.

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

