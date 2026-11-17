"""Build the relevance-judgment sheet and convert finished labels into qrels.

Usage (from the repo root):
python -m retrieval.judgments sheet    # -> data/labels/judgments.csv (one row per question/doc)
python -m retrieval.judgments qrels    # -> data/qrels.txt            (mp1 format: qid doc_id grade)

Full judging (default): every document published at or before a question's
as_of gets a row, the way Cranfield was judged. The corpus is small (131 docs),
so this is affordable and avoids pooling bias.

Rows are sorted by publish date (newest first), not by system rank, so a
labeler can't tell which system found what. Re-running `sheet` keeps labels
already filled in.

Grades:
    2 = directly informs the answer (e.g. the previous CPI release for a CPI question)
    1 = same indicator or its direct drivers (e.g. an older CPI release, a post on inflation expectations)
    0 = not relevant
Only grades > 0 are written to qrels; docs not listed count as 0, as in mp1.
"""

import argparse
import csv
import json
from pathlib import Path

from retrieval.build_index import CORPUS_PATH
from retrieval.search import SYSTEMS, load_queries, parse_time

QUERIES_PATH = Path("data/queries.jsonl")
SHEET_PATH = Path("data/labels/judgments.csv")
QRELS_PATH = Path("data/qrels.txt")
VALID_GRADES = {"0", "1", "2"}
SNIPPET_CHARS = 600

FIELDS = [
    "qid", "query", "as_of", "doc_id", "title", "published_at", "source",
    "snippet", "url", "label", "labeler", "notes",
]


def read_sheet(path):
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

# Write via a temp file in case of interruption
def write_sheet(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)

# check as_of for appropriate docs
def all_candidates(queries, docs):
    for q in queries:
        as_of = parse_time(q["as_of"])
        yield q, {
            doc_id: doc for doc_id, doc in docs.items()
            if parse_time(doc["published_at"]) <= as_of
        }

# kept for comparison
def pooled_candidates(queries, depth, systems):
    from retrieval.search import Retriever
    retriever = Retriever()
    for q in queries:
        pooled = {}
        for system in systems:
            for hit in retriever.search(q["query"], as_of=q["as_of"], system=system, k=depth):
                pooled.setdefault(hit["doc_id"], hit)
        yield q, pooled

def build_sheet(queries_path, sheet_path, pooled=False, depth=10, systems=None, qids=None):
    queries = load_queries(queries_path)
    if qids:
        queries = [q for q in queries if q["qid"] in qids]
    docs = {}
    with open(CORPUS_PATH, encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            docs[doc["doc_id"]] = doc

    # in case of rebuild
    existing = {(r["qid"], r["doc_id"]): r for r in read_sheet(sheet_path)}
    candidates = (pooled_candidates(queries, depth, systems or list(SYSTEMS)) if pooled
                  else all_candidates(queries, docs))

    rows = []
    for q, cands in candidates:
        for doc_id, hit in sorted(cands.items(), key=lambda kv: kv[1]["published_at"], reverse=True):
            old = existing.get((q["qid"], doc_id), {})
            rows.append({
                "qid": q["qid"],
                "query": q["query"],
                "as_of": q["as_of"],
                "doc_id": doc_id,
                "title": hit["title"],
                "published_at": hit["published_at"],
                "source": hit["source"],
                "snippet": " ".join(docs[doc_id]["body"].split())[:SNIPPET_CHARS],
                "url": hit["url"],
                "label": old.get("label", ""),
                "labeler": old.get("labeler", ""),
                "notes": old.get("notes", ""),
            })

    write_sheet(rows, sheet_path)
    kept = sum(1 for r in rows if r["label"])
    sizes = [sum(1 for r in rows if r["qid"] == q["qid"]) for q in queries]
    mode = f"pooled (depth {depth})" if pooled else "full judging"
    print(f"{mode}: {len(queries)} questions, {len(rows)} (question, doc) pairs "
          f"(per question: min {min(sizes)}, avg {len(rows) / len(queries):.1f}, max {max(sizes)}); "
          f"kept {kept} existing labels -> {sheet_path}")


def write_qrels(sheet_path, qrels_path, allow_unlabeled):
    rows = read_sheet(sheet_path)

    # safety checks
    if not rows:
        raise SystemExit(f"{sheet_path} is missing or empty; run `python -m retrieval.judgments sheet` first")

    invalid = [r for r in rows if r["label"].strip() and r["label"].strip() not in VALID_GRADES]
    if invalid:
        for r in invalid[:10]:
            print(f"  invalid label {r['label']!r}: {r['qid']} {r['doc_id']}")
        raise SystemExit(f"{len(invalid)} rows have labels other than 0/1/2")

    unlabeled = [r for r in rows if not r["label"].strip()]
    if unlabeled and not allow_unlabeled:
        qids = sorted({r["qid"] for r in unlabeled})
        raise SystemExit(f"{len(unlabeled)} rows across {len(qids)} questions are unlabeled "
                         f"(e.g. {qids[:3]}); finish labeling or pass --allow-unlabeled")

    qrels = [(r["qid"], r["doc_id"], r["label"].strip()) for r in rows
             if r["label"].strip() in ("1", "2")]
    qrels_path.parent.mkdir(parents=True, exist_ok=True)
    with open(qrels_path, "w", encoding="utf-8") as f:
        for qid, doc_id, grade in qrels:
            f.write(f"{qid} {doc_id} {grade}\n")

    labeled_qids = {r["qid"] for r in rows if r["label"].strip()}
    no_relevant = sorted(labeled_qids - {qid for qid, _, _ in qrels})
    print(f"wrote {len(qrels)} relevant judgments for {len(labeled_qids) - len(no_relevant)} "
          f"questions -> {qrels_path}" + (f" ({len(unlabeled)} unlabeled rows skipped)" if unlabeled else ""))
    if no_relevant:
        print(f"warning: {len(no_relevant)} questions have no relevant docs (NDCG undefined): {no_relevant}")


def main():
    parser = argparse.ArgumentParser(description="Relevance judgment sheet and qrels")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sheet", help="build/refresh the judgment sheet")
    s.add_argument("--queries", type=Path, default=QUERIES_PATH)
    s.add_argument("--out", type=Path, default=SHEET_PATH)
    s.add_argument("--qid", nargs="+", help="only these questions")
    s.add_argument("--pooled", action="store_true", help="TREC pooling instead of full judging (needs Java 21)")
    s.add_argument("--depth", type=int, default=10, help="with --pooled: top-k per system")
    s.add_argument("--systems", nargs="+", choices=list(SYSTEMS), help="with --pooled: systems to pool")

    q = sub.add_parser("qrels", help="convert the labeled sheet to mp1-style qrels")
    q.add_argument("--sheet", type=Path, default=SHEET_PATH)
    q.add_argument("--out", type=Path, default=QRELS_PATH)
    q.add_argument("--allow-unlabeled", action="store_true",
                   help="write qrels from partial labels (unlabeled rows are skipped)")

    args = parser.parse_args()
    if args.cmd == "sheet":
        build_sheet(args.queries, args.out, pooled=args.pooled, depth=args.depth,
                    systems=args.systems, qids=args.qid)
    else:
        write_qrels(args.sheet, args.out, args.allow_unlabeled)


if __name__ == "__main__":
    main()
