"""Traceable evidence: where every statement comes from.

* `text_source`         — "Full text (PDF, 12 pages)" / "Abstract only" / "Metadata only" …
* `read_pdf_pages`      — per-page text, flags pages with no extractable text (scanned → OCR needed)
* `parse_report`        — pages, empty pages, tables/figures mentioned but not read
* `page_of`             — page number that contains a sentence
* `trace_statements`    — split any draft into statements and link each to its best source passage
                          (paper, section, page, DOI, support, label: extracted / generated / candidate)
* `initial_provenance`  — which source supplied each bibliographic field
"""
from __future__ import annotations

import io
import re
import time

from .pdf_reader import split_sections
from .text_utils import clean_text, cosine_sim, split_sentences, tfidf_matrix

LABELS = {
    "extracted": "Extracted from the paper",
    "generated": "AI-generated wording",
    "candidate": "Candidate — verify",
}
CITE_RE = re.compile(r"\(([A-Z][A-Za-z'\-]+(?: et al\.| (?:&|and) [A-Z][A-Za-z'\-]+)?),? (\d{4}|n\.d\.)\)|"
                     r"([A-Z][A-Za-z'\-]+(?: et al\.| and [A-Z][A-Za-z'\-]+)?) \((\d{4})\)")
BIB_FIELDS = ["title", "authors", "editors", "year", "venue", "volume", "issue", "pages", "publisher", "place",
              "edition", "doi", "type"]


# ------------------------------------------------------------- text source
def text_source(paper: dict, text: str) -> str:
    pages = paper.get("pages_count")
    if text and len(text.split()) > 400:
        if pages:
            return f"Full text (PDF, {pages} pages)"
        return "Full text (open-access download)" if paper.get("oa_pdf") else "Full text"
    if text or paper.get("abstract"):
        return "Abstract only"
    return "Metadata only"


def is_full_text(src: str) -> bool:
    return (src or "").startswith("Full text")


def read_pdf_pages(source) -> list[str]:
    from pypdf import PdfReader
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    pages = [clean_text(p.extract_text() or "") for p in PdfReader(source).pages]
    ocr = _ocr_engine()
    if ocr is not None:  # optional OCR for scanned pages (pip install rapidocr-onnxruntime pypdfium2)
        for i, t in enumerate(pages):
            if len(t.strip()) < 30:
                try:
                    pages[i] = _ocr_page(source, i, ocr) or t
                except Exception:
                    pass
    return pages


def _ocr_engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
        return RapidOCR()
    except Exception:
        return None


def _ocr_page(source, i, ocr) -> str:
    import pypdfium2 as pdfium
    if hasattr(source, "seek"):
        source.seek(0)
    doc = pdfium.PdfDocument(source)
    img = doc[i].render(scale=2).to_pil()
    res, _ = ocr(img)
    return "\n".join(r[1] for r in (res or []))


def parse_report(text: str, pages: list[str] | None = None) -> dict:
    tables = sorted(set(re.findall(r"\bTable\s+(\d+)", text)), key=int)
    figures = sorted(set(re.findall(r"\b(?:Figure|Fig\.)\s+(\d+)", text)), key=int)
    empty = [i + 1 for i, p in enumerate(pages or []) if len(p.strip()) < 30]
    secs = [k for k in split_sections(text).keys() if k not in ("front_matter", "body")] if text else []
    issues = []
    if empty:
        issues.append(f"{len(empty)} page(s) have no extractable text (scanned?) — pages {empty[:10]}. "
                      "Install OCR support or paste the text.")
    if tables or figures:
        issues.append(f"The paper mentions {len(tables)} table(s) and {len(figures)} figure(s); their contents "
                      "are not read — check numbers in tables against the PDF.")
    if text and not secs:
        issues.append("No section headings were recognised; section labels in the evidence will be ‘body’.")
    return {"pages": len(pages or []), "empty_pages": empty, "tables": tables, "figures": figures,
            "sections": secs, "issues": issues}


def page_of(snippet: str, pages: list[str] | None) -> int | None:
    if not pages or not snippet:
        return None
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    probe = norm(snippet)[:70]
    if len(probe) < 15:
        return None
    for i, p in enumerate(pages):
        if probe in norm(p):
            return i + 1
    probe = norm(snippet)[:35]
    for i, p in enumerate(pages):
        if probe in norm(p):
            return i + 1
    return None


def support_label(score: float) -> str:
    return "strong" if score >= 0.5 else ("moderate" if score >= 0.25 else "weak")


