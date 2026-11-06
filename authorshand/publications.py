"""
My publications: one list of every paper from ORCID, OpenAlex, Google Scholar and ResearchGate exports,
with type, field, indexing category, citations, co-authors and a formatted citation — plus a co-author table.
Pure functions (no Streamlit) so they can be tested.
"""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

import pandas as pd

from . import citations as C
from .text_utils import normalize_title

TYPE_LABELS = {
    "journal-article": "Journal article", "article": "Journal article", "article-journal": "Journal article",
    "proceedings-article": "Conference paper", "paper-conference": "Conference paper", "conference": "Conference paper",
    "book-chapter": "Book chapter", "chapter": "Book chapter", "book": "Book", "edited-book": "Edited book",
    "posted-content": "Preprint", "preprint": "Preprint", "dissertation": "Thesis", "thesis": "Thesis",
    "report": "Report", "dataset": "Dataset", "review": "Review article", "editorial": "Editorial",
    "letter": "Letter", "other": "Other", "": "Not stated",
    "case-study": "Case study", "case": "Case study", "working-paper": "Working paper",
    "conference-abstract": "Conference abstract", "poster": "Conference poster", "patent": "Patent",
    "magazine-article": "Magazine / newspaper article",
}
# Types offered in the "add a paper manually" form → stored type code
MANUAL_TYPES = {"Journal article": "journal-article", "Conference paper": "proceedings-article",
                "Conference abstract": "conference-abstract", "Conference poster": "poster",
                "Book chapter": "book-chapter", "Book": "book", "Edited book": "edited-book",
                "Case study": "case-study", "Working paper": "working-paper", "Preprint": "preprint",
                "Thesis": "thesis", "Report": "report", "Patent": "patent",
                "Magazine / newspaper article": "magazine-article", "Other": "other"}


def type_label(w: dict) -> str:
    t = (w.get("type") or "").lower()
    if (w.get("venue") or "").lower() == "arxiv":
        return "Preprint"
    if t in TYPE_LABELS:
        return TYPE_LABELS[t]
    v = (w.get("venue") or "").lower()
    if any(k in v for k in ("conference", "proceedings", "symposium", "workshop")):
        return "Conference paper"
    return t.replace("-", " ").capitalize() if t else ("Journal article" if w.get("venue") else "Not stated")


