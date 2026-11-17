"""Build the search indexes for the AsOf corpus.

Usage (from the repo root):
    python -m retrieval.build_index            # build if missing
    python -m retrieval.build_index --force    # rebuild from scratch
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

# constants
CORPUS_PATH = Path("data/processed/corpus.jsonl")
PYSERINI_INPUT_DIR = Path("data/pyserini_input")
INDEX_DIR = Path("indexes/lucene")
METADATA_PATH = Path("indexes/doc_metadata.json")
EMBEDDINGS_PATH = Path("indexes/passage_embeddings.npz")

# embedding model for semantic index
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
PASSAGE_WORDS = 150

METADATA_FIELDS = [
    "title",
    "source",
    "source_type",
    "release_type",
    "url",
    "published_at",
    "published_at_verified",
]

# load JSONL in list
def load_corpus(path=CORPUS_PATH):
    docs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                docs.append(json.loads(line))
    return docs

# convert into pyserini's JsonCollection format
def preprocess_corpus(docs, output_dir=PYSERINI_INPUT_DIR):
    if output_dir.exists():
        # clean up
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    with open(output_dir / "docs.jsonl", "w", encoding="utf-8") as out:
        for doc in docs:
            contents = f"{doc.get('title', '')}\n{doc.get('body', '')}".strip()
            out.write(json.dumps({"id": doc["doc_id"], "contents": contents}) + "\n")

# add metadata, need dates
def write_metadata(docs, path=METADATA_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        doc["doc_id"]: {field: doc.get(field) for field in METADATA_FIELDS}
        for doc in docs
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

# run pyserini like in mp1
def build_index(input_dir=PYSERINI_INPUT_DIR, index_dir=INDEX_DIR):
    if index_dir.exists():
        shutil.rmtree(index_dir)
    cmd = [
        sys.executable, "-m", "pyserini.index.lucene",
        "--collection", "JsonCollection",
        "--input", str(input_dir),
        "--index", str(index_dir),
        "--generator", "DefaultLuceneDocumentGenerator",
        "--threads", "1",
        "--storePositions", "--storeDocvectors", "--storeRaw",
    ]
    subprocess.run(cmd, check=True)

# embedding model can only read about 180 words, thus need to chunk
# prefix w/ title
def split_passages(doc, size=PASSAGE_WORDS):
    words = doc["body"].split()
    return [
        f"{doc['title']}. " + " ".join(words[i:i + size])
        for i in range(0, max(len(words), 1), size)
    ]

# embed passages, save vectors and respective docs
def build_dense_index(docs, path=EMBEDDINGS_PATH):
    import numpy as np
    from sentence_transformers import SentenceTransformer

    passage_texts, passage_doc_ids = [], []
    for doc in docs:
        for passage in split_passages(doc):
            passage_texts.append(passage)
            passage_doc_ids.append(doc["doc_id"])

    model = SentenceTransformer(EMBED_MODEL)
    # Normalized vectors, dot product is the cosine similarity.
    embeddings = model.encode(passage_texts, batch_size=64, normalize_embeddings=True,
                              show_progress_bar=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, embeddings=embeddings.astype(np.float32), doc_ids=np.array(passage_doc_ids))
    return len(passage_texts)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--force", action="store_true", help="rebuild even if the index exists")
    args = parser.parse_args()

    # skip if already built, unless --force
    if INDEX_DIR.exists() and any(INDEX_DIR.iterdir()) and not args.force:
        print(f"Index already exists at {INDEX_DIR}. Use --force to rebuild.")
        return

    docs = load_corpus(args.corpus)
    # duplicate id check
    ids = [d["doc_id"] for d in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("corpus contains duplicate doc_ids")

    preprocess_corpus(docs)
    write_metadata(docs)
    build_index()
    print(f"Indexed {len(docs)} documents -> {INDEX_DIR}")
    n_passages = build_dense_index(docs)
    print(f"Embedded {n_passages} passages -> {EMBEDDINGS_PATH}")


if __name__ == "__main__":
    main()
