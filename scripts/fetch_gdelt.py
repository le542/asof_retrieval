
import json
import time
from pathlib import Path
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

QUERIES = {
    "fed": '"Federal Reserve" "interest rates"',
    # "inflation": '"consumer price index" inflation',
    # "employment": '"unemployment rate" jobs',
    # "gdp": '"GDP" "economic growth"',
}

START_DATE = "20250701000000"
END_DATE = "20250731235959"

OUTPUT_DIR = Path("data/raw")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def fetch_with_retry(url, params, max_attempts=3):
    for attempt in range(max_attempts):
        response = requests.get(
            url,
            params=params,
            timeout=30,
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")

            if retry_after:
                try:
                    wait = float(retry_after)
                except ValueError:
                    retry_time = parsedate_to_datetime(retry_after)
                    wait = max(
                        0,
                        (
                            retry_time -
                            datetime.now(timezone.utc)
                        ).total_seconds(),
                    )
            else:
                wait = min(60 * (2 ** attempt), 240)
                wait += random.uniform(0, 5)

            if attempt == max_attempts - 1:
                raise RuntimeError(
                    "GDELT is still rate-limiting requests. "
                    "Stop and try again later."
                )

            print(f"Rate limited. Waiting {wait:.0f} seconds...")
            time.sleep(wait)
            continue

        response.raise_for_status()
        return response.json()

for category, query in QUERIES.items():
    print(f"\nFetching {category} articles...")

    params = {
        "query": query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": 50,
        "startdatetime": START_DATE,
        "enddatetime": END_DATE,
        "sort": "DateDesc",
    }

    try:
        data = fetch_with_retry(API_URL, params)
        articles = data.get("articles", [])

        output_path = OUTPUT_DIR / f"gdelt_{category}.json"

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Retrieved {len(articles)} articles")
        print(f"Saved to {output_path}")

    except (requests.RequestException, ValueError, RuntimeError) as e:
        print(f"Error fetching {category}: {e}")

    # Avoid sending requests too rapidly
    time.sleep(2)