# ------------------------------------------------------------ provenance
def initial_provenance(paper: dict) -> dict:
    src = paper.get("source") or "Unknown source"
    if isinstance(paper.get("sources"), list) and paper["sources"]:
        src = " + ".join(dict.fromkeys(paper["sources"]))
    now = time.strftime("%Y-%m-%d")
    return {f: {"source": src, "at": now} for f in BIB_FIELDS if paper.get(f) not in (None, "", [])}


def mark_edited(old: dict, new: dict) -> dict:
    prov = dict(old.get("provenance") or {})
    now = time.strftime("%Y-%m-%d")
    for f in BIB_FIELDS:
        if (old.get(f) or "") != (new.get(f) or ""):
            prov[f] = {"source": "Edited by you", "at": now}
    return prov


# --------------------------------------------------------------- tracing
def _source_index(articles: list[dict]):
    """articles: [{cite, paper, text, pages?}] → flat list of source sentences."""
    rows = []
    for ai, a in enumerate(articles):
        text = a.get("text") or f"{a['paper'].get('title', '')}\n\nAbstract: {a['paper'].get('abstract', '')}"
        for sec, body in split_sections(text).items():
            if sec == "front_matter":
                continue
            sents = split_sentences(body, min_words=4)
            for si, snt in enumerate(sents):
                rows.append({"a": ai, "section": sec, "sentence": snt,
                             "context": " ".join(sents[max(0, si - 1): si + 2])})
    return rows


def _cited_articles(statement: str, articles: list[dict]) -> list[int]:
    hits = []
    for ai, a in enumerate(articles):
        lead = (a.get("cite") or "").strip("()").split(",")[0].split(" ")[0]
        yr = str(a["paper"].get("year") or "")
        if lead and lead in statement and (not yr or yr in statement):
            hits.append(ai)
    return hits


def trace_statements(draft: str, articles: list[dict], default_kind: str = "generated") -> list[dict]:
    """Split a draft into statements and link each to its best-supporting passage."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", draft or "")
    stmts = [s for s in split_sentences(text.replace("\n", " "), min_words=5)]
    src = _source_index(articles)
    if not stmts:
        return []
    if not src:
        return [{"statement": s, "kind": default_kind, "label": LABELS[default_kind], "support": 0.0,
                 "strength": "weak", "paper": "", "cite": "", "section": "", "page": None, "doi": "",
                 "passage": "", "context": ""} for s in stmts]
    _, m = tfidf_matrix([r["sentence"] for r in src] + stmts)
    S, Q = m[:len(src)], m[len(src):]
    sims = cosine_sim(Q, S)
    out = []
    for i, s in enumerate(stmts):
        cited = _cited_articles(s, articles)
        cand = [j for j, r in enumerate(src) if not cited or r["a"] in cited]
        j = max(cand, key=lambda k: sims[i, k]) if cand else int(sims[i].argmax())
        score = float(sims[i, j])
        r = src[j]
        a = articles[r["a"]]
        if default_kind == "candidate":
            kind = "candidate"
        elif (score >= 0.5 and (cited or default_kind == "extracted")) or score >= 0.75:
            kind = "extracted"
        else:
            kind = "generated"
        out.append({"statement": s, "kind": kind, "label": LABELS[kind], "support": round(score, 3),
                    "strength": support_label(score), "paper": a["paper"].get("title", ""), "cite": a.get("cite", ""),
                    "section": r["section"], "page": page_of(r["sentence"], a.get("pages")),
                    "doi": a["paper"].get("doi", ""), "passage": r["sentence"], "context": r["context"],
                    "text_source": a.get("text_source", "")})
    return out


def disagreements(relations: list[dict]) -> list[dict]:
    """Same outcome, opposite directions across different studies → sources disagree."""
    by_dv = {}
    for r in relations:
        key = re.sub(r"[^a-z ]", "", r["dv"].lower()).strip()
        by_dv.setdefault(key, []).append(r)
    out = []
    for dv, rs in by_dv.items():
        signs = {r["sign"] for r in rs}
        if len(signs) > 1 and len({r["cite"] for r in rs}) > 1:
            out.append({"outcome": dv, "positive": [r["cite"] for r in rs if r["sign"] == "+"],
                        "negative": [r["cite"] for r in rs if r["sign"] != "+"]})
    return out


CONTRAST_CUES = ("in contrast", "contrary to", "did not find", "no significant", "not significant", "inconsistent with",
                 "contradict", "failed to", "mixed evidence", "questioned")


def contrasting_sentences(articles: list[dict]) -> list[dict]:
    out = []
    for r in _source_index(articles):
        if any(c in r["sentence"].lower() for c in CONTRAST_CUES):
            a = articles[r["a"]]
            out.append({"cite": a.get("cite", ""), "section": r["section"], "sentence": r["sentence"],
                        "page": page_of(r["sentence"], a.get("pages"))})
    return out
