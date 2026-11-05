
import hashlib
import json
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import trafilatura

INPUT_PATH = Path("data/raw/bea_releases_2025.json")
OUTPUT_PATH = Path("data/processed/bea_documents.jsonl")

# Provisional time; verify before historical evaluation.
RELEASE_HOUR = 8
RELEASE_MINUTE = 30

if not INPUT_PATH.exists():
    raise FileNotFoundError(
        f"Missing {INPUT_PATH}. Run discover_bea.py first."
    )

with INPUT_PATH.open("r", encoding="utf-8") as f:
    releases = json.load(f)

print(f"Loaded {len(releases)} BEA releases")

documents = []
failed = []

session = requests.Session()
session.headers.update({
    "User-Agent": "AsOfRetrieval/0.1 (academic research)"
})

for i, release in enumerate(releases, start=1):
    url = release["url"]
    title = release["title"]
    published_date = release["published_date"]

    print(f"\n[{i}/{len(releases)}] {title}")

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()

        body = trafilatura.extract(
            response.text,
            include_comments=False,
            include_tables=False,
        )

        if not body or len(body.strip()) < 100:
            print("  Failed to extract sufficient text")
            failed.append(url)
            continue

        release_day = date.fromisoformat(published_date)

        eastern_time = datetime(
            release_day.year,
            release_day.month,
            release_day.day,
            RELEASE_HOUR,
            RELEASE_MINUTE,
            tzinfo=ZoneInfo("America/New_York"),
        )

        doc_id = "bea_" + hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:12]

        document = {
            "doc_id": doc_id,
            "title": title,
            "body": body,
            "source": "bea.gov",
            "source_type": "official",
            "url": url,
            "published_at": eastern_time.isoformat(),
            "published_at_verified": False,
            "gdelt_seen_at": None,
        }

        documents.append(document)

        print(f"  Extracted {len(body)} characters")
        print(f"  Publication date: {published_date}")

    except (requests.RequestException, ValueError) as e:
        print(f"  Failed: {e}")
        failed.append(url)

    time.sleep(1)

if documents:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(documents)} documents")
    print(f"Output: {OUTPUT_PATH}")
else:
    print("\nNo documents extracted. Existing output unchanged.")

print(f"Failed releases: {len(failed)}")

for url in failed:
    print(f"  {url}")
