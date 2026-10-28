
import hashlib
import json
from pathlib import Path

INPUT_PATH = Path("data/processed/documents.jsonl")
OUTPUT_PATH = Path("data/processed/documents_clean.jsonl")

seen_hashes = set()
clean_documents = []

with INPUT_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        document = json.loads(line)

        body = document.get("body", "")

        # Normalize whitespace before hashing
        normalized_body = " ".join(body.split())

        # Compute a fingerprint for the article text
        content_hash = hashlib.sha256(
            normalized_body.encode("utf-8")
        ).hexdigest()

        if content_hash in seen_hashes:
            print(f"Duplicate skipped: {document['title']}")
            continue

        seen_hashes.add(content_hash)
        clean_documents.append(document)

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

with OUTPUT_PATH.open("w", encoding="utf-8") as f:
    for document in clean_documents:
        f.write(json.dumps(document, ensure_ascii=False) + "\n")

print(f"\nUnique documents: {len(clean_documents)}")
print(f"Saved to {OUTPUT_PATH}")