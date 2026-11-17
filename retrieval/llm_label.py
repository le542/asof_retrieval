"""LLM relevance labeling of the judgment sheet (data/labels/judgments.csv) using Claude.

Usage (from the repo root; needs `ant auth login` or ANTHROPIC_API_KEY):
    python -m retrieval.llm_label --dry-run              # cost estimate, no API calls
    python -m retrieval.llm_label --batch                # label everything unlabeled (Batch API, 50% off)
    python -m retrieval.llm_label --qid KXCPI-25JUL      # one question, live (good for a spot check)

One API call per question or batch mode
Claude returns a 0/1/2 grade plus a one-line
reason for each doc (structured output, so the reply is always valid JSON).

Long documents are cut to the first --max-words words (default 1500). Official
releases lead with their headline numbers, so the start is what matters; the
prompt tells Claude the text may be truncated.
"""

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from retrieval.build_index import CORPUS_PATH
from retrieval.judgments import SHEET_PATH, read_sheet, write_sheet

# showing work behind testing for llm judging
# model id -> (input, output) USD per million tokens
MODELS = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
}

# Went with Sonnet 5.5 as default exceptionally cheaper 
# with almost exact same results as Opus in test run
DEFAULT_MODEL = "claude-sonnet-5-5"
TOKENS_PER_WORD = 2.3

