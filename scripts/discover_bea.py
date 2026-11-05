
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ARCHIVE_URL = "https://www.bea.gov/news/archive"
OUTPUT_PATH = Path("data/raw/bea_releases_2025.json")

START_YEAR = 2025
END_YEAR = 2025
MAX_PAGES = 30

def parse_date(text):
    try:
        return datetime.strptime(text, "%B %d, %Y").date()
    except ValueError:
        return None

def main():
    session = requests.Session()

    releases = {}

    for page in range(MAX_PAGES):
        print(f"Fetching BEA archive page {page + 1}...")

        params = {
            "created_1": "All", # all dates
            "field_related_product_target_id": "451", # 451 is GDP
            "title": "",
            "page": page,
        }

        try:
            response = session.get(ARCHIVE_URL, params=params, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"Request failed: {exc}")
            break

        soup = BeautifulSoup(response.text, "html.parser")
        rows = soup.select("table tbody tr")

        if not rows:
            print("No archive rows found.")
            break

        page_dates = []
        new_count = 0

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue

            release_date = parse_date(cells[-1].get_text(" ", strip=True))
            if release_date is None:
                continue

            page_dates.append(release_date)

            if not START_YEAR <= release_date.year <= END_YEAR:
                continue

            link = row.find("a", href=True)
            if link is None:
                continue

            url = urljoin(ARCHIVE_URL, link["href"])
            parsed = urlparse(url)

            if parsed.hostname not in ("bea.gov", "www.bea.gov"):
                continue

            if "/news/" not in parsed.path or url in releases:
                continue

            releases[url] = {
                "title": link.get_text(" ", strip=True),
                "url": url,
                "published_date": release_date.isoformat(),
            }
            new_count += 1

        print(f"Found {new_count} new releases")

        if page_dates and max(page_dates).year < START_YEAR:
            break

        time.sleep(1)

    results = sorted(
        releases.values(),
        key=lambda release: release["published_date"],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nFound {len(results)} releases. Saved to {OUTPUT_PATH}")

    for release in results:
        print(f"{release['published_date']} | {release['title']}")


if __name__ == "__main__":
    main()
