
import json
from datetime import datetime
from pathlib import Path

INPUT_FILES = [
    Path("data/processed/fed_documents.jsonl"),
    Path("data/processed/bea_documents.jsonl"),
    Path("data/processed/bls_documents.jsonl"),
    Path("data/processed/nyfed_documents.jsonl")
]

OUTPUT_PATH = Path("data/processed/corpus.jsonl")

REQUIRED_FIELDS = [
    "doc_id",
    "title",
    "body",
    "source",
    "source_type",
    "url",
    "published_at",
]

documents = []
seen_ids = set()

for input_path in INPUT_FILES:
    print(f"\nReading {input_path}...")

    if not input_path.exists():
        print("  File not found. Skipping.")
        continue

    with input_path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            if not line.strip():
                continue

            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                print(f"  Invalid JSON on line {line_number}. Skipping.")
                continue

            missing = [
                field for field in REQUIRED_FIELDS
                if not doc.get(field)
            ]

            if missing:
                print(
                    f"  Missing fields on line {line_number}: "
                    f"{missing}. Skipping."
                )
                continue

            try:
                published = datetime.fromisoformat(
                    doc["published_at"]
                )

                if published.tzinfo is None:
                    raise ValueError("Timestamp lacks timezone")

            except ValueError:
                print(
                    f"  Invalid publication timestamp on "
                    f"line {line_number}. Skipping."
                )
                continue

            if doc["doc_id"] in seen_ids:
                print(f"  Duplicate ID skipped: {doc['doc_id']}")
                continue

            seen_ids.add(doc["doc_id"])
            documents.append(doc)

    print(f"  Total accepted so far: {len(documents)}")

# Sort documents by their publication timestamps
documents.sort(
    key=lambda doc: datetime.fromisoformat(
        doc["published_at"]
    )
)

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    for doc in documents:
        f.write(json.dumps(doc, ensure_ascii=False) + "\n")

print("\n" + "=" * 50)
print("CORPUS SUMMARY")
print("=" * 50)

print(f"Total documents: {len(documents)}")

source_counts = {}

for doc in documents:
    source = doc["source"]
    source_counts[source] = source_counts.get(source, 0) + 1

for source, count in sorted(source_counts.items()):
    print(f"  {source}: {count}")

if documents:
    print("\nEarliest document:", documents[0]["published_at"])
    print("Latest document:", documents[-1]["published_at"])

print(f"\nSaved to {OUTPUT_PATH}")
