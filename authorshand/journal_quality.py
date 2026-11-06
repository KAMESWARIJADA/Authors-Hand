"""Rapid Journal Quality Check: one transparent score from open sources plus the
researcher's own indexing lists (Scopus, WoS, ABDC, UGC-CARE … as CSV/XLSX).

Signals: OpenAlex source metrics (h-index, 2-year mean citedness ≈ impact-factor
proxy, output history, APC, DOAJ flag), DOAJ API, Crossref journal record, and
membership/rating in uploaded lists. Red flags follow Think.Check.Submit-style
heuristics. The score supports — never replaces — a reviewer's judgement.
"""
from __future__ import annotations

import json
import time
import re
from pathlib import Path

import pandas as pd

from .config import Settings
from .connectors import HTTP
from .text_utils import normalize_title

ISSN_RE = re.compile(r"\b(\d{4}-\d{3}[\dXx])\b")
DEMO_FILE = Path(__file__).resolve().parent.parent / "demo_data" / "journals_demo.json"


def _norm_issn(s: str) -> str:
    s = re.sub(r"[^0-9Xx]", "", str(s or "")).upper()
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else ""


def load_list(file_or_df, name: str) -> dict:
    """Read an indexing list (CSV/XLSX). Detects ISSN, title and rating/quartile columns."""
    df = file_or_df if isinstance(file_or_df, pd.DataFrame) else (
        pd.read_excel(file_or_df) if str(getattr(file_or_df, "name", file_or_df)).lower().endswith(("xlsx", "xls"))
        else pd.read_csv(file_or_df))
    cols = {c.lower(): c for c in df.columns}
    issn_cols = [cols[c] for c in cols if "issn" in c]
    title_col = next((cols[c] for c in cols if c in ("title", "journal title", "journal", "source title", "journal name")), None)
    rating_col = next((cols[c] for c in cols if any(k in c for k in ("rating", "quartile", "rank", "category", "group"))), None)
    index = {}
    for _, row in df.iterrows():
        rating = str(row[rating_col]) if rating_col and pd.notna(row[rating_col]) else "listed"
        for c in issn_cols:
            for part in str(row[c]).split(","):
                n = _norm_issn(part)
                if n:
                    index[n] = rating
        if title_col and pd.notna(row[title_col]):
            index["t:" + normalize_title(str(row[title_col]))] = rating
    return {"name": name, "index": index, "size": len(df)}


