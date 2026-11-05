
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.bea.gov"
ARCHIVE_URL = f"{BASE_URL}/news/archive"

START_YEAR = 2025
END_YEAR = 2025

OUTPUT_PATH = Path("data/raw/bea_releases_2025.json")

session = requests.Session()
session.headers.update({
    "User-Agent": "AsOfRetrieval/0.1 (academic research)"
})

releases = {}
page = 0
MAX_PAGES = 30

while page < MAX_PAGES:
    print(f"Fetching BEA archive page {page + 1}...")

    params = {
        "created_1": "All",
        "field_related_product_target_id": "451",
        "title": "",
        "page": page,
    }

    try:
        response = session.get(
            ARCHIVE_URL,
            params=params,
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        break

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.select("table tbody tr")

    if not rows:
        print("No archive rows found. Stopping.")
        break

    new_count = 0

    for row in rows:
        link = row.find("a", href=True)

        if not link:
            continue

        title = link.get_text(" ", strip=True)
        url = urljoin(BASE_URL, link["href"])
        parsed = urlparse(url)

        if parsed.netloc not in ("bea.gov", "www.bea.gov"):
            continue

        if "/news/" not in parsed.path:
            continue

        cells = row.find_all("td")

        if len(cells) < 2:
            continue

        date_text = cells[-1].get_text(" ", strip=True)

        try:
            release_date = datetime.strptime(
                date_text,
                "%B %d, %Y",
            ).date()
        except ValueError:
            continue

        if not START_YEAR <= release_date.year <= END_YEAR:
            continue

        if url in releases:
            continue

        releases[url] = {
            "title": title,
            "url": url,
            "published_date": release_date.isoformat(),
        }

        new_count += 1

    print(f"Found {new_count} new 2025 GDP releases")

    # Stop after reaching archive pages entirely
    # older than the requested year.
    page_dates = []

    for row in rows:
        cells = row.find_all("td")

        if len(cells) < 2:
            continue

        try:
            date = datetime.strptime(
                cells[-1].get_text(" ", strip=True),
                "%B %d, %Y",
            ).date()
            page_dates.append(date)
        except ValueError:
            pass

    if page_dates and max(page_dates).year < START_YEAR:
        break

    page += 1
    time.sleep(1)

results = sorted(
    releases.values(),
    key=lambda item: item["published_date"],
)

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nTotal discovered releases: {len(results)}")
print(f"Saved to {OUTPUT_PATH}")

for release in results:
    print(
        release["published_date"],
        "|",
        release["title"],
    )
