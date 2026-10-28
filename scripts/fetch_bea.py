
import hashlib
import json
import time
from pathlib import Path

import requests
import trafilatura

OUTPUT_PATH = Path("data/processed/bea_documents.jsonl")

RELEASES = [
    {
        "url": (
            "https://www.bea.gov/news/2025/"
            "gross-domestic-product-4th-quarter-and-year-2024-advance"
        ),
        "title": "Gross Domestic Product, Q4 2024 (Advance Estimate)",
        "published_at": "2025-01-30T08:30:00-05:00",
    },
    {
        "url": (
            "https://www.bea.gov/news/2025/"
            "gross-domestic-product-1st-quarter-2025-advance-estimate"
        ),
        "title": "Gross Domestic Product, Q1 2025 (Advance Estimate)",
        "published_at": "2025-04-30T08:30:00-04:00",
    },
    {
        "url": (
            "https://www.bea.gov/news/2025/"
            "gross-domestic-product-2nd-quarter-2025-advance-estimate"
        ),
        "title": "Gross Domestic Product, Q2 2025 (Advance Estimate)",
        "published_at": "2025-07-30T08:30:00-04:00",
    },
    {
        "url": (
            "https://www.bea.gov/news/2025/"
            "gross-domestic-product-3rd-quarter-2025-advance-estimate"
        ),
        "title": "Gross Domestic Product, Q3 2025 (Advance Estimate)",
        "published_at": None,
    },
]

documents = []

for i, release in enumerate(RELEASES):
    url = release["url"]
    print(f"[{i + 1}/{len(RELEASES)}] Fetching: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        body = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
        )

        if not body:
            print("  Could not extract release text")
            continue

        doc_id = "bea_" + hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:12]

        document = {
            "doc_id": doc_id,
            "title": release["title"],
            "body": body,
            "source": "bea.gov",
            "source_type": "official",
            "url": url,
            "published_at": release["published_at"],
            "gdelt_seen_at": None,
        }

        documents.append(document)

        print(f"  Extracted {len(body)} characters")

    except requests.RequestException as e:
        print(f"  Request failed: {e}")

    time.sleep(1)

if documents:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(documents)} documents to {OUTPUT_PATH}")
else:
    print("\nNo documents retrieved. Existing output left unchanged.")