def _norm_issn(s: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", str(s or "")).upper()
    return s if len(s) == 8 else ""


def index_category(w: dict, lists: list[dict]) -> str:
    """Category from the researcher's own indexing lists (Scopus, WoS, ABDC, UGC-CARE …): 'ABDC: A; Scopus: Q1'."""
    hits = []
    issns = [_norm_issn(x) for x in re.split(r"[,; ]+", str(w.get("issn") or "")) if _norm_issn(x)]
    tkey = "t:" + normalize_title(w.get("venue") or "") if w.get("venue") else None
    for L in lists or []:
        idx = L.get("index") or {}
        rating = next((idx[i] for i in issns if i in idx), None) or (idx.get(tkey) if tkey else None)
        if rating:
            hits.append(f"{L.get('name', 'List')}: {rating}")
    return "; ".join(hits)


def _same(a: str, b: str) -> bool:
    a, b = normalize_title(a or ""), normalize_title(b or "")
    return bool(a) and (a == b or SequenceMatcher(None, a, b).ratio() >= 0.92)


def merge_scholar(works: list[dict], gs_articles: list[dict]) -> list[dict]:
    """Attach Google Scholar citation counts to matching works; add Scholar-only papers."""
    out = [dict(w) for w in works]
    for g in gs_articles or []:
        m = next((w for w in out if _same(w.get("title", ""), g.get("title", ""))), None)
        if m:
            m["scholar_citations"] = g.get("citations")
            m["sources"] = sorted(set(m.get("sources") or [m.get("source", "")]) | {"Google Scholar"})
        else:
            new = dict(g)
            new["scholar_citations"] = g.get("citations")
            new["citations"] = None
            new["sources"] = ["Google Scholar"]
            new.setdefault("source", "Google Scholar")
            out.append(new)
    return out


def merge_extra(works: list[dict], extra: list[dict]) -> list[dict]:
    """Add papers from a ResearchGate / Scholar / other export that are not already in the list (DOI, then title)."""
    out = [dict(w) for w in works]
    dois = {(w.get("doi") or "").lower() for w in out if w.get("doi")}
    for e in extra or []:
        if (e.get("doi") or "").lower() in dois and e.get("doi"):
            continue
        if any(_same(w.get("title", ""), e.get("title", "")) for w in out):
            continue
        e = dict(e)
        e.setdefault("sources", [e.get("source") or "Export"])
        out.append(e)
    return out


def field_of(w: dict, theme_of: dict | None = None) -> str:
    if w.get("topics"):
        return w["topics"][0]
    return (theme_of or {}).get(w.get("title", ""), "")


def _authors_text(authors) -> str:
    a = list(authors or [])
    return ", ".join(a[:6]) + (f" … (+{len(a) - 6})" if len(a) > 6 else "")


def publication_table(works: list[dict], own_name: str = "", lists: list[dict] | None = None,
                      theme_of: dict | None = None, style: str = "apa") -> pd.DataFrame:
    me = {t for t in re.findall(r"[a-z]+", (own_name or "").lower()) if len(t) > 2}
    rows = []
    for i, w in enumerate(works):
        co = [a for a in (w.get("authors") or []) if not (me & set(re.findall(r"[a-z]+", a.lower())))]
        rec = C.from_paper(w)
        rows.append({
            "#": i, "Year": w.get("year") or None, "Title": w.get("title", ""), "Journal / venue": w.get("venue", ""),
            "Type": type_label(w), "Field / topic": field_of(w, theme_of),
            "Indexing (your lists)": "; ".join(x for x in (index_category(w, lists or []),
                                                           w.get("manual_indexing", "")) if x),
            "Citations (OpenAlex)": w.get("citations"), "Citations (Scholar)": w.get("scholar_citations"),
            "Co-authors": _authors_text(co), "No. of authors": len(w.get("authors") or []),
            "Open access": "Yes" if w.get("oa_pdf") else "",
            "DOI": w.get("doi", ""), "Found in": ", ".join(w.get("sources") or [w.get("source", "")]),
            "Citation": C.md_to_plain(C.format_reference(rec, style)),
        })
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["Year", "Title"], ascending=[False, True], na_position="last").reset_index(drop=True)
    return df


def coauthor_table(works: list[dict], own_name: str = "") -> pd.DataFrame:
    me = {t for t in re.findall(r"[a-z]+", (own_name or "").lower()) if len(t) > 2}
    d = defaultdict(lambda: {"papers": 0, "years": [], "cites": 0, "titles": []})
    for w in works:
        for a in w.get("authors") or []:
            if me & set(re.findall(r"[a-z]+", a.lower())):
                continue
            x = d[a.strip()]
            x["papers"] += 1
            if w.get("year"):
                x["years"].append(int(w["year"]))
            x["cites"] += int(w.get("citations") or w.get("scholar_citations") or 0)
            x["titles"].append(w.get("title", ""))
    rows = [{"Co-author": k, "Joint papers": v["papers"], "First": min(v["years"]) if v["years"] else None,
             "Latest": max(v["years"]) if v["years"] else None, "Citations of joint papers": v["cites"],
             "Papers": "; ".join(t[:60] for t in v["titles"][:4])} for k, v in d.items()]
    df = pd.DataFrame(rows)
    if len(df):
        df = df.sort_values(["Joint papers", "Latest"], ascending=[False, False]).reset_index(drop=True)
    return df


def summary_counts(df: pd.DataFrame) -> dict:
    if not len(df):
        return {"total": 0}
    return {"total": len(df), "by_type": df["Type"].value_counts().to_dict(),
            "with_doi": int((df["DOI"] != "").sum()), "open_access": int((df["Open access"] == "Yes").sum()),
            "indexed": int((df["Indexing (your lists)"] != "").sum()),
            "first_year": int(df["Year"].min()) if df["Year"].notna().any() else None,
            "latest_year": int(df["Year"].max()) if df["Year"].notna().any() else None}


