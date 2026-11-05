
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import trafilatura

OUTPUT_PATH = Path("data/processed/fed_documents.jsonl")

# https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
VERIFIED_RELEASE_DATES = [
    "20250129",
    "20250319",
    "20250507",
    "20250618",
    "20250730",
    "20250917",
    "20251029",
    "20251210",
]

RELEASE_HOUR = 14
RELEASE_MINUTE = 0

REQUEST_DELAY = 1.0


def collect():
    documents = []
    failures = []

    session = requests.Session()
    session.headers.update({
        "User-Agent": "AsOfRetrieval/0.1 (academic research)"
    })

    for i, date_string in enumerate(
        VERIFIED_RELEASE_DATES, start=1
    ):
        release_date = datetime.strptime(
            date_string, "%Y%m%d"
        ).date()

        url = (
            "https://www.federalreserve.gov/"
            "newsevents/pressreleases/"
            f"monetary{date_string}a.htm"
        )

        title = (
            "Federal Reserve issues FOMC statement "
            f"- {release_date.isoformat()}"
        )

        print(
            f"[{i}/{len(VERIFIED_RELEASE_DATES)}] "
            f"Fetching: {url}"
        )

        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()

            body = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
            )

            if not body or len(body.strip()) < 100:
                print("  Could not extract sufficient text")
                failures.append(url)
                continue

            eastern_time = datetime(
                release_date.year,
                release_date.month,
                release_date.day,
                RELEASE_HOUR,
                RELEASE_MINUTE,
                tzinfo=ZoneInfo("America/New_York"),
            )

            doc_id = "fed_" + hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest()[:12]

            document = {
                "doc_id": doc_id,
                "title": title,
                "body": body,
                "source": "federalreserve.gov",
                "source_type": "official",
                "url": url,
                "published_at": eastern_time.isoformat(),
                "published_at_verified": True,
                "gdelt_seen_at": None,
            }

            documents.append(document)

            print(f"  Extracted {len(body)} characters")
            print(
                f"  Verified timestamp: "
                f"{document['published_at']}"
            )

        except requests.RequestException as e:
            print(f"  Request failed: {e}")
            failures.append(url)

        time.sleep(REQUEST_DELAY)

    if documents:
        documents.sort(key=lambda d: d["published_at"])

        OUTPUT_PATH.parent.mkdir(
            parents=True, exist_ok=True
        )

        with OUTPUT_PATH.open("w", encoding="utf-8") as f:
            for document in documents:
                f.write(
                    json.dumps(
                        document, ensure_ascii=False
                    ) + "\n"
                )

        print(
            f"\nSuccessfully extracted "
            f"{len(documents)} documents"
        )
        print(f"Saved to {OUTPUT_PATH}")
    else:
        print(
            "\nNo documents extracted. "
            "Existing output unchanged."
        )

    print(f"Failed releases: {len(failures)}")

    for url in failures:
        print(f"  {url}")


if __name__ == "__main__":
    collect()