SYSTEM_PROMPT = """\
You are labeling relevance judgments for an information retrieval evaluation.

The search engine helps an analyst forecast an economics prediction-market
question (from Kalshi). For each question it retrieves documents that were
published BEFORE the question's as_of time: official releases (FOMC
statements, BLS CPI and Employment Situation reports, BEA GDP and Personal
Income and Outlays reports) and New York Fed Liberty Street Economics posts.

Grade how useful each document is to an analyst answering the question at the
as_of time:

2 = Directly informative. The most recent release(s) of the indicator the
    question is about (e.g. the previous month's CPI report for a CPI
    question, the latest FOMC statement for a Fed decision question), or
    analysis focused specifically on that indicator's current trend.
1 = Useful background. About the same indicator or its direct drivers, but
    less directly: older superseded releases of the same indicator, or
    analysis substantially about the indicator or its drivers (e.g. inflation
    expectations or tariff pass-through for a CPI question).
0 = Not relevant. A different topic, or only passing mentions of the
    question's keywords.

Releases of a different indicator:
- Fed decision questions: CPI, PCE, jobs and GDP releases are inputs the Fed
  weighs, so they can be 1.
- CPI and core PCE questions: the two are both inflation measures, so a
  release of one can be 1 for the other.
- Otherwise a release of a different indicator is 0 (e.g. a jobs report for
  a CPI question), even if it contains a related number such as wage growth.

Rules:
- Judge relevance to the question, not whether the document points to the
  outcome that actually happened. Do not use any knowledge of what happened
  after the as_of time.
- Grade each document on its own; several documents can share a grade.
- Document text may be truncated; judge from what is shown.
- Give a grade and a short reason (one sentence) for every document id you
  are given, and only those ids."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "judgments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "grade": {"type": "integer", "enum": [0, 1, 2]},
                    "reason": {"type": "string"},
                },
                "required": ["doc_id", "grade", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["judgments"],
    "additionalProperties": False,
}


def load_bodies(path=CORPUS_PATH):
    bodies = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            bodies[doc["doc_id"]] = doc["body"].split()
    return bodies


def build_user_message(qid, rows, bodies, max_words):
    first = rows[0]
    parts = [
        f"Question ({qid}): {first['query']}",
        f"as_of: {first['as_of']}",
        f"\nGrade these {len(rows)} documents:\n",
    ]
    for r in rows:
        words = bodies[r["doc_id"]]
        text = " ".join(words[:max_words])
        if len(words) > max_words:
            text += f" [... truncated, {len(words) - max_words} more words]"
        parts.append(
            f'<document id="{r["doc_id"]}">\n'
            f"Title: {r['title']}\nPublished: {r['published_at']}\nSource: {r['source']}\n\n"
            f"{text}\n</document>\n"
        )
    return "\n".join(parts)

# Messages API parameters for one question
def request_params(model, qid, rows, bodies, max_words):
    return {
        "model": model,
        "max_tokens": 16000,
        "output_config": {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
        },
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": build_user_message(qid, rows, bodies, max_words)}],
    }

# take in grade and reason
def parse_judgments(qid, message, expected):
    if message.stop_reason == "refusal":
        raise RuntimeError(f"{qid}: request declined ({message.stop_details})")
    if message.stop_reason == "max_tokens":
        raise RuntimeError(f"{qid}: response hit max_tokens")
    text = next(b.text for b in message.content if b.type == "text")
    return {
        j["doc_id"]: (j["grade"], j["reason"])
        for j in json.loads(text)["judgments"]
        if j["doc_id"] in expected
    }

def label_question(client, model, qid, rows, bodies, max_words):
    response = client.beta.messages.create(
        **request_params(model, qid, rows, bodies, max_words),
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # re-run on a fallback model if the request is declined
    )
    return parse_judgments(qid, response, {r["doc_id"] for r in rows}), response.usage

def batch_state_path(sheet_path):
    return sheet_path.with_name(f".batch_{sheet_path.stem}.json")

def run_batch(client, args, todo, bodies, rows):
    """Submit all questions as one Message Batch (50% price), wait, and apply the results."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    state_path = batch_state_path(args.sheet)
    if state_path.exists():
        state = json.loads(state_path.read_text())
        print(f"resuming batch {state['batch_id']} (submitted earlier)")
    else:
        requests = [
            Request(custom_id=qid, params=MessageCreateParamsNonStreaming(
                **request_params(args.model, qid, qrows, bodies, args.max_words)))
            for qid, qrows in todo.items()
        ]
        batch = client.messages.batches.create(requests=requests)
        state = {"batch_id": batch.id, "model": args.model}
        state_path.write_text(json.dumps(state))
        print(f"submitted batch {batch.id} with {len(requests)} questions")

    while True:
        batch = client.messages.batches.retrieve(state["batch_id"])
        c = batch.request_counts
        print(f"  {time.strftime('%H:%M:%S')} {batch.processing_status}: "
              f"{c.succeeded} succeeded, {c.errored} errored, {c.processing} processing", flush=True)
        if batch.processing_status == "ended":
            break
        time.sleep(60)

    labeled, failed, in_tok, out_tok = 0, [], 0, 0
    for result in client.messages.batches.results(state["batch_id"]):
        qid = result.custom_id
        if qid not in todo:
            continue  # already labeled by an earlier partial apply
        if result.result.type != "succeeded":
            failed.append(f"{qid} ({result.result.type})")
            continue
        message = result.result.message
        try:
            judgments = parse_judgments(qid, message, {r["doc_id"] for r in todo[qid]})
        except (RuntimeError, json.JSONDecodeError) as e:
            failed.append(f"{qid} ({e})")
            continue
        in_tok += message.usage.input_tokens
        out_tok += message.usage.output_tokens
        for r in todo[qid]:
            if r["doc_id"] in judgments:
                grade, reason = judgments[r["doc_id"]]
                r["label"], r["labeler"], r["notes"] = str(grade), state["model"], reason
                labeled += 1

    write_sheet(rows, args.sheet)
    state_path.unlink()
    price_in, price_out = MODELS[state["model"]]
    cost = (in_tok * price_in + out_tok * price_out) / 1e6 / 2  # batch = 50% off
    n_rows = sum(len(v) for v in todo.values())
    print(f"labeled {labeled}/{n_rows} rows; {in_tok:,} input + {out_tok:,} output tokens "
          f"(~${cost:.2f} at batch price)")
    if failed:
        print(f"failed: {failed}")
    if failed or labeled < n_rows:
        print("Fill the gaps with a live run: re-run the same command without --batch.")


