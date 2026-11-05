
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

RAW_DIR = Path("data/raw/bls")
OUTPUT_FILE = Path("data/processed/bls_documents.jsonl")
EASTERN = ZoneInfo("America/New_York")

SOURCE_PATTERN = re.compile(
    r"saved from url=\(\d+\)(https?://[^\s]+)"
)
RELEASE_PATTERN = re.compile(
    r"8:30\s*a\.m\.\s*\(ET\)\s+"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)
REPORT_PATTERN = re.compile(
    r"CONSUMER PRICE INDEX\s*[-–]\s*([A-Z]+\s+\d{4})",
    re.IGNORECASE,
)


def import_file(path):
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    content = soup.select_one("#bodytext .normalnews")
    if content is None:
        raise ValueError("Could not find CPI report content")

    first_pre = content.find("pre")
    if first_pre is None:
        raise ValueError("Could not find release header")

    header = first_pre.get_text(" ", strip=True)

    date_match = RELEASE_PATTERN.search(header)
    if not date_match:
        raise ValueError("Could not verify publication date")

    release_date = datetime.strptime(
        date_match.group(1), "%B %d, %Y"
    )

    published_at = release_date.replace(
        hour=8,
        minute=30,
        tzinfo=EASTERN,
    ).isoformat()

    report_match = REPORT_PATTERN.search(header)
    if not report_match:
        raise ValueError("Could not identify CPI reporting month")

    report_month = report_match.group(1).title()

    source_match = SOURCE_PATTERN.search(html)
    if not source_match:
        raise ValueError("Could not find original BLS URL")

    url = source_match.group(1)

    if urlparse(url).hostname != "www.bls.gov":
        raise ValueError("Unexpected source URL")

    for element in content.select(
        "script, style, nav, button"
    ):
        element.decompose()

    body = content.get_text("\n", strip=True)
    body = re.sub(r"\n{3,}", "\n\n", body)

    if len(body) < 500:
        raise ValueError("Extracted report is unexpectedly short")

    return {
        "doc_id": f"bls_cpi_{release_date:%Y%m%d}",
        "title": f"Consumer Price Index - {report_month}",
        "body": body,
        "source": "bls.gov",
        "source_type": "official",
        "url": url,
        "published_at": published_at,
        "published_at_verified": True,
        "gdelt_seen_at": None,
    }


def main():
    files = sorted(RAW_DIR.glob("*.html"))
    print(f"Found {len(files)} HTML files")

    documents = []
    failures = []

    for path in files:
        try:
            document = import_file(path)
            documents.append(document)
            print(
                f"OK: {document['title']} "
                f"({document['published_at']})"
            )
        except Exception as exc:
            failures.append((path.name, str(exc)))
            print(f"FAILED: {path.name}: {exc}")

    if failures or len(documents) != 8:
        print(
            f"\nExpected 8 valid reports; "
            f"got {len(documents)}."
        )
        print("Output not written. Fix the issues first.")
        return

    documents.sort(key=lambda d: d["published_at"])

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(documents)} documents to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
