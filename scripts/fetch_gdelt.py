
import json
from pathlib import Path

import requests

# GDELT DOC 2.0 API
API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Search for news about the Federal Reserve
params = {
    "query": '"Federal Reserve" "interest rates"',
    "mode": "ArtList",
    "format": "json",
    "maxrecords": 10,
    "startdatetime": "20250701000000",
    "enddatetime": "20250731235959",
}

print("Fetching articles from GDELT...")

response = requests.get(API_URL, params=params, timeout=30)
response.raise_for_status()

data = response.json()

articles = data.get("articles", [])

print(f"Retrieved {len(articles)} articles")

# Save the raw API response
output_path = Path("data/raw/gdelt_sample.json")
output_path.parent.mkdir(parents=True, exist_ok=True)

with output_path.open("w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Saved results to {output_path}")

# Preview article metadata
for article in articles[:5]:
    print()
    print("Title:", article.get("title"))
    print("Date:", article.get("seendate"))
    print("URL:", article.get("url"))
