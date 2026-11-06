"""Auto-refresh: keeps each project current.

For every project that is due (its interval has passed) it
  1. runs the project's saved topic search for works published since the last refresh,
  2. finds new papers that CITE the project's articles (OpenAlex `cites:` filter),
  3. updates citation counts and flags retracted works,
and files anything new as an alert in the project. Runs on demand, while the
app is open (timed fragment), or headless from a scheduler (see README).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from . import demo
from .config import Settings
from .connectors import HTTP, OpenAlexClient, clean_doi
from .store import Workspace


def is_due(project: dict, now: float | None = None) -> bool:
    now = now or time.time()
    return (project.get("auto_refresh_hours") or 0) > 0 and \
        now - (project.get("last_refresh") or 0) >= project["auto_refresh_hours"] * 3600


def refresh_project(ws: Workspace, pid: int, settings: Settings | None = None, demo_mode: bool = False,
                    max_new: int = 15) -> dict:
    s = settings or Settings()
    proj = ws.project(pid)
    arts = ws.articles(pid)
    report = {"project": proj["name"], "new_alerts": 0, "citations_updated": 0, "retracted": [], "errors": [],
              "mode": "demo" if demo_mode else "live"}
    if demo_mode:
        query = proj.get("topic_query") or " ".join(a["title"] for a in arts[:3])
        cands = demo.search(query or "analytics", 5) + demo.load_corpus()["papers"]
        new = [p for p in {c["id"]: c for c in cands}.values() if not ws.has_article(pid, p)][:3]
        for p in new:
            if ws.add_alert(pid, p, f"matches saved search “{query[:40]}” (demo)"):
                report["new_alerts"] += 1
        ws.update_project(pid, last_refresh=time.time())
        return report

    oa = OpenAlexClient(HTTP(s))
    since = datetime.fromtimestamp(proj["last_refresh"]) if proj.get("last_refresh") else datetime.now() - timedelta(days=365)
    since_s = since.strftime("%Y-%m-%d")
    # 1. saved topic search
    if proj.get("topic_query"):
        try:
            for p in oa.search(proj["topic_query"], n=max_new, from_year=None)[:max_new]:
                if p.get("year") and p["year"] >= since.year and not ws.has_article(pid, p):
                    report["new_alerts"] += ws.add_alert(pid, p, "new on your saved topic")
        except Exception as e:
            report["errors"].append(f"topic search: {e}")
    # 2. new citing papers + 3. citation counts / retractions (batched by DOI)
    dois = [clean_doi(a["doi"]) for a in arts if a.get("doi")]
    for i in range(0, len(dois), 40):
        batch = dois[i:i + 40]
        try:
            d = oa.http.get(f"{oa.BASE}/works", params=oa._params(
                {"filter": "doi:" + "|".join(batch), "per-page": 50,
                 "select": "id,doi,cited_by_count,is_retracted,title"}))
            ids = []
            for w in d.get("results", []):
                doi = clean_doi(w.get("doi") or "")
                ids.append(w["id"].rsplit("/", 1)[-1])
                for a in arts:
                    if clean_doi(a.get("doi") or "") == doi:
                        if (w.get("cited_by_count") or 0) != (a.get("citations") or 0):
                            ws.update_article(a["id"], citations=w.get("cited_by_count") or 0, checked=time.time())
                            report["citations_updated"] += 1
                        if w.get("is_retracted"):
                            report["retracted"].append(a["title"])
            if ids:
                c = oa.http.get(f"{oa.BASE}/works", params=oa._params(
                    {"filter": f"cites:{'|'.join(ids)},from_publication_date:{since_s}", "per-page": max_new,
                     "sort": "cited_by_count:desc"}))
                for w in c.get("results", []):
                    p = oa._to_paper(w)
                    if not ws.has_article(pid, p):
                        report["new_alerts"] += ws.add_alert(pid, p, "cites a paper in this project")
        except Exception as e:
            report["errors"].append(f"citations: {e}")
    ws.update_project(pid, last_refresh=time.time())
    return report


def refresh_due(ws: Workspace, owner: str, settings: Settings | None = None, demo_mode: bool = False) -> list[dict]:
    return [refresh_project(ws, p["id"], settings, demo_mode) for p in ws.projects(owner) if is_due(p)]


if __name__ == "__main__":  # headless: python -m authorshand.refresh you@uni.edu
    import sys
    ws = Workspace()
    for r in refresh_due(ws, sys.argv[1], Settings(), demo_mode=False):
        print(r)