class JournalChecker:
    def __init__(self, settings: Settings | None = None, demo_mode: bool = False, lists: list[dict] | None = None):
        self.s = settings or Settings()
        self.demo = demo_mode
        self.lists = lists or []
        self.http = HTTP(self.s)

    # --------------------------------------------------------------- lookups
    def _openalex(self, q: str) -> dict | None:
        issn = ISSN_RE.search(q)
        params = {"filter": f"issn:{issn.group(1)}"} if issn else {"search": q}
        params["per-page"] = 1
        if self.s.contact_email:
            params["mailto"] = self.s.contact_email
        d = self.http.get("https://api.openalex.org/sources", params=params)
        return (d.get("results") or [None])[0]

    def _doaj(self, issn: str) -> bool | None:
        try:
            d = self.http.get(f"https://doaj.org/api/search/journals/issn:{issn}")
            return d.get("total", 0) > 0
        except Exception:
            return None

    def _crossref(self, issn: str) -> dict | None:
        try:
            return self.http.get(f"https://api.crossref.org/journals/{issn}").get("message")
        except Exception:
            return None

    def _demo(self, q: str) -> dict | None:
        data = json.loads(DEMO_FILE.read_text(encoding="utf-8"))["journals"]
        ql = q.lower()
        return next((j for j in data if ql in j["display_name"].lower() or ql in j.get("issn", [])), None)

    # ------------------------------------------------------------------ check
    def check(self, query: str) -> dict:
        src = self._demo(query) if self.demo else self._openalex(query)
        if not src:
            return {"found": False, "query": query,
                    "message": "Journal not found" + (" in the demo data — switch to Live mode." if self.demo else ".")}
        issns = src.get("issn") or ([src["issn_l"]] if src.get("issn_l") else [])
        issn = issns[0] if issns else ""
        stats = src.get("summary_stats") or {}
        cby = sorted(src.get("counts_by_year") or [], key=lambda r: r["year"])
        years = [r["year"] for r in cby if r.get("works_count")]
        if self.demo:
            doaj, xref = src.get("_doaj"), src.get("_crossref")
        else:
            doaj = self._doaj(issn) if issn else None
            xref = self._crossref(issn) if issn else None
        if doaj is None:
            doaj = bool(src.get("is_in_doaj"))
        listed = []
        for L in self.lists:
            hit = next((L["index"][n] for n in [_norm_issn(i) for i in issns] if n in L["index"]), None) \
                or L["index"].get("t:" + normalize_title(src.get("display_name", "")))
            listed.append({"list": L["name"], "status": hit or "not listed"})

        h, cit = stats.get("h_index") or 0, stats.get("2yr_mean_citedness") or 0
        age = (max(years) - min(years) + 1) if years else 0
        checks, flags = [], []
        score = 0

        checked = time.strftime("%Y-%m-%d %H:%M")

        def add(label, pts, ok, detail="", source="OpenAlex"):
            nonlocal score
            score += pts if ok else 0
            checks.append({"check": label, "passed": bool(ok), "points": pts if ok else 0, "max": pts,
                           "detail": detail, "data source": ("Demo data (fictional)" if self.demo else source),
                           "checked": checked})

        add("Indexed in OpenAlex with ≥ 5 years of output", 15, age >= 5, f"{age} active years")
        add("Journal h-index ≥ 20", 15, h >= 20, f"h-index {h}")
        add("2-year mean citedness ≥ 1.0 (impact-factor proxy)", 15, cit >= 1.0, f"{cit:.2f}")
        is_oa = bool(src.get("is_oa"))
        add("Open-access journal listed in DOAJ (or subscription journal)", 15, (doaj or not is_oa),
            "in DOAJ" if doaj else ("subscription" if not is_oa else "OA but not in DOAJ"), "DOAJ + OpenAlex")
        add("Registered with Crossref (DOIs deposited)", 10, bool(xref),
            f"{(xref or {}).get('counts', {}).get('total-dois', 0)} DOIs" if xref else "no Crossref record", "Crossref")
        add("Publisher identified with a home page", 10, bool(src.get("host_organization_name") and src.get("homepage_url")),
            src.get("host_organization_name") or "unknown")
        good_lists = [x for x in listed if x["status"] != "not listed"]
        add("Found in your indexing lists (Scopus / WoS / ABDC / UGC-CARE …)", 20, bool(good_lists),
            ", ".join(f"{x['list']}: {x['status']}" for x in good_lists) or ("no lists loaded" if not listed else "not listed"),
            "Your uploaded lists")

        recent = [r["works_count"] for r in cby[-4:-1]] if len(cby) >= 4 else []
        last_full = cby[-2]["works_count"] if len(cby) >= 2 else 0
        if recent and last_full > 3 * max(1, sum(recent[:-1]) / max(1, len(recent[:-1]))):
            flags.append("Sudden output surge (> 3× the previous years) — a common paper-mill pattern.")
        if is_oa and src.get("apc_usd") and not doaj:
            flags.append(f"Charges an APC (US${src['apc_usd']}) but is not listed in DOAJ.")
        if (src.get("works_count") or 0) > 3000 and cit < 0.5:
            flags.append("Very high volume with very low citation impact.")
        if age and age < 3:
            flags.append("Journal is less than 3 years old — little track record.")
        score = max(0, score - 10 * len(flags))
        verdict = ("Looks reputable", "green") if score >= 70 else (("Verify further", "amber") if score >= 45
                                                                    else ("High risk — avoid unless verified", "red"))
        q = quote(src.get("display_name", ""))
        return {
            "checked": checked,
            "explanation": ("The score adds points for transparent, verifiable signals (indexing, citation impact, DOAJ, "
                            "Crossref, publisher identity, your institution's lists) and subtracts 10 per red flag. "
                            "It is a screening aid, not a universal measure of journal quality: disciplines differ, and "
                            "your institution's approved list (e.g. UGC-CARE, ABDC, Scopus) should decide."),
            "found": True, "name": src.get("display_name"), "issn": issns, "publisher": src.get("host_organization_name"),
            "homepage": src.get("homepage_url"), "is_oa": is_oa, "apc_usd": src.get("apc_usd"), "in_doaj": doaj,
            "h_index": h, "two_year_citedness": cit, "works_count": src.get("works_count"),
            "cited_by_count": src.get("cited_by_count"), "active_years": age,
            "output_by_year": {r["year"]: r["works_count"] for r in cby},
            "lists": listed, "checks": checks, "red_flags": flags, "score": score,
            "verdict": verdict[0], "colour": verdict[1], "demo": self.demo,
            "links": {"SCImago (SJR, quartile)": f"https://www.scimagojr.com/journalsearch.php?q={issn or q}",
                      "WoS Master Journal List": "https://mjl.clarivate.com",
                      "Scopus Sources": "https://www.scopus.com/sources", "UGC-CARE": "https://ugccare.unipune.ac.in",
                      "ABDC list": "https://abdc.edu.au/abdc-journal-quality-list/",
                      "Think. Check. Submit.": "https://thinkchecksubmit.org"},
        }


def quote(s: str) -> str:
    from urllib.parse import quote_plus
    return quote_plus(s or "")
