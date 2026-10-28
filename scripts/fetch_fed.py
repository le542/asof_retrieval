
import hashlib
import json
import time
from pathlib import Path

import requests
import trafilatura

OUTPUT_PATH = Path("data/processed/fed_documents.jsonl")

# Scheduled FOMC statement dates in 2025
RELEASE_DATES = [
    "20250129",
    "20250319",
    "20250507",
    "20250618",
    "20250730",
    "20250917",
    "20251029",
    "20251210",
]

RELEASES = []

for date in RELEASE_DATES:
    year = date[:4]
    month = date[4:6]
    day = date[6:8]

    # Eastern Time: EST in January and December,
    # EDT for the other scheduled meeting dates.
    offset = "-05:00" if month in ("01", "12") else "-04:00"

    RELEASES.append({
        "url": (
            "https://www.federalreserve.gov/"
            "newsevents/pressreleases/"
            f"monetary{date}a.htm"
        ),
        "title": (
            f"Federal Reserve issues FOMC statement "
            f"- {year}-{month}-{day}"
        ),
        "published_at": (
            f"{year}-{month}-{day}T14:00:00{offset}"
        ),
    })

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
            print("  Could not extract article text")
            continue

        doc_id = "fed_" + hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:12]

        document = {
            "doc_id": doc_id,
            "title": release["title"],
            "body": body,
            "source": "federalreserve.gov",
            "source_type": "official",
            "url": url,
            "published_at": release["published_at"],
            "gdelt_seen_at": None,
        }

        documents.append(document)

        print(f"  Extracted {len(body)} characters")

    except requests.RequestException as e:
        print(f"  Request failed: {e}")

    # Be respectful of the Federal Reserve's servers
    time.sleep(1)

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    for document in documents:
        f.write(json.dumps(document, ensure_ascii=False) + "\n")

print(f"\nSuccessfully extracted {len(documents)} documents")
print(f"Saved to {OUTPUT_PATH}")
