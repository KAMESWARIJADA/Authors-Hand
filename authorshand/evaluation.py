"""Evaluation suite for summaries, grounding and retrieval."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from .summarizer import _as_text


def rouge(candidate: str, reference: str) -> dict:
    try:
        from rouge_score import rouge_scorer
        sc = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
        r = sc.score(reference, candidate)
        return {k: round(v.fmeasure, 4) for k, v in r.items()}
    except ImportError:  # minimal unigram fallback
        c, r = set(candidate.lower().split()), set(reference.lower().split())
        p = len(c & r) / max(1, len(c))
        rc = len(c & r) / max(1, len(r))
        return {"rouge1": round(2 * p * rc / max(1e-9, p + rc), 4), "rouge2": None, "rougeL": None}


def field_coverage(summary: dict) -> float:
    """Share of the 9 structured fields that were filled."""
    f = summary["fields"]
    return round(np.mean([bool(_as_text(v).strip()) for v in f.values()]), 3)


def evaluate_summaries(summarizer, corpus: list[dict]) -> pd.DataFrame:
    """corpus items: {title, text, reference_summary}"""
    rows = []
    for item in corpus:
        t0 = time.time()
        s = summarizer.summarize(item["text"], title=item["title"])
        cand = s["executive_summary"]
        r = rouge(cand, item["reference_summary"])
        rows.append({"paper": item["title"][:45], **r,
                     "faithfulness": s["faithfulness"], "field_coverage": field_coverage(s),
                     "exec_words": len(cand.split()), "compression": s["compression"], "latency_s": round(time.time() - t0, 2)})
    df = pd.DataFrame(rows)
    if len(df):
        mean = df.drop(columns=["paper"]).mean(numeric_only=True).round(4).to_dict()
        df.loc[len(df)] = {"paper": "MEAN", **mean}
    return df


def evaluate_baseline_lead3(corpus: list[dict]) -> pd.DataFrame:
    """LEAD-3 baseline (first three sentences) — the standard summarisation baseline."""
    from .text_utils import split_sentences
    from .pdf_reader import split_sections
    rows = []
    for item in corpus:
        secs = split_sections(item["text"])
        body = " ".join(v for k, v in secs.items() if k != "front_matter")
        lead = " ".join(split_sentences(body)[:3])
        rows.append({"paper": item["title"][:45], **rouge(lead, item["reference_summary"])})
    df = pd.DataFrame(rows)
    if len(df):
        df.loc[len(df)] = {"paper": "MEAN", **df.drop(columns=["paper"]).mean(numeric_only=True).round(4).to_dict()}
    return df


def evaluate_retrieval(index, qa_pairs: list[dict], k: int = 3) -> dict:
    """qa_pairs: {question, paper, section, answer_contains}. Reports Hit@k, MRR and answer accuracy."""
    hits, rr, correct, rows = [], [], [], []
    for qa in qa_pairs:
        ret = index.retrieve(qa["question"], k=k)
        rank = next((i + 1 for i, h in enumerate(ret)
                     if h["paper"] == qa["paper"] and qa["answer_contains"].lower() in h["text"].lower()), None)
        hits.append(rank is not None)
        rr.append(1 / rank if rank else 0)
        ans = index.ask(qa["question"], k=k)["answer"]
        ok = qa["answer_contains"].lower() in ans.lower()
        correct.append(ok)
        rows.append({"question": qa["question"], "hit@k": rank is not None, "rank": rank, "answer_correct": ok})
    return {f"hit@{k}": round(float(np.mean(hits)), 3), "mrr": round(float(np.mean(rr)), 3),
            "answer_accuracy": round(float(np.mean(correct)), 3), "details": pd.DataFrame(rows)}


def hallucination_probe(summarizer, text: str, title: str, injected_claim: str) -> dict:
    """Robustness test: append an unsupported claim to a summary and check that grounding flags it."""
    from .summarizer import ground
    from .pdf_reader import split_sections
    s = summarizer.summarize(text, title=title)
    fields = dict(s["fields"])
    fields["key_findings"] = list(fields.get("key_findings") or []) + [injected_claim]
    ev = ground(fields, split_sections(text))
    injected = [e for e in ev if e["claim"] == injected_claim][0]
    genuine = [e["support"] for e in ev if e["claim"] != injected_claim]
    return {"injected_support": injected["support"], "genuine_mean_support": round(float(np.mean(genuine)), 3),
            "flagged": injected["support"] < min(genuine)}


# ------------------------------------------------- evaluation on REAL papers
def evaluate_own_papers(summarizer, articles: list[dict]) -> dict:
    """Standard 'abstract as reference' protocol on the user's own full-text papers:
    the abstract is removed from the input, the body is summarised, and the summary is compared
    with the authors' abstract (ROUGE) against the LEAD-3 baseline. Failure cases are listed.
    articles: [{title, text}] with full text that contains an Abstract section."""
    from .pdf_reader import split_sections
    from .text_utils import split_sentences
    rows, failures = [], []
    for a in articles:
        secs = split_sections(a.get("text") or "")
        ref = secs.get("abstract", "")
        body = "\n\n".join(f"{k}\n{v}" for k, v in secs.items() if k not in ("abstract", "front_matter"))
        if len(ref.split()) < 40 or len(body.split()) < 300:
            failures.append({"paper": a["title"][:60], "problem": "skipped: needs full text with an abstract section"})
            continue
        s = summarizer.summarize(body, title=a["title"])
        cand = s.get("executive_summary") or " ".join(_as_text(v) for v in s["fields"].values())
        r = rouge(cand, ref)
        lead = rouge(" ".join(split_sentences(body)[:3]), ref)
        empty = [k for k, v in s["fields"].items() if not _as_text(v).strip()]
        weak = [e for e in s["evidence"] if e["support"] < 0.25]
        rows.append({"paper": a["title"][:50], **{k: v for k, v in r.items()},
                     "lead3_rouge1": lead["rouge1"], "beats_lead3": (r["rouge1"] or 0) > (lead["rouge1"] or 0),
                     "fields_missing": len(empty), "weak_claims": len(weak), "faithfulness": s["faithfulness"]})
        if empty:
            failures.append({"paper": a["title"][:60], "problem": f"no content found for: {', '.join(empty)}"})
        if (r["rouge1"] or 0) < (lead["rouge1"] or 0):
            failures.append({"paper": a["title"][:60], "problem": "summary scored below the LEAD-3 baseline"})
        for e in weak[:2]:
            failures.append({"paper": a["title"][:60], "problem": f"weakly supported claim: “{e['claim'][:90]}”"})
    df = pd.DataFrame(rows)
    return {"table": df, "failures": pd.DataFrame(failures),
            "summary": df.drop(columns=["paper"]).mean(numeric_only=True).round(3).to_dict() if len(df) else {},
            "n": len(df)}


def rating_summary(ws, account: str | None = None) -> dict:
    q = "SELECT accuracy, usefulness, errors FROM ratings" + (" WHERE account=?" if account else "")
    rows = ws.db.execute(q, (account,) if account else ()).fetchall()
    if not rows:
        return {"n": 0}
    return {"n": len(rows), "accuracy": round(float(np.mean([r["accuracy"] for r in rows])), 2),
            "usefulness": round(float(np.mean([r["usefulness"] for r in rows])), 2),
            "with_errors": sum(1 for r in rows if (r["errors"] or "").strip())}
