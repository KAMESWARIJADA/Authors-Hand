"""Litmaps-style citation map: seed articles, the works they cite, and the works
citing them, laid out by publication year (x) and citations (y)."""
from __future__ import annotations

from .config import Settings
from .connectors import HTTP, OpenAlexClient, clean_doi
from .text_utils import cosine_sim, tfidf_matrix


def build_map(seeds: list[dict], settings: Settings | None = None, demo_mode: bool = False,
              per_seed: int = 8) -> dict:
    nodes, edges = {}, []

    def node(p, kind):
        key = clean_doi(p.get("doi", "")) or p.get("id") or p.get("title", "")[:60]
        if key not in nodes:
            nodes[key] = {"id": key, "title": p.get("title", ""), "year": p.get("year"),
                          "citations": p.get("citations") or 0, "kind": kind, "doi": clean_doi(p.get("doi", "")),
                          "authors": (p.get("authors") or [""])[0]}
        elif kind == "seed":
            nodes[key]["kind"] = "seed"
        return key

    seed_keys = [node(p, "seed") for p in seeds]
    if demo_mode:
        from . import demo
        pool = demo.load_corpus()["papers"] + demo.load_profile_dict()["works"]
        docs = [f"{p['title']} {p.get('abstract', '')}" for p in seeds + pool]
        _, m = tfidf_matrix(docs)
        sim = cosine_sim(m[:len(seeds)], m[len(seeds):])
        for i, sk in enumerate(seed_keys):
            order = sim[i].argsort()[::-1]
            added = 0
            for j in order:
                p = pool[j]
                k = node(p, "related")
                if k == sk or sim[i, j] < 0.05:
                    continue
                kind = "reference" if (p.get("year") or 0) <= (nodes[sk]["year"] or 0) else "citing"
                if nodes[k]["kind"] != "seed":
                    nodes[k]["kind"] = kind
                edges.append({"source": k, "target": sk} if kind == "reference" else {"source": k, "target": sk})
                added += 1
                if added >= per_seed:
                    break
        return {"nodes": list(nodes.values()), "edges": edges, "mode": "demo (similarity links)"}

    oa = OpenAlexClient(HTTP(settings or Settings()))
    for p, sk in zip(seeds, seed_keys):
        doi = clean_doi(p.get("doi", ""))
        try:
            w = oa.http.get(f"{oa.BASE}/works/doi:{doi}" if doi else f"{oa.BASE}/works/{p['id']}", params=oa._params())
        except Exception:
            continue
        refs = (w.get("referenced_works") or [])[:40]
        if refs:
            d = oa.http.get(f"{oa.BASE}/works", params=oa._params(
                {"filter": "openalex:" + "|".join(r.rsplit("/", 1)[-1] for r in refs), "per-page": 50,
                 "sort": "cited_by_count:desc"}))
            for rw in d.get("results", [])[:per_seed]:
                edges.append({"source": sk, "target": node(oa._to_paper(rw), "reference")})
        try:
            c = oa.http.get(f"{oa.BASE}/works", params=oa._params(
                {"filter": f"cites:{w['id'].rsplit('/', 1)[-1]}", "per-page": per_seed, "sort": "cited_by_count:desc"}))
            for cw in c.get("results", []):
                edges.append({"source": node(oa._to_paper(cw), "citing"), "target": sk})
        except Exception:
            pass
    return {"nodes": list(nodes.values()), "edges": edges, "mode": "live (OpenAlex citations)"}
