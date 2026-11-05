
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

EASTERN = ZoneInfo("America/New_York")

REPORTS = {
    "cpi": {
        "folder": Path("data/raw/bls"),
        "output": Path("data/processed/bls_documents.jsonl"),
        "expected": 8, # CHANGE THIS DEPENDING ON HOW MANY DOCS YOU IMPORT
        "heading": re.compile(
            r"CONSUMER PRICE INDEX\s*[-–]\s*([A-Z]+\s+\d{4})",
            re.IGNORECASE,
        ),
    },
    "employment": {
        "folder": Path("data/raw/bls_employment"),
        "output": Path("data/processed/bls_employment_documents.jsonl"),
        "expected": 11, # CHANGE THIS DEPENDING ON HOW MANY DOCS YOU IMPORT
        "heading": re.compile(
            r"THE EMPLOYMENT SITUATION\s*[-–]{1,2}\s*([A-Z]+\s+\d{4})",
            re.IGNORECASE,
        ),
    },
}

SOURCE_PATTERN = re.compile(
    r"saved from url=\(\d+\)(https?://[^\s]+)",
    re.IGNORECASE,
)

RELEASE_PATTERN = re.compile(
    r"8:30\s*a\.m\.\s*\(ET\)\s+"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    re.IGNORECASE,
)


def import_file(path, report_type):
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    content = soup.select_one("#bodytext .normalnews")
    if content is None:
        raise ValueError("Could not find report content")

    first_pre = content.find("pre")
    if first_pre is None:
        raise ValueError("Could not find release header")

    header = first_pre.get_text(" ", strip=True)

    date_match = RELEASE_PATTERN.search(header)
    if not date_match:
        raise ValueError("Could not verify publication date")

    release_date = datetime.strptime(date_match.group(1), "%B %d, %Y")

    if release_date.year != 2025:
        raise ValueError("Publication date is outside 2025")

    published_at = release_date.replace(
        hour=8,
        minute=30,
        tzinfo=EASTERN,
    ).isoformat()

    report_match = REPORTS[report_type]["heading"].search(header)
    if not report_match:
        raise ValueError("Could not identify reporting month")

    report_month = report_match.group(1).title()

    source_match = SOURCE_PATTERN.search(html)
    if not source_match:
        raise ValueError("Could not find original BLS URL")

    url = source_match.group(1)

    if urlparse(url).hostname != "www.bls.gov":
        raise ValueError("Unexpected source URL")

    expected_prefix = (
        "cpi_" if report_type == "cpi" else "empsit_"
    )
    if expected_prefix not in url:
        raise ValueError("Source URL does not match report type")

    for element in content.select("script, style, nav, button"):
        element.decompose()

    body = content.get_text("\n", strip=True)
    body = re.sub(r"\n{3,}", "\n\n", body)

    if len(body) < 500:
        raise ValueError("Extracted report is unexpectedly short")

    title_prefix = (
        "Consumer Price Index"
        if report_type == "cpi"
        else "Employment Situation"
    )

    return {
        "doc_id": f"bls_{report_type}_{release_date:%Y%m%d}",
        "title": f"{title_prefix} - {report_month}",
        "body": body,
        "source": "bls.gov",
        "source_type": "official",
        "url": url,
        "published_at": published_at,
        "published_at_verified": True,
        "gdelt_seen_at": None,
    }


def import_reports(report_type):
    config = REPORTS[report_type]
    files = sorted(config["folder"].glob("*.html"))

    print(f"\nImporting {report_type}: found {len(files)} HTML files")

    documents = []
    failures = []

    for path in files:
        try:
            document = import_file(path, report_type)
            documents.append(document)
            print(f"OK: {document['title']} ({document['published_at']})")
        except Exception as exc:
            failures.append((path.name, str(exc)))
            print(f"FAILED: {path.name}: {exc}")

    if failures or len(documents) != config["expected"]:
        print(
            f"Expected {config['expected']} valid {report_type} reports; "
            f"got {len(documents)}."
        )
        print("Output not written.")
        return

    if len({doc["doc_id"] for doc in documents}) != len(documents):
        print("Duplicate publication dates found. Output not written.")
        return

    documents.sort(key=lambda doc: doc["published_at"])

    config["output"].parent.mkdir(parents=True, exist_ok=True)

    with config["output"].open("w", encoding="utf-8") as f:
        for document in documents:
            f.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"Saved {len(documents)} documents to {config['output']}")


if __name__ == "__main__":
    import_reports("cpi")
    import_reports("employment")
