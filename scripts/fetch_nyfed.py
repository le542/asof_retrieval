
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://libertystreeteconomics.newyorkfed.org"
OUTPUT = Path("data/processed/nyfed_documents.jsonl")

YEAR = 2025
REQUEST_DELAY = 1.5

session = requests.Session()

def fetch_html(url):
    response = session.get(url, timeout=25)
    response.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return BeautifulSoup(response.text, "html.parser")


def discover_articles(month):
    url = f"{BASE_URL}/{YEAR}/{month:02d}/"
    soup = fetch_html(url)

    articles = set()

    for link in soup.select("a[href]"):
        href = urljoin(url, link["href"])
        parsed = urlparse(href)
        parts = [p for p in parsed.path.split("/") if p]

        if (
            parsed.netloc == urlparse(BASE_URL).netloc
            and len(parts) == 3
            and parts[0] == str(YEAR)
            and parts[1] == f"{month:02d}"
        ):
            articles.add(
                f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/"
            )

    return sorted(articles)


def extract_article(url):
    soup = fetch_html(url)

    title_tag = soup.select_one("h1.ts-blog-article-title")
    body_tag = soup.select_one("div.ts-article-text")
    date_tag = soup.select_one(
        'meta[property="article:published_time"]'
    )

    if not title_tag or not body_tag or not date_tag:
        raise ValueError("Missing title, body, or publication date")

    title = title_tag.get_text(" ", strip=True)
    published_at = date_tag.get("content")

    datetime.fromisoformat(published_at.replace("Z", "+00:00"))

    # Work on a copy so the original page remains unchanged.
    body = BeautifulSoup(str(body_tag), "html.parser")

    for tag in body.select(
        "script, style, nav, .sharedaddy, "
        ".sd-sharing, .jp-relatedposts"
    ):
        tag.decompose()

    text = body.get_text(" ", strip=True)

    # Remove trailing site boilerplate when identifiable.
    for marker in [
        "You may also be interested in:",
        "Disclaimer",
        "Share this:",
    ]:
        match = re.search(re.escape(marker), text, re.IGNORECASE)
        if match:
            text = text[:match.start()].strip()

    text = re.sub(r"\s+", " ", text).strip()

    if len(text) < 500:
        raise ValueError("Article text unexpectedly short")

    doc_id = "nyfed_" + hashlib.sha256(
        url.encode("utf-8")
    ).hexdigest()[:12]

    return {
        "doc_id": doc_id,
        "title": title,
        "body": text,
        "source": "libertystreeteconomics.newyorkfed.org",
        "source_type": "economic_commentary",
        "url": url,
        "published_at": published_at,
        "published_at_verified": True,
    }


def main():
    all_urls = set()

    for month in range(1, 13):
        try:
            urls = discover_articles(month)
            all_urls.update(urls)
            print(f"{YEAR}-{month:02d}: {len(urls)} articles")
        except (requests.RequestException, ValueError) as exc:
            print(f"Archive failed for {month:02d}: {exc}")

    print(f"\nDiscovered {len(all_urls)} unique article URLs")

    documents = []

    for index, url in enumerate(sorted(all_urls), 1):
        try:
            document = extract_article(url)
            documents.append(document)
            print(f"[{index}/{len(all_urls)}] OK: {document['title']}")
        except (requests.RequestException, ValueError) as exc:
            print(f"[{index}/{len(all_urls)}] FAILED: {url}: {exc}")

    documents.sort(key=lambda doc: doc["published_at"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document, ensure_ascii=False) + "\n")

    print(f"\nSaved {len(documents)} documents to {OUTPUT}")


if __name__ == "__main__":
    main()