def manual_work(kind: str, title: str, authors: str, year, venue: str = "", volume: str = "", issue: str = "",
                pages: str = "", publisher: str = "", doi: str = "", url: str = "", citations=None,
                indexing: str = "", notes: str = "", editors: str = "") -> dict:
    """A paper the researcher adds by hand (missing from ORCID / Scholar / ResearchGate)."""
    import time
    import uuid
    split = lambda x: [a.strip() for a in re.split(r"[;\n]", x or "") if a.strip()]
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", (doi or "").strip(), flags=re.I)
    return {"id": "manual:" + uuid.uuid4().hex[:10], "title": title.strip(), "authors": split(authors),
            "editors": split(editors), "year": int(year) if str(year or "").isdigit() else None,
            "venue": venue.strip(), "volume": str(volume or ""), "issue": str(issue or ""), "pages": str(pages or ""),
            "publisher": publisher.strip(), "doi": doi, "url": url.strip(),
            "citations": int(citations) if str(citations or "").isdigit() else None,
            "type": MANUAL_TYPES.get(kind, kind), "manual_indexing": indexing.strip(), "notes": notes.strip(),
            "source": "Added by you", "sources": ["Added by you"], "added": time.time()}


def year_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Papers per year and type (for the year-wise chart)."""
    if not len(df):
        return pd.DataFrame(columns=["Year", "Type", "Papers"])
    d = df.dropna(subset=["Year"]).groupby(["Year", "Type"]).size().reset_index(name="Papers")
    d["Year"] = d["Year"].astype(int)
    return d.sort_values("Year")


# ------------------------------------------------------------------ ORCID ↔ Google Scholar check
def _close(a: str, b: str) -> bool:
    """Title match that tolerates Scholar's truncated / re-cased titles."""
    a, b = normalize_title(a or ""), normalize_title(b or "")
    if not a or not b:
        return False
    if a == b or SequenceMatcher(None, a, b).ratio() >= 0.88:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 25 and long_.startswith(short)


def reconcile(orcid_works: list[dict], scholar_articles: list[dict]) -> pd.DataFrame:
    """One row per paper: in both / only on Google Scholar / only on ORCID, with citation counts side by side."""
    rows, used = [], set()
    for w in orcid_works:
        j = next((k for k, g in enumerate(scholar_articles) if k not in used and _close(w.get("title"), g.get("title"))),
                 None)
        g = scholar_articles[j] if j is not None else None
        if j is not None:
            used.add(j)
        year_diff = bool(g and w.get("year") and g.get("year") and int(w["year"]) != int(g["year"]))
        rows.append({"Status": "✅ In both" if g else "🟠 Only on ORCID", "Title": w.get("title", ""),
                     "Year (ORCID)": w.get("year"), "Year (Scholar)": g.get("year") if g else None,
                     "Journal / venue": w.get("venue") or (g or {}).get("venue", ""),
                     "DOI": w.get("doi", ""), "Citations (OpenAlex)": w.get("citations"),
                     "Citations (Scholar)": g.get("citations") if g else None,
                     "Note": "year differs" if year_diff else ""})
    for k, g in enumerate(scholar_articles):
        if k in used:
            continue
        rows.append({"Status": "🔵 Only on Google Scholar", "Title": g.get("title", ""), "Year (ORCID)": None,
                     "Year (Scholar)": g.get("year"), "Journal / venue": g.get("venue", ""), "DOI": g.get("doi", ""),
                     "Citations (OpenAlex)": None, "Citations (Scholar)": g.get("citations"),
                     "Note": "add to ORCID"})
    return pd.DataFrame(rows)


def compare_metrics(profile_metrics: dict | None, gs: dict, orcid_count: int, scholar_count: int) -> pd.DataFrame:
    gm = (gs or {}).get("metrics") or {}
    pm = profile_metrics or {}
    out = [("Papers listed", orcid_count, scholar_count),
           ("Citations", pm.get("citations"), (gm.get("citations") or {}).get("all")),
           ("h-index", pm.get("h_index"), (gm.get("h_index") or {}).get("all")),
           ("i10-index", pm.get("i10_index"), (gm.get("i10_index") or {}).get("all"))]
    return pd.DataFrame([{"Measure": m, "ORCID + OpenAlex": a if a is not None else "—",
                          "Google Scholar": b if b is not None else "—"} for m, a, b in out])
