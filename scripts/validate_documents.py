
import json
from datetime import datetime, timezone
from pathlib import Path

INPUT_PATH = Path("data/processed/documents_clean.jsonl")

documents = []

with INPUT_PATH.open("r", encoding="utf-8") as f:
    for line in f:
        documents.append(json.loads(line))

print(f"Validating {len(documents)} documents...\n")

for doc in documents:
    title = doc.get("title", "Unknown")
    published = doc.get("published_at")
    seen = doc.get("gdelt_seen_at")

    issues = []

    if not doc.get("body"):
        issues.append("Missing article text")

    if not published:
        issues.append("Missing publication date")

    if published and seen:
        try:
            published_date = datetime.strptime(
                published, "%Y-%m-%d"
            ).date()

            seen_date = datetime.strptime(
                seen, "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc).date()

            if published_date > seen_date:
                issues.append(
                    "Publication date later than GDELT observation"
                )

        except ValueError:
            issues.append("Invalid timestamp format")

    print(f"Article: {title[:70]}")

    if issues:
        for issue in issues:
            print(f"  WARNING: {issue}")
    else:
        print("  No basic validation issues")

    print()
