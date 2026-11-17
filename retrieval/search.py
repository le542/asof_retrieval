"""Point-in-time retrieval systems over the AsOf Lucene index.

Main point:
`as_of` is enforced for every system: no document with published_at > as_of
is ever returned, and no future document influences the ranking (RM3 learns
its expansion terms only from documents before as_of). Pass as_of=None only
for an unfiltered (leaky) baseline.

Known limitation: 
BM25's corpus statistics (IDF, average doc length) come from
the whole index, including documents after as_of.

Systems (see SYSTEMS), each testing one idea:
  bm25        Baseline: Lucene BM25 keyword matching (k1, b)
  bm25_decay  Recency: BM25 score * 0.5 ** (age_days / half_life_days), age
              measured from as_of (or from the newest doc if as_of is None)
  rm3         Query expansion: RM3 pseudo-relevance feedback on top of BM25
  hybrid      Meaning: BM25 fused with semantic (embedding) search using
              reciprocal rank fusion, score = sum of 1 / (rrf_k + rank)
Run it:
python -m retrieval.search "fed rate cut september" --as-of 2025-09-10
python -m retrieval.search --queries queries.jsonl --system bm25 --run runs/bm25.txt
(queries.jsonl lines: {"qid": "...", "query": "...", "as_of": "2025-09-10T00:00:00Z"})
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from retrieval.build_index import EMBED_MODEL, EMBEDDINGS_PATH, INDEX_DIR, METADATA_PATH

# systems w/ hyperparameters
SYSTEMS = {
    "bm25": {"k1": 0.9, "b": 0.4},
    "bm25_decay": {"k1": 0.9, "b": 0.4, "half_life_days": 30.0},
    "rm3": {"k1": 0.9, "b": 0.4, "fb_terms": 10, "fb_docs": 10, "original_query_weight": 0.5},
    "hybrid": {"k1": 0.9, "b": 0.4, "rrf_k": 60},
}

# date regex
_DATE_TOKENS = re.compile(
    r"\b(?:(?:19|20)\d{2}|q[1-4]|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|"
    r"july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
    re.IGNORECASE,
)

# Strip month names, quarters and years from a contract question.
# Kalshi questions are full of dates
def clean_query(query):
    return " ".join(_DATE_TOKENS.sub(" ", query).split())

# Parse an ISO date/datetime
def parse_time(value):
    if value is None or isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Retriever:
    def __init__(self, index_dir=INDEX_DIR, metadata_path=METADATA_PATH):
        # Imported in class and not at top of file (heavy)
        # pyserini starts a JVM (needs Java 21)
        from pyserini.index.lucene import LuceneIndexReader
        from pyserini.search.lucene import LuceneSearcher

        self.searcher = LuceneSearcher(str(index_dir))
        self.reader = LuceneIndexReader(str(index_dir))  # term counts per doc, for RM3
        with open(metadata_path, encoding="utf-8") as f:
            self.metadata = json.load(f)
        self.published = {
            doc_id: parse_time(meta["published_at"]) for doc_id, meta in self.metadata.items()
        }
        self.num_docs = self.searcher.num_docs
        self._dense = None  # (model, passage embeddings, passage doc ids), loaded on first hybrid search

    def _bm25_search(self, query, as_of):
        """BM25 scores for every doc published at or before as_of."""
        hits = self.searcher.search(query, k=self.num_docs)
        return {
            hit.docid: hit.score for hit in hits
            if as_of is None or self.published[hit.docid] <= as_of
        }

    def search(self, query, as_of=None, system="bm25", k=10, clean=True, **overrides):
        """
        Return the top-k documents published at or before `as_of`.
        """
        if system not in SYSTEMS:
            raise ValueError(f"unknown system {system!r}; choose from {list(SYSTEMS)}")
        params = {**SYSTEMS[system], **overrides}
        as_of = parse_time(as_of)
        if clean:
            query = clean_query(query) or query
        # every system starts from BM25
        self.searcher.set_bm25(k1=params["k1"], b=params["b"])
        # doc_id -> BM25 score, future docs already removed
        bm25_scores = self._bm25_search(query, as_of)

        # other systems
        if system == "hybrid":
            results = self._fuse(query, bm25_scores, as_of, params["rrf_k"])
        elif system == "rm3":
            results = self._rm3(query, bm25_scores, as_of, params)
        else:
            # bm25 keeps its score; bm25_decay discounts older docs
            reference = as_of or max(self.published.values())
            results = []
            for doc_id, base_score in bm25_scores.items():
                score = base_score
                if system == "bm25_decay":
                    age_days = max((reference - self.published[doc_id]).total_seconds() / 86400.0, 0.0)
                    score *= 0.5 ** (age_days / params["half_life_days"])
                results.append((doc_id, score, base_score))

        results.sort(key=lambda r: r[1], reverse=True)
        # each hit is a dict with rank, doc_id, score, base_score and doc metadata.
        return [
            {
                "rank": rank,
                "doc_id": doc_id,
                "score": score,
                "base_score": base_score,
                **self.metadata[doc_id],
            }
            for rank, (doc_id, score, base_score) in enumerate(results[:k], start=1)
        ]

    # hand rolled RM3 to filter feedback
    def _rm3(self, query, bm25_scores, as_of, params):
        """RM3 pseudo-relevance feedback, using only feedback docs from before as_of.

        Pyserini's built-in RM3 (searcher.set_rm3) picks its feedback docs from the
        whole index, so documents published after as_of would shape the expanded
        query. Here the feedback docs are the top BM25 docs *after* the as_of filter."""
        from pyserini.search.lucene.querybuilder import JBooleanClauseOccur, JBoostQuery, JTerm, JTermQuery, get_boolean_query_builder

        feedback = sorted(bm25_scores, key=bm25_scores.get, reverse=True)[:params["fb_docs"]]
        if not feedback:
            return [(doc_id, score, score) for doc_id, score in bm25_scores.items()]

        total = sum(bm25_scores[d] for d in feedback)
        relevance = defaultdict(float)
        for doc_id in feedback:
            term_counts = self.reader.get_document_vector(doc_id)
            doc_len = sum(term_counts.values())
            for term, count in term_counts.items():
                if term.isalpha(): # skip numbers, the release tables are full of them
                    relevance[term] += (count / doc_len) * (bm25_scores[doc_id] / total)

        top_terms = sorted(relevance, key=relevance.get, reverse=True)[:params["fb_terms"]]
        expansion_total = sum(relevance[t] for t in top_terms)
        original = Counter(self.reader.analyze(query))  # same stemming as the index
        w = params["original_query_weight"]
        weights = defaultdict(float)
        for term, count in original.items():
            weights[term] += w * count / sum(original.values())
        for term in top_terms:
            weights[term] += (1 - w) * relevance[term] / expansion_total

        # Terms are already stemmed, so build term queries directly
        builder = get_boolean_query_builder()
        for term, weight in weights.items():
            builder.add(JBoostQuery(JTermQuery(JTerm("contents", term)), weight), JBooleanClauseOccur.should.value)
        expanded = self._bm25_search(builder.build(), as_of)
        return [(doc_id, score, bm25_scores.get(doc_id, 0.0)) for doc_id, score in expanded.items()]

    # semantic scoring
    def _dense_scores(self, query):
        if self._dense is None:
            import numpy as np
            from sentence_transformers import SentenceTransformer

            data = np.load(EMBEDDINGS_PATH)
            self._dense = (SentenceTransformer(EMBED_MODEL), data["embeddings"], data["doc_ids"].tolist())
        model, embeddings, passage_doc_ids = self._dense

        query_vec = model.encode([query], normalize_embeddings=True)[0]
        similarities = embeddings @ query_vec  # vectors are normalized, so dot product = cosine
        best = {}
        for doc_id, sim in zip(passage_doc_ids, similarities):
            if sim > best.get(doc_id, -1.0):
                best[doc_id] = float(sim)
        return best

    # rank fusion of BM25 and semantic ranking
    def _fuse(self, query, bm25_scores, as_of, rrf_k):
        dense = self._dense_scores(query)
        dense_ranked = sorted(
            (d for d in dense if as_of is None or self.published[d] <= as_of),
            key=dense.get, reverse=True,
        )
        bm25_ranked = sorted(bm25_scores, key=bm25_scores.get, reverse=True)

        fused = defaultdict(float)
        for ranking in (bm25_ranked, dense_ranked):
            for rank, doc_id in enumerate(ranking, start=1):
                fused[doc_id] += 1.0 / (rrf_k + rank)
        return [(doc_id, score, bm25_scores.get(doc_id, 0.0)) for doc_id, score in fused.items()]

    def run_queries(self, queries, system="bm25", k=10, clean=True, **overrides):
        return {
            q["qid"]: self.search(q["query"], as_of=q.get("as_of"), system=system, k=k,
                                  clean=clean, **overrides)
            for q in queries
        }

# check and count no returned doc was published after its query's as_of
def check_no_leakage(retriever, results, queries):
    as_of_by_qid = {q["qid"]: parse_time(q.get("as_of")) for q in queries}
    violations = 0
    for qid, hits in results.items():
        as_of = as_of_by_qid.get(qid)
        if as_of is None:
            continue
        for hit in hits:
            if retriever.published[hit["doc_id"]] > as_of:
                violations += 1
                print(f"LEAK: query {qid} returned {hit['doc_id']} ({hit['published_at']}) > {as_of}")
    return violations

def load_queries(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]

# standard TREC run format
def write_trec_run(results, path, tag):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for qid, hits in results.items():
            for hit in hits:
                f.write(f"{qid} Q0 {hit['doc_id']} {hit['rank']} {hit['score']:.6f} {tag}\n")


def main():
    parser = argparse.ArgumentParser(description="AsOf point-in-time search")
    parser.add_argument("query", nargs="?", help="ad-hoc query text")
    parser.add_argument("--as-of", help="ISO date/datetime cutoff (bare dates = 00:00 UTC)")
    parser.add_argument("--system", default="bm25", choices=list(SYSTEMS))
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--queries", help="JSONL file of {qid, query, as_of} for batch mode")
    parser.add_argument("--run", help="write a TREC run file (batch mode)")
    parser.add_argument("--no-clean", action="store_true", help="keep dates in the query text")
    args = parser.parse_args()

    retriever = Retriever()
    clean = not args.no_clean

    if args.queries:
        queries = load_queries(args.queries)
        results = retriever.run_queries(queries, system=args.system, k=args.k, clean=clean)
        leaks = check_no_leakage(retriever, results, queries)
        print(f"{len(queries)} queries, {leaks} leakage violations")
        if args.run:
            write_trec_run(results, args.run, tag=args.system)
            print(f"wrote {args.run}")
        return

    if not args.query:
        parser.error("give a query or --queries FILE")
    for hit in retriever.search(args.query, as_of=args.as_of, system=args.system, k=args.k,
                                clean=clean):
        print(f"{hit['rank']:>2}. {hit['score']:7.3f}  {hit['published_at'][:10]}  "
              f"[{hit['source']}] {hit['title'][:80]}")


if __name__ == "__main__":
    main()