def main():
    parser = argparse.ArgumentParser(description="LLM relevance labeling")
    parser.add_argument("--sheet", type=Path, default=SHEET_PATH)
    parser.add_argument("--qid", nargs="+", help="only label these questions")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))
    parser.add_argument("--max-words", type=int, default=1500, help="words of each doc to send")
    parser.add_argument("--workers", type=int, default=4, help="parallel API calls")
    parser.add_argument("--relabel", action="store_true", help="redo rows previously labeled by same model")
    parser.add_argument("--dry-run", action="store_true", help="estimate cost, make no API calls")
    parser.add_argument("--batch", action="store_true",
                        help="use the Message Batches API: 50%% cheaper, results within ~1h (max 24h)")
    args = parser.parse_args()

    rows = read_sheet(args.sheet)
    if not rows:
        raise SystemExit(f"{args.sheet} is missing or empty; run `python -m retrieval.judgments sheet` first")
    bodies = load_bodies()

    def needs_label(r):
        if args.qid and r["qid"] not in args.qid:
            return False
        if not r["label"].strip():
            return True
        return args.relabel and r["labeler"] == args.model

    todo = defaultdict(list)
    for r in rows:
        if needs_label(r):
            todo[r["qid"]].append(r)
    if not todo:
        print("Nothing to label.")
        return

    n_rows = sum(len(v) for v in todo.values())
    est_in = sum(
        len(build_user_message(q, rs, bodies, args.max_words).split()) for q, rs in todo.items()
    ) * TOKENS_PER_WORD + len(todo) * len(SYSTEM_PROMPT.split()) * TOKENS_PER_WORD
    est_out = n_rows * 60
    price_in, price_out = MODELS[args.model]
    est_cost = (est_in * price_in + est_out * price_out) / 1e6 / (2 if args.batch else 1)
    print(f"{len(todo)} questions, {n_rows} rows to label with {args.model}"
          f"{' (batch)' if args.batch else ''}; "
          f"~{est_in / 1e6:.2f}M input tokens, est. cost ~${est_cost:.2f}")
    if args.dry_run:
        return

    import anthropic

    client = anthropic.Anthropic()
    if args.batch:
        run_batch(client, args, todo, bodies, rows)
        return

    labeled, failed, in_tok, out_tok = 0, [], 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(label_question, client, args.model, qid, qrows, bodies, args.max_words): qid
            for qid, qrows in todo.items()
        }
        for i, future in enumerate(as_completed(futures), start=1):
            qid = futures[future]
            try:
                results, usage = future.result()
            except (anthropic.APIError, RuntimeError, json.JSONDecodeError) as e:
                failed.append(qid)
                print(f"[{i}/{len(todo)}] {qid}: FAILED - {e}")
                continue
            in_tok += usage.input_tokens
            out_tok += usage.output_tokens
            for r in todo[qid]:
                if r["doc_id"] in results:
                    grade, reason = results[r["doc_id"]]
                    r["label"], r["labeler"], r["notes"] = str(grade), args.model, reason
                    labeled += 1
            missing = len(todo[qid]) - sum(r["doc_id"] in results for r in todo[qid])
            write_sheet(rows, args.sheet)
            print(f"[{i}/{len(todo)}] {qid}: labeled {len(results)}"
                  + (f", {missing} missing" if missing else ""))

    cost = (in_tok * price_in + out_tok * price_out) / 1e6
    print(f"labeled {labeled}/{n_rows} rows; {in_tok:,} input + {out_tok:,} output tokens (~${cost:.2f})")
    if failed or labeled < n_rows:
        print(f"failed questions: {failed}. Re-run the same command to retry unlabeled rows.")


if __name__ == "__main__":
    main()
