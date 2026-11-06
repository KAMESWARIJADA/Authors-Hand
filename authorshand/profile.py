"""Researcher Intelligence: an ORCID-anchored, multi-source research profile.

From one ORCID iD (+ optional ResearchGate link/export) Author's Hand builds:
  * a de-duplicated publication list (ORCID ∪ OpenAlex ∪ ResearchGate export)
  * bibliometrics (citations, h-index, i10-index, yearly output & impact)
  * research themes (clustered) with momentum (rising / steady / fading)
  * co-author network and venue profile
  * a Profile-Health audit (ORCID completeness, DOIs, open-access visibility)
  * cross-theme research-gap opportunities and next-paper ideas
"""
from __future__ import annotations

import re

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from itertools import combinations

import numpy as np

from .config import Settings
from .connectors import (HTTP, OpenAlexClient, OrcidClient, ResearchGateLinker, merge_works,
                         valid_orcid)
from .llm import LLM
from .text_utils import cosine_sim, tfidf_matrix, top_keywords


@dataclass
class ResearcherProfile:
    orcid: str
    name: str = ""
    biography: str = ""
    keywords: list = field(default_factory=list)
    researchgate: str = ""
    urls: list = field(default_factory=list)
    employments: list = field(default_factory=list)
    institutions: list = field(default_factory=list)
    works: list = field(default_factory=list)
    openalex: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)       # information, not problems (shown quietly)

    # --------------------------------------------------------------- builders
    @classmethod
    def from_orcid(cls, orcid: str, settings: Settings | None = None, researchgate_url: str = "",
                   researchgate_export: str = "", openalex_id: str = "") -> "ResearcherProfile":
        if not valid_orcid(orcid):
            raise ValueError(f"'{orcid}' is not a valid ORCID iD (checksum failed).")
        http = HTTP(settings)
        oc, oa = OrcidClient(http), OpenAlexClient(http)
        prof = cls(orcid=orcid)
        orcid_works, oa_works, rg_works = [], [], []
        try:
            person = oc.person(orcid)
            prof.name, prof.biography = person["name"], person["biography"]
            prof.keywords, prof.urls = person["keywords"], person["urls"]
            prof.researchgate = person["researchgate"]
            prof.employments = oc.employments(orcid)
            orcid_works = oc.works(orcid)
        except Exception as e:
            prof.warnings.append(f"ORCID unavailable: {e}")
        oa_error = None
        try:
            prof.openalex = oa.author_by_orcid(orcid)
            prof.name = prof.name or prof.openalex["name"]
            prof.institutions = prof.openalex.get("institutions", [])
            oa_works = oa.author_works(prof.openalex["openalex_id"])
        except Exception as e:
            oa_error = e
        if not prof.openalex and openalex_id:
            # OpenAlex author id remembered from an earlier lookup — fast and exact
            try:
                prof.openalex = oa.author_by_id(openalex_id)
                prof.openalex["matched_by"] = "saved"
                prof.institutions = prof.openalex.get("institutions", [])
                oa_works = oa.author_works(openalex_id)
                prof.notes.append(f"OpenAlex author record {openalex_id} (saved for your account) is used for "
                                  "citations, because OpenAlex has not yet linked it to your ORCID iD.")
            except Exception:
                prof.openalex = {}
        if not prof.openalex:
            oa_works, note = cls._openalex_fallback(oa, orcid, prof.name, orcid_works, http)
            prof.openalex = note.pop("author", {}) or {}
            if prof.openalex:
                prof.institutions = prof.openalex.get("institutions", [])
            (prof.notes if prof.openalex else prof.warnings).append(
                "OpenAlex has no author profile linked to this ORCID iD"
                + (f" ({oa_error})" if oa_error and "404" not in str(oa_error) else "")
                + f". Citations were looked up paper by paper instead: {note['summary']}. "
                  "To link it permanently, add your ORCID iD to your OpenAlex author profile "
                  "(openalex.org → search your name → ‘Request changes’) or keep your DOIs complete in ORCID.")
        if researchgate_url:
            if ResearchGateLinker.valid_profile_url(researchgate_url):
                prof.researchgate = researchgate_url
            else:
                prof.warnings.append("ResearchGate URL not recognised (expected researchgate.net/profile/…)")
        if researchgate_export:
            rg_works = (ResearchGateLinker.parse_bibtex(researchgate_export)
                        or ResearchGateLinker.parse_ris(researchgate_export))
        prof.works = merge_works(orcid_works, oa_works, rg_works)
        return prof

    @staticmethod
    def _openalex_fallback(oa, orcid: str, name: str, orcid_works: list[dict], http) -> tuple[list[dict], dict]:
        """Find the researcher's works in OpenAlex without an author record: by ORCID on the works, by DOI,
        by exact title; then citation counts for the rest from Semantic Scholar."""
        from .connectors import SemanticScholarClient, guess_openalex_author
        found, how = [], []
        try:
            w = oa.works_by_orcid(orcid)
            if w:
                found += w
                how.append(f"{len(w)} by ORCID on the papers")
        except Exception:
            pass
        have = {x["doi"] for x in found if x.get("doi")}
        dois = [w["doi"] for w in orcid_works if w.get("doi") and w["doi"] not in have]
        if dois:
            try:
                w = oa.works_by_dois(dois)
                found += w
                how.append(f"{len(w)} of {len(dois)} by DOI")
            except Exception:
                pass
        have = {x["doi"] for x in found if x.get("doi")}
        no_doi = [w for w in orcid_works if not w.get("doi") or w["doi"] not in have][:30]
        n_title = 0
        for w in no_doi:
            try:
                m = oa.work_by_title(w["title"], w.get("year"))
            except Exception:
                m = None
            if m:
                found.append(m)
                n_title += 1
        if n_title:
            how.append(f"{n_title} by exact title")
        note = {"author": {}}
        aid = guess_openalex_author(found, name, orcid)
        if aid:
            try:
                note["author"] = oa.author_by_id(aid)
                more = oa.author_works(aid)
                found += more
                how.append(f"author record {aid} found through your papers")
            except Exception:
                pass
        # Semantic Scholar citation counts for DOIs still without a match
        have = {x["doi"] for x in found if x.get("doi")}
        rest = [w for w in orcid_works if w.get("doi") and w["doi"] not in have]
        if rest:
            try:
                cc = SemanticScholarClient(http).citations_by_doi([w["doi"] for w in rest])
                for w in rest:
                    if w["doi"] in cc:
                        w["citations"] = max(w.get("citations") or 0, cc[w["doi"]])
                if cc:
                    how.append(f"{len(cc)} citation counts from Semantic Scholar")
            except Exception:
                pass
        note["summary"] = "; ".join(how) or "no matches found (the papers may not be indexed yet)"
        return found, note

    @classmethod
    def from_dict(cls, d: dict) -> "ResearcherProfile":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        prof = cls(**known)
        for w in prof.works:
            w.setdefault("sources", [w.get("source", "")])
        return prof

    def add_researchgate_export(self, text: str) -> int:
        rg = ResearchGateLinker.parse_bibtex(text) or ResearchGateLinker.parse_ris(text)
        before = len(self.works)
        self.works = merge_works(self.works, rg)
        return len(self.works) - before

    # ------------------------------------------------------------- analytics
    def metrics(self) -> dict:
        cites = sorted([w.get("citations") or 0 for w in self.works], reverse=True)
        h = sum(1 for i, c in enumerate(cites, 1) if c >= i)
        years = [w["year"] for w in self.works if w.get("year")]
        oa = self.openalex or {}
        return {
            "works": len(self.works),
            "citations": max(int(sum(cites)), int(oa.get("cited_by_count") or 0)),
            "h_index": max(h, int(oa.get("h_index") or 0)),
            "i10_index": max(sum(1 for c in cites if c >= 10), int(oa.get("i10_index") or 0)),
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
            "open_access_share": round(np.mean([bool(w.get("oa_pdf")) for w in self.works]), 2) if self.works else 0,
            "with_doi_share": round(np.mean([bool(w.get("doi")) for w in self.works]), 2) if self.works else 0,
        }

    def output_by_year(self) -> dict:
        c = Counter(w["year"] for w in self.works if w.get("year"))
        return dict(sorted(c.items()))

    def citations_by_year(self) -> dict:
        cby = (self.openalex or {}).get("counts_by_year") or []
        return {r["year"]: r.get("cited_by_count", 0) for r in sorted(cby, key=lambda r: r["year"])}

    def venues(self, n: int = 10) -> list[tuple]:
        return Counter(w["venue"] for w in self.works if w.get("venue")).most_common(n)

    def coauthors(self, n: int = 15) -> list[tuple]:
        me = self._name_tokens()
        c = Counter()
        for w in self.works:
            for a in w.get("authors") or []:
                if not (self._toks(a) & me):
                    c[a] += 1
        return c.most_common(n)

    def coauthor_graph(self):
        import networkx as nx
        g = nx.Graph()
        me = self.name or "Me"
        g.add_node(me, kind="self")
        mine = self._name_tokens()
        for w in self.works:
            others = [a for a in (w.get("authors") or []) if not (self._toks(a) & mine)]
            for a in others:
                g.add_node(a, kind="coauthor")
                g.add_edge(me, a, weight=g.get_edge_data(me, a, {"weight": 0})["weight"] + 1)
            for a, b in combinations(others, 2):
                g.add_edge(a, b, weight=g.get_edge_data(a, b, {"weight": 0})["weight"] + 1)
        return g

    def _name_tokens(self) -> set:
        toks = {t for t in re.findall(r"[a-z]+", self.name.lower()) if len(t) > 2}
        return toks or {"__self__"}

    @staticmethod
    def _toks(author: str) -> set:
        return set(re.findall(r"[a-z]+", author.lower()))

    def themes(self, k: int | None = None) -> list[dict]:
        """Cluster works into research themes and measure each theme's momentum."""
        docs = [f"{w['title']}. {w.get('abstract', '')} {' '.join(w.get('topics') or [])}" for w in self.works]
        if len(docs) < 3:
            return [{"theme": ", ".join(top_keywords(docs, 3)), "works": len(docs), "momentum": "n/a",
                     "titles": [w["title"] for w in self.works]}] if docs else []
        from sklearn.cluster import KMeans
        vec, m = tfidf_matrix(docs)
        k = k or max(2, min(5, len(docs) // 3))
        km = KMeans(n_clusters=k, n_init=10, random_state=42).fit(m)
        terms = vec.get_feature_names_out()
        last = max((w.get("year") or 0) for w in self.works)
        out = []
        for c in range(k):
            idx = np.where(km.labels_ == c)[0]
            if not len(idx):
                continue
            centre = km.cluster_centers_[c]
            label_terms, seen = [], []
            for t in centre.argsort()[::-1]:
                term = terms[t]
                if any(term in s or s in term for s in seen):
                    continue
                seen.append(term)
                label_terms.append(term)
                if len(label_terms) == 3:
                    break
            yrs = [self.works[i].get("year") or 0 for i in idx]
            recent = sum(1 for y in yrs if y >= last - 2) / len(yrs)
            momentum = "rising" if recent >= 0.6 else ("steady" if recent >= 0.3 else "fading")
            out.append({"theme": ", ".join(label_terms), "works": len(idx), "momentum": momentum,
                        "recent_share": round(recent, 2),
                        "citations": int(sum(self.works[i].get("citations") or 0 for i in idx)),
                        "titles": [self.works[i]["title"] for i in idx]})
        return sorted(out, key=lambda t: -t["works"])

    def health_audit(self) -> dict:
        """Profile-Health score: how discoverable & complete is this researcher online?"""
        checks = [
            ("ORCID biography present", bool(self.biography)),
            ("ORCID keywords present", bool(self.keywords)),
            ("Employment listed on ORCID", bool(self.employments)),
            ("ResearchGate profile linked", bool(self.researchgate)),
            ("≥ 80% of works carry a DOI", self.metrics()["with_doi_share"] >= 0.8 if self.works else False),
            ("≥ 50% of works open access", self.metrics()["open_access_share"] >= 0.5 if self.works else False),
            ("Published in the last 2 years",
             (self.metrics()["last_year"] or 0) >= date.today().year - 2),
            ("Works abstract available (≥ 50%)",
             bool(self.works) and np.mean([bool(w.get("abstract")) for w in self.works]) >= 0.5),
        ]
        fixes = {
            "ORCID biography present": "Add a 3–4 line biography on orcid.org → your record → Biography.",
            "ORCID keywords present": "Add 5–8 keywords on ORCID so indexers classify you correctly.",
            "Employment listed on ORCID": "Add your current employer under Employment on ORCID.",
            "ResearchGate profile linked": "Add your ResearchGate URL under 'Websites & social links' on ORCID.",
            "≥ 80% of works carry a DOI": "Attach DOIs to works (ORCID → Works → Add → Search & link: Crossref).",
            "≥ 50% of works open access": "Deposit accepted manuscripts in a repository/Zenodo to raise visibility.",
            "Published in the last 2 years": "Plan a near-term submission to keep the profile active.",
            "Works abstract available (≥ 50%)": "Ensure publishers deposit abstracts with Crossref, or add them on ResearchGate.",
        }
        passed = [c for c, ok in checks if ok]
        return {"score": round(100 * len(passed) / len(checks)),
                "checks": [{"check": c, "passed": bool(ok)} for c, ok in checks],
                "fixes": [fixes[c] for c, ok in checks if not ok]}

    def gap_opportunities(self, top_n: int = 3) -> list[dict]:
        """Pairs of the researcher's own themes that have never been combined in one paper —
        a personalised source of novel, defensible research ideas."""
        th = self.themes()
        if len(th) < 2:
            return []
        docs = [f"{w['title']}. {w.get('abstract', '')}" for w in self.works]
        vec, m = tfidf_matrix(docs + [t["theme"] for t in th])
        W, T = m[:len(docs)], m[len(docs):]
        sim = cosine_sim(W, T)  # work x theme
        out = []
        for i, j in combinations(range(len(th)), 2):
            overlap = int(np.sum((sim[:, i] > 0.05) & (sim[:, j] > 0.05)))
            out.append({"theme_a": th[i]["theme"], "theme_b": th[j]["theme"], "papers_bridging": overlap,
                        "idea": f"Apply your work on “{th[i]['theme']}” to the problem space of “{th[j]['theme']}”."})
        return sorted(out, key=lambda x: x["papers_bridging"])[:top_n]

    def next_paper_ideas(self, llm: LLM | None = None, n: int = 3) -> list[str]:
        gaps = self.gap_opportunities(n)
        if llm and llm.available:
            try:
                ideas = llm.generate_json(
                    f"A researcher's themes: {[t['theme'] for t in self.themes()]}. Under-explored theme "
                    f"intersections: {gaps}. Recent titles: {[w['title'] for w in self.works[:15]]}. "
                    f"Propose {n} specific, publishable paper ideas (title + one-line design). JSON list of strings.")
                if isinstance(ideas, list):
                    return [str(i) for i in ideas][:n]
            except Exception:
                pass
        return [g["idea"] for g in gaps]

    def recommend_venues(self, manuscript: str, candidates: list[dict] | None = None, n: int = 5) -> list[dict]:
        """Rank journals by how similar their papers are to a manuscript abstract.
        Uses the researcher's own record plus any candidate papers (e.g. from a live search)."""
        pool = [w for w in (self.works + (candidates or [])) if w.get("venue")]
        if not pool:
            return []
        docs = [f"{w['title']}. {w.get('abstract', '')}" for w in pool]
        vec, m = tfidf_matrix(docs + [manuscript])
        sims = cosine_sim(m[-1], m[:-1]).ravel()
        score = Counter()
        for w, s in zip(pool, sims):
            score[w["venue"]] += float(s)
        own = Counter(w["venue"] for w in self.works if w.get("venue"))
        return [{"venue": v, "fit": round(s, 3), "you_published_here": own.get(v, 0)}
                for v, s in score.most_common(n) if s > 0]

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}
