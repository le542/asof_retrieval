
import hashlib
import json
from io import BytesIO
from pathlib import Path

import requests
from pypdf import PdfReader

OUTPUT_PATH = Path("data/processed/bls_documents.jsonl")

RELEASES = [
    {
        "url": "https://www.bls.gov/news.release/archives/cpi_08122025.pdf",
        "title": "Consumer Price Index - July 2025",
        "published_at": "2025-08-12T08:30:00-04:00",
    }
]

documents = []

for i, release in enumerate(RELEASES):
    url = release["url"]
    print(f"[{i + 1}/{len(RELEASES)}] Fetching: {url}")

    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        reader = PdfReader(BytesIO(response.content))

        body = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        ).strip()

        if not body:
            print("  Could not extract PDF text")
            continue

        doc_id = "bls_" + hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:12]

        document = {
            "doc_id": doc_id,
            "title": release["title"],
            "body": body,
            "source": "bls.gov",
            "source_type": "official",
            "url": url,
            "published_at": release["published_at"],
            "gdelt_seen_at": None,
        }

        documents.append(document)
        print(f"  Extracted {len(body)} characters")
        print(f"  PDF pages: {len(reader.pages)}")
        print(f"  Preview: {body[:250]}")

    except (requests.RequestException, Exception) as e:
        print(f"  Failed: {e}")

if documents:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(documents)} documents to {OUTPUT_PATH}")
else:
    print("\nNo documents retrieved. Existing output left unchanged.")
