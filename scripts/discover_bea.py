
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

CATEGORIES = {
    "gdp": "451",
    "pce": "476",
}


def parse_date(text):
    try:
        return datetime.strptime(text, "%B %d, %Y").date()
    except ValueError:
        return None


def main():
    session = requests.Session()
    releases = {}

    for release_type, category_id in CATEGORIES.items():
        print(f"\nDiscovering {release_type.upper()} releases...")

        for page in range(MAX_PAGES):
            print(f"Fetching archive page {page + 1}...")

            params = {
                "created_1": "All",
                "field_related_product_target_id": category_id,
                "title": "",
                "page": page,
            }

            response = session.get(ARCHIVE_URL, params=params, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            rows = soup.select("table tbody tr")

            if not rows:
                break

            page_dates = []
            new_count = 0

            for row in rows:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue

                release_date = parse_date(
                    cells[-1].get_text(" ", strip=True)
                )
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

                title = link.get_text(" ", strip=True)

                if release_type == "pce" and not title.lower().startswith(
                    "personal income and outlays"
                ):
                    continue

                releases[url] = {
                    "title": title,
                    "url": url,
                    "published_date": release_date.isoformat(),
                    "release_type": release_type,
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
        print(
            f"{release['published_date']} | "
            f"{release['release_type'].upper()} | "
            f"{release['title']}"
        )


if __name__ == "__main__":
    main()
