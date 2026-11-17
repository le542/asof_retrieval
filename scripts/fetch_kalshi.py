"""Fetch settled Kalshi economics markets and turn them into retrieval queries.

Run it:
python scripts/fetch_kalshi.py                  # 2025 events, as_of = market close
python scripts/fetch_kalshi.py --lead-hours 24  # as_of = 24h before market close

Kalshi's older events are archived and come from /historical/markets via public API

as_of defaults to the earliest market close in the event. Kalshi usually closes markets
just before the official release (e.g. 12:29 UTC for an 8:30 ET CPI release),
so the answering document is always after as_of.
"""

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API = "https://api.elections.kalshi.com/trade-api/v2"

# series that match the corpus (FOMC, BLS CPI/jobs, BEA GDP/PCE).
SERIES = {
    "KXFEDDECISION": "fed",
    "KXCPIYOY": "cpi",
    "KXCPI": "cpi",
    "KXPAYROLLS": "jobs",
    "KXU3": "jobs",
    "KXGDP": "gdp",
    "KXPCECORE": "pce",
}

CORPUS_PATH = Path("data/processed/corpus.jsonl")

# title prefix of the official release each topic's questions are about.
RELEASE_TITLES = {
    "fed": "Federal Reserve issues FOMC statement",
    "cpi": "Consumer Price Index",
    "jobs": "Employment Situation",
    "gdp": "Gross Domestic Product",
    "pce": "Personal Income and Outlays",
}

# Upper bound of corpus
COVERAGE_END = {
    "cpi": "2025-09-11T12:30:00Z",
}

def snap_before_release(query, releases):
    """Some markets close *after* the release (e.g. KXGDP-25JAN31 closed 13:32 UTC,
    release at 13:30). If a same-topic release falls in the 24h before as_of,
    move as_of to one minute before that release so the answer can't leak.
    
    This is rare, but used as a safegaurd"""
    as_of = parse_time(query["as_of"])
    recent = [t for t in releases.get(query["topic"], []) if as_of - timedelta(days=1) < t <= as_of]
    if recent:
        snapped = min(recent) - timedelta(minutes=1)
        query["as_of_original"] = query["as_of"]
        query["as_of"] = snapped.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return True
    return False

# return reason to drop the query given corpus coverage, or None to keep it.
# exclude after coverage end (upper bound of time)
def corpus_exclusion(query, releases):
    as_of = parse_time(query["as_of"])
    coverage_end = COVERAGE_END.get(query["topic"])
    if coverage_end and as_of > parse_time(coverage_end):
        return f"past corpus coverage for {query['topic']} (ends {coverage_end})"
    if not any(t <= as_of for t in releases.get(query["topic"], [])):
        return f"no {query['topic']} release in corpus before as_of"
    return None

# record official release
def load_release_times(corpus_path):
    releases = {topic: [] for topic in RELEASE_TITLES}
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            for topic, prefix in RELEASE_TITLES.items():
                if doc["title"].startswith(prefix):
                    releases[topic].append(parse_time(doc["published_at"]))
    return releases

# api call
def get(path, **params):
    for attempt in range(5):
        resp = requests.get(f"{API}/{path}", params=params, timeout=30)
        if resp.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()

# allows pagination through calls
def paginate(path, key, **params):
    cursor = None
    while True:
        data = get(path, limit=200, cursor=cursor, **params) if cursor else get(path, limit=200, **params)
        yield from data.get(key, [])
        cursor = data.get("cursor")
        if not cursor:
            return

def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def fetch_event_markets(event_ticker):
    """Markets for an event: live endpoint first, then the historical archive."""
    markets = list(paginate("markets", "markets", event_ticker=event_ticker))
    if not markets:
        markets = list(paginate("historical/markets", "markets", event_ticker=event_ticker))
    return markets

# manually normalize title
def clean_title(title):
    title = title.replace("**", "")
    # Kalshi words the "no change" Fed market as "Hike rates by 0bps".
    title = title.replace("Hike rates by 0bps", "maintain rates")
    return " ".join(title.split())

def build_query(series, topic, event, markets, lead):
    settled = [m for m in markets if m.get("result") in ("yes", "no")]
    if not settled:
        return None
    rep = max(settled, key=lambda m: float(m.get("volume_fp") or 0))
    close = min(parse_time(m["close_time"]) for m in settled)
    winners = [m.get("yes_sub_title") or m.get("subtitle") for m in settled if m["result"] == "yes"]
    return {
        "qid": event["event_ticker"],
        "query": clean_title(rep["title"]),
        "market_title": rep["title"],
        "as_of": (close - lead).isoformat().replace("+00:00", "Z"),
        "series": series,
        "topic": topic,
        "event_title": event["title"],
        "representative_market": rep["ticker"],
        "close_time": close.isoformat().replace("+00:00", "Z"),
        "outcome": rep.get("expiration_value"),
        "yes_outcomes": winners,
        "num_markets": len(settled),
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch settled Kalshi economics markets as queries")
    parser.add_argument("--year", type=int, default=2025, help="keep events whose markets close in this year")
    parser.add_argument("--lead-hours", type=float, default=0.0, help="set as_of this many hours before close")
    parser.add_argument("--raw-out", type=Path)
    parser.add_argument("--queries-out", type=Path, default=Path("data/queries.jsonl"))
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH,
                        help="drop queries the corpus can't support (see COVERAGE_END)")
    parser.add_argument("--keep-all", action="store_true", help="skip the corpus coverage filter")
    args = parser.parse_args()
    raw_out = args.raw_out or Path(f"data/raw/kalshi_markets_{args.year}.json")
    lead = timedelta(hours=args.lead_hours)

    raw, queries = [], []
    for series, topic in SERIES.items():
        events = list(paginate("events", "events", series_ticker=series, status="settled"))
        kept = 0
        for event in events:
            markets = fetch_event_markets(event["event_ticker"])
            time.sleep(0.1)
            if not markets or min(parse_time(m["close_time"]) for m in markets).year != args.year:
                continue
            raw.append({"series": series, "event": event, "markets": markets})
            query = build_query(series, topic, event, markets, lead)
            if query:
                queries.append(query)
                kept += 1
        print(f"{series:14} {len(events):3} settled events, {kept:3} in {args.year}")

    queries.sort(key=lambda q: (q["as_of"], q["qid"]))

    excluded = []
    if not args.keep_all:
        releases = load_release_times(args.corpus)
        for q in queries:
            if snap_before_release(q, releases):
                print(f"  as_of moved before release: {q['qid']} {q['as_of_original']} -> {q['as_of']}")
        kept_queries = []
        for q in queries:
            reason = corpus_exclusion(q, releases)
            if reason:
                excluded.append({**q, "excluded_reason": reason})
            else:
                kept_queries.append(q)
        queries = kept_queries
        excluded_out = args.queries_out.with_name(args.queries_out.stem + "_excluded.jsonl")
        with open(excluded_out, "w", encoding="utf-8") as f:
            for q in excluded:
                f.write(json.dumps(q) + "\n")
                print(f"  excluded {q['qid']:20} {q['excluded_reason']}")
        print(f"excluded {len(excluded)} queries -> {excluded_out}")

    raw_out.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_out, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=1)
    args.queries_out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.queries_out, "w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q) + "\n")
    print(f"wrote {len(queries)} queries -> {args.queries_out}, raw markets -> {raw_out}")


if __name__ == "__main__":
    main()
