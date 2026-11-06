"""Offline demo corpus loader (lets the whole system run with no internet / no key)."""
from __future__ import annotations

import json
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_data"
DEMO_ORCID = "0000-0000-0000-0001"


def load_corpus() -> dict:
    meta = json.loads((DEMO_DIR / "papers" / "corpus.json").read_text(encoding="utf-8"))
    for p in meta["papers"]:
        p["text"] = (DEMO_DIR / "papers" / p["file"]).read_text(encoding="utf-8")
        p.setdefault("abstract", p["text"].split("Abstract", 1)[-1].split("1. Introduction")[0].strip())
        p.setdefault("citations", 0)
        p.setdefault("oa_pdf", "")
        p.setdefault("source", "Demo corpus")
    return meta


def load_profile_dict() -> dict:
    return json.loads((DEMO_DIR / "demo_profile.json").read_text(encoding="utf-8"))


def researchgate_export() -> str:
    return (DEMO_DIR / "sample_researchgate_export.bib").read_text(encoding="utf-8")


def search(query: str, n: int = 5) -> list[dict]:
    """TF-IDF search over the demo corpus (stands in for OpenAlex/S2/arXiv offline)."""
    from .text_utils import cosine_sim, tfidf_matrix
    papers = load_corpus()["papers"]
    docs = [f"{p['title']} {p['abstract']}" for p in papers]
    vec, m = tfidf_matrix(docs + [query])
    sims = cosine_sim(m[-1], m[:-1]).ravel()
    order = sims.argsort()[::-1][:n]
    return [dict(papers[i], score=round(float(sims[i]), 3)) for i in order if sims[i] > 0] or papers[:n]


def get(identifier: str) -> dict:
    papers = load_corpus()["papers"]
    ident = identifier.lower().strip()
    for p in papers:
        if ident in (p["id"].lower(), p["doi"].lower()) or ident in p["title"].lower():
            return p
    return search(identifier, 1)[0]


DEMO_EMAIL = "demo@authorshand.app"


def _with_pdf_pages(p: dict) -> dict:
    """Attach per-page text from the demo PDF so evidence carries page numbers, like a real upload."""
    from .evidence import parse_report, read_pdf_pages
    q = dict(p)
    pdf = DEMO_DIR / "papers" / p.get("pdf", "")
    if p.get("pdf") and pdf.exists():
        pages = read_pdf_pages(str(pdf))
        q.update(pages_text=pages, pages_count=len(pages), text="\n".join(pages),
                 parse=parse_report("\n".join(pages), pages), source="Demo corpus (synthetic PDF)")
    return q


def seed_workspace(ws, email: str = DEMO_EMAIL) -> None:
    """Create two example projects with folders and the synthetic papers (idempotent)."""
    if ws.projects(email):
        return
    ws.user(email)
    ws.update_user(email, name="A. Demo", orcid=DEMO_ORCID,
                   researchgate="https://www.researchgate.net/profile/A-Demo")
    papers = {p["id"]: _with_pdf_pages(p) for p in load_corpus()["papers"]}
    p1 = ws.create_project(email, "GenAI & explainable ML in organisations",
                           "Paper on AI-assisted decisions in HR and banking",
                           topic_query="explainable machine learning generative AI organisations",
                           citation_style="apa", auto_refresh_hours=24)
    core = ws.add_folder(p1, "Core papers")
    meth = ws.add_folder(p1, "Methods references")
    for pid, folder in (("demo:p1", core), ("demo:p2", core), ("demo:p5", core), ("demo:p3", meth)):
        ws.add_article(p1, papers[pid], folder, papers[pid]["text"])
    chapter = {"id": "demo:ch1", "type": "book-chapter", "title": "Explainable AI for people decisions: a primer",
               "authors": ["A. Demo"], "editors": ["Kiran Rao", "Priya Sharma"], "year": 2023,
               "venue": "Handbook of People Analytics (fictional)", "edition": "2", "pages": "45-67",
               "publisher": "Demo Academic Press", "place": "Hyderabad", "doi": "10.0000/demo.ch.2023.01",
               "abstract": "This chapter introduces explainable AI methods such as SHAP and counterfactual "
                           "explanations for HR decisions. It argues that explanations improve manager trust. "
                           "Future research should test explanation formats with HR managers in field settings.",
               "source": "Demo corpus"}
    ws.add_article(p1, chapter, meth, "")
    p2 = ws.create_project(email, "Learning analytics review", "Systematic review for a PGDM study",
                           topic_query="learning analytics at-risk students early warning", citation_style="apa")
    f2 = ws.add_folder(p2, "Included studies")
    ws.add_article(p2, papers["demo:p4"], f2, papers["demo:p4"]["text"])


EXAMPLE_PROJECT = "Example project (synthetic demo papers)"


def seed_example_project(ws, account: str) -> int:
    """Add a clearly labelled example project with the synthetic demo papers to ANY account (idempotent)."""
    for p in ws.projects(account):
        if p["name"] == EXAMPLE_PROJECT:
            return p["id"]
    papers = [_with_pdf_pages(p) for p in load_corpus()["papers"]]
    pid = ws.create_project(account, EXAMPLE_PROJECT, "Synthetic papers for trying every feature",
                            topic_query="explainable machine learning generative AI organisations",
                            citation_style="apa", auto_refresh_hours=0)
    folder = ws.add_folder(pid, "Example papers")
    for p in papers:
        ws.add_article(pid, p, folder, p.get("text", ""))
    return pid
