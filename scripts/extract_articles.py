
import json
from pathlib import Path

import trafilatura

INPUT_PATH = Path("data/raw/gdelt_sample.json")
OUTPUT_PATH = Path("data/processed/documents.jsonl")

with INPUT_PATH.open("r", encoding="utf-8") as f:
    data = json.load(f)

articles = data.get("articles", [])
documents = []

for i, article in enumerate(articles):
    url = article.get("url")
    if not url:
        continue

    print(f"[{i + 1}/{len(articles)}] Fetching: {url}")

    try:
        downloaded = trafilatura.fetch_url(url)

        if not downloaded:
            print("  Could not download article")
            continue

        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
        )

        metadata = trafilatura.extract_metadata(
            downloaded,
            default_url=url,
        )

        if not text:
            print("  Could not extract text")
            continue

        document = {
            "doc_id": f"news_{i + 1:06d}",
            "title": article.get("title"),
            "body": text,
            "source": article.get("domain"),
            "source_type": "news",
            "url": url,
            "published_at": metadata.date if metadata else None,
            "gdelt_seen_at": article.get("seendate"),
        }

        documents.append(document)
        print(f"  Extracted {len(text)} characters")

    except Exception as e:
        print(f"  Error: {e}")

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    for document in documents:
        f.write(json.dumps(document, ensure_ascii=False) + "\n")

print(f"\nSuccessfully extracted {len(documents)} documents")
print(f"Saved to {OUTPUT_PATH}")
