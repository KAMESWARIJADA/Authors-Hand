"""Reproducible literature-review workflow (PRISMA 2020 style).

Protocol → logged searches (database, query, filters, date, hits) → duplicate
removal with recorded reasons → title/abstract screening with include / exclude
/ maybe and reasons → PRISMA counts → exports (screening table, search log,
duplicate log, protocol, and a ready-to-edit "search strategy" methods paragraph).
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher

import pandas as pd

from . import connectors, demo
from .config import Settings
from .store import Workspace, article_key
from .text_utils import normalize_title

DATABASES = ["OpenAlex", "Semantic Scholar", "arXiv", "Crossref"]
DEFAULT_EXCLUSIONS = ["Not relevant to the research question", "Wrong population / context", "Wrong study design",
                      "Not empirical (opinion / editorial)", "Language not supported", "Full text not available",
                      "Duplicate publication", "Outside the date range"]
REVIEW_TYPES = ["Systematic review", "Scoping review", "Qualitative / thematic synthesis", "Bibliometric review",
                "Exploratory reading (no formal protocol)"]


def _search_db(db: str, query: str, n: int, filters: dict, s: Settings, demo_mode: bool) -> list[dict]:
    if demo_mode:
        return demo.search(query, n)
    http = connectors.HTTP(s)
    if db == "OpenAlex":
        res = connectors.OpenAlexClient(http).search(query, n, from_year=filters.get("year_from"))
    elif db == "Semantic Scholar":
        res = connectors.SemanticScholarClient(http).search(query, n)
    elif db == "arXiv":
        res = connectors.ArxivClient(http).search(query, n)
    elif db == "Crossref":
        d = http.get("https://api.crossref.org/works", params={"query": query, "rows": n})
        from .citations import from_crossref
        res = []
        for m in d.get("message", {}).get("items", []):
            yr = (((m.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
            res.append(connectors.paper(id=f"doi:{m.get('DOI', '')}", title=(m.get("title") or [""])[0],
                                        authors=[f"{a.get('given', '')} {a.get('family', '')}".strip()
                                                 for a in m.get("author", [])], year=yr,
                                        venue=(m.get("container-title") or [""])[0], doi=m.get("DOI", ""),
                                        citations=m.get("is-referenced-by-count", 0), source="Crossref",
                                        type=m.get("type", ""), csl=from_crossref(m)))
    else:
        raise ValueError(db)
    yf, yt = filters.get("year_from"), filters.get("year_to")
    return [p for p in res if (not yf or (p.get("year") or 0) >= yf) and (not yt or (p.get("year") or 9999) <= yt)
            and (not filters.get("oa_only") or p.get("oa_pdf"))]


def run_search(ws: Workspace, pid: int, databases: list[str], query: str, filters: dict, n: int = 25,
               settings: Settings | None = None, demo_mode: bool = False) -> list[dict]:
    """Run and LOG a search on each database; store new records; detect duplicates with reasons."""
    s = settings or Settings()
    logs = []
    for db in databases:
        try:
            hits = _search_db(db, query, n, filters, s, demo_mode)
            note = "demo corpus (offline)" if demo_mode else ""
        except Exception as e:
            hits, note = [], f"failed: {e}"
        cur = ws.db.execute("INSERT INTO review_runs(project_id,database,query,filters,run_at,n_results,note)"
                            " VALUES (?,?,?,?,?,?,?)", (pid, db, query, json.dumps(filters), time.time(), len(hits), note))
        run_id = cur.lastrowid
        for h in hits:
            _add_record(ws, pid, h, run_id, db)
        logs.append({"database": db, "results": len(hits), "note": note})
    ws.db.commit()
    return logs


def import_records(ws: Workspace, pid: int, records: list[dict], source_name: str) -> int:
    cur = ws.db.execute("INSERT INTO review_runs(project_id,database,query,filters,run_at,n_results,note)"
                        " VALUES (?,?,?,?,?,?,?)", (pid, source_name, "(imported file)", "{}", time.time(), len(records),
                                                    "records imported from an export file"))
    for r in records:
        _add_record(ws, pid, r, cur.lastrowid, source_name)
    ws.db.commit()
    return len(records)


def _add_record(ws: Workspace, pid: int, paper: dict, run_id: int, db: str):
    key = article_key(paper)
    row = ws.db.execute("SELECT id, runs FROM review_records WHERE project_id=? AND key=?", (pid, key)).fetchone()
    if row:  # same DOI / identical title already present → same record found again
        runs = json.loads(row["runs"]) + [run_id]
        ws.db.execute("UPDATE review_records SET runs=? WHERE id=?", (json.dumps(sorted(set(runs))), row["id"]))
        return
    dup_of, reason = None, ""
    t = normalize_title(paper.get("title", ""))
    for r in ws.db.execute("SELECT id, data FROM review_records WHERE project_id=? AND duplicate_of IS NULL", (pid,)):
        d = json.loads(r["data"])
        if paper.get("doi") and d.get("doi") and paper["doi"].lower() == d["doi"].lower():
            dup_of, reason = r["id"], f"same DOI ({paper['doi']})"
            break
        sim = SequenceMatcher(None, t, normalize_title(d.get("title", ""))).ratio()
        if t and sim >= 0.92 and (not paper.get("year") or not d.get("year") or abs((paper.get("year") or 0) - (d.get("year") or 0)) <= 1):
            dup_of, reason = r["id"], f"title {sim:.0%} similar, same year"
            break
    data = {k: v for k, v in paper.items() if k not in ("text",)}
    data["found_in"] = db
    ws.db.execute("INSERT INTO review_records(project_id,key,data,runs,duplicate_of,duplicate_reason,decision,updated)"
                  " VALUES (?,?,?,?,?,?,?,?)", (pid, key, json.dumps(data), json.dumps([run_id]), dup_of, reason,
                                               "duplicate" if dup_of else "unscreened", time.time()))


def records(ws: Workspace, pid: int, include_duplicates: bool = False) -> list[dict]:
    q = "SELECT * FROM review_records WHERE project_id=?" + ("" if include_duplicates else " AND duplicate_of IS NULL")
    out = []
    for r in ws.db.execute(q + " ORDER BY id", (pid,)):
        d = dict(r)
        d["paper"] = json.loads(d.pop("data"))
        d["runs"] = json.loads(d["runs"])
        out.append(d)
    return out


def runs(ws: Workspace, pid: int) -> list[dict]:
    return [dict(r) for r in ws.db.execute("SELECT * FROM review_runs WHERE project_id=? ORDER BY run_at", (pid,))]


def set_decision(ws: Workspace, rid: int, decision: str, reason: str = "", notes: str = "", stage: str = ""):
    ws.db.execute("UPDATE review_records SET decision=?, reason=?, notes=?, stage=COALESCE(NULLIF(?,''),stage), updated=?"
                  " WHERE id=?", (decision, reason, notes, stage, time.time(), rid))
    ws.db.commit()


def prisma_counts(ws: Workspace, pid: int) -> dict:
    rr = runs(ws, pid)
    allrec = records(ws, pid, include_duplicates=True)
    uniq = [r for r in allrec if r["duplicate_of"] is None]
    found_again = sum(max(0, len(r["runs"]) - 1) for r in allrec)
    dec = Counter(r["decision"] for r in uniq)
    reasons = Counter(r["reason"] or "No reason given" for r in uniq if r["decision"] == "exclude")
    return {"identified": sum(x["n_results"] for x in rr),
            "by_database": {db: sum(x["n_results"] for x in rr if x["database"] == db)
                            for db in dict.fromkeys(x["database"] for x in rr)},
            "duplicates_removed": len(allrec) - len(uniq) + found_again,
            "screened": len(uniq), "excluded": dec.get("exclude", 0), "maybe": dec.get("maybe", 0),
            "included": dec.get("include", 0), "unscreened": dec.get("unscreened", 0),
            "exclusion_reasons": dict(reasons)}


def prisma_dot(c: dict) -> str:
    dbs = "\\n".join(f"{k}: {v}" for k, v in c["by_database"].items()) or "no searches yet"
    ex = "\\n".join(f"{k}: {v}" for k, v in c["exclusion_reasons"].items()) or "none"
    return f'''digraph P {{ rankdir=TB; bgcolor="transparent"; node [shape=box, style="rounded,filled", fillcolor="#F1F5F7",
color="#94A3B8", fontname="Helvetica", fontsize=11];
a [label="Records identified (n = {c['identified']})\\n{dbs}", fillcolor="#E6F2F1", color="#0F766E"];
b [label="Duplicates removed (n = {c['duplicates_removed']})"];
s [label="Records screened (n = {c['screened']})"];
e [label="Records excluded (n = {c['excluded']})\\n{ex}", fillcolor="#FDF1E3", color="#B45309"];
m [label="Awaiting decision (maybe {c['maybe']}, unscreened {c['unscreened']})"];
i [label="Studies included (n = {c['included']})", fillcolor="#E6F2F1", color="#0F766E"];
a -> s; a -> b [style=dashed]; s -> e; s -> m [style=dashed]; s -> i; }}'''


def screening_table(ws: Workspace, pid: int) -> pd.DataFrame:
    rows = []
    for r in records(ws, pid):
        p = r["paper"]
        rows.append({"id": r["id"], "title": p.get("title", ""), "year": p.get("year"), "venue": p.get("venue", ""),
                     "doi": p.get("doi", ""), "found in": p.get("found_in", ""), "decision": r["decision"],
                     "reason": r["reason"], "notes": r["notes"], "stage": r["stage"],
                     "abstract": (p.get("abstract") or "")[:400]})
    return pd.DataFrame(rows)


def duplicate_log(ws: Workspace, pid: int) -> pd.DataFrame:
    rows = []
    allrec = {r["id"]: r for r in records(ws, pid, include_duplicates=True)}
    for r in allrec.values():
        if r["duplicate_of"]:
            keep = allrec.get(r["duplicate_of"])
            rows.append({"removed": r["paper"].get("title", ""), "found in": r["paper"].get("found_in", ""),
                         "kept": keep["paper"].get("title", "") if keep else "", "reason": r["duplicate_reason"]})
        if len(r["runs"]) > 1:
            rows.append({"removed": f"{len(r['runs']) - 1} repeat hit(s)", "found in": "several searches",
                         "kept": r["paper"].get("title", ""), "reason": "identical DOI/title in another search"})
    return pd.DataFrame(rows)


def methods_paragraph(ws: Workspace, pid: int, protocol: dict) -> str:
    rr = runs(ws, pid)
    c = prisma_counts(ws, pid)
    dbs = sorted({r["database"] for r in rr})
    dates = [datetime.fromtimestamp(r["run_at"]).strftime("%d %B %Y") for r in rr]
    queries = sorted({r["query"] for r in rr if r["query"] != "(imported file)"})
    f = protocol.get("filters", {})
    lim = []
    if f.get("year_from") or f.get("year_to"):
        lim.append(f"publication years {f.get('year_from') or 'any'}–{f.get('year_to') or 'present'}")
    if f.get("oa_only"):
        lim.append("open-access records only")
    reasons = "; ".join(f"{k} (n = {v})" for k, v in c["exclusion_reasons"].items()) or "none recorded yet"
    return (f"A {protocol.get('review_type', 'literature review').lower()} was conducted to answer the question: "
            f"“{protocol.get('question') or '[research question]'}”. "
            f"{', '.join(dbs) or '[databases]'} were searched"
            + (f" between {dates[0]} and {dates[-1]}" if len(set(dates)) > 1 else (f" on {dates[0]}" if dates else ""))
            + (f" using the search string(s) {'; '.join(f'“{q}”' for q in queries)}" if queries else "")
            + (f", limited to {', '.join(lim)}" if lim else "") + ". "
            f"The searches identified {c['identified']} records; after removing {c['duplicates_removed']} duplicates, "
            f"{c['screened']} records were screened on title and abstract against pre-defined criteria "
            f"(inclusion: {protocol.get('inclusion') or '[criteria]'}; exclusion: {protocol.get('exclusion_text') or '[criteria]'}). "
            f"{c['excluded']} records were excluded — {reasons} — and {c['included']} studies were included in the synthesis. "
            "Screening decisions and reasons were recorded in Author's Hand and are available as a supplementary file.")


def export_bundle(ws: Workspace, pid: int, protocol: dict) -> dict:
    return {"protocol": protocol, "searches": runs(ws, pid), "prisma": prisma_counts(ws, pid),
            "screening": screening_table(ws, pid).to_dict("records"),
            "duplicates": duplicate_log(ws, pid).to_dict("records"),
            "methods_paragraph": methods_paragraph(ws, pid, protocol), "exported": time.time()}
