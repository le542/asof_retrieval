
import hashlib
import json
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import trafilatura

INPUT_PATH = Path("data/raw/bea_releases_2025.json")
OUTPUT_PATH = Path("data/processed/bea_documents.jsonl")

EASTERN = ZoneInfo("America/New_York")

# sourced from https://www.bea.gov/news/schedule/full-2025
VERIFIED_RELEASE_DATES = {
    "2025-01-30",
    "2025-02-27",
    "2025-03-27",
    "2025-04-30",
    "2025-05-29",
    "2025-06-26",
    "2025-07-30",
    "2025-08-28",
    "2025-09-25",
    "2025-12-23",
}


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            f"Missing {INPUT_PATH}. Run discover_bea.py first."
        )

    with INPUT_PATH.open(encoding="utf-8") as f:
        releases = json.load(f)

    print(f"Loaded {len(releases)} BEA releases")

    session = requests.Session()
    session.headers["User-Agent"] = "AsOfRetrieval"

    documents = []
    failed = []

    for i, release in enumerate(releases, start=1):
        url = release["url"]
        published_date = release["published_date"]

        print(f"[{i}/{len(releases)}] {release['title']}")

        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()

            body = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
            )

            if not body or len(body.strip()) < 100:
                raise ValueError("Not enough text extracted")

            # archive gives us the date, but not the exact time.
            release_date = datetime.fromisoformat(published_date).date()
            published_at = datetime.combine(
                release_date,
                dt_time(8, 30), # use 8:30 AM Eastern for BEA GDP releases since that's when they usually publish
                tzinfo=EASTERN,
            ).isoformat()

            doc_id = "bea_" + hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest()[:12]

            documents.append({
                "doc_id": doc_id,
                "title": release["title"],
                "body": body,
                "source": "bea.gov",
                "source_type": "official",
                "url": url,
                "published_at": published_at,
                "published_at_verified": published_date in VERIFIED_RELEASE_DATES,
                # "gdelt_seen_at": None,  # not needed anymore
            })

            print(f"  Extracted {len(body)} characters")

        except (requests.RequestException, ValueError) as exc:
            print(f"  Failed: {exc}")
            failed.append(url)

        time.sleep(1)

    # Don't overwrite the existing dataset if any releases failed.
    if failed:
        print(f"\nFailed to process {len(failed)} releases:")
        for url in failed:
            print(f"  {url}")
        print("Output not written.")
        return

    if not documents:
        print("\nNo documents extracted. Output not written.")
        return

    documents.sort(key=lambda doc: doc["published_at"])
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(documents)} documents to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
