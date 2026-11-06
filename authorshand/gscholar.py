"""Google Scholar profile linking.

Google Scholar has no official API and its terms forbid automated scraping, so
Author's Hand supports three honest routes, and always shows where numbers came
from and when:

1. Automatic — through SerpApi's Google Scholar Author API (the user supplies
   their own SerpApi key; free plan available). Returns the citations / h-index /
   i10-index table, citations-per-year graph and article list.
2. Manual — the user copies the metrics box and the bar-chart values from their
   own Scholar profile into a form (takes a minute; dated "entered by you").
3. Articles — the user's own "Export" from Scholar (BibTeX / RIS) is imported.
"""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, urlparse

import requests

PROFILE_RE = re.compile(r"scholar\.google\.[a-z.]+/citations", re.I)


def author_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if PROFILE_RE.search(s):
        return (parse_qs(urlparse(s).query).get("user") or [""])[0]
    return s if re.fullmatch(r"[A-Za-z0-9_\-]{12}", s) else ""


def profile_url(aid: str) -> str:
    return f"https://scholar.google.com/citations?user={aid}&hl=en" if aid else ""


class ScholarFetchError(Exception):
    pass


def _friendly(msg: str) -> str:
    m = (msg or "").lower()
    if "invalid api key" in m or "401" in m:
        return ("SerpApi says the API key is not valid. Copy it again from serpapi.com → Dashboard → Api Key "
                "(no spaces), and check that your SerpApi e-mail and phone are verified.")
    if "run out of searches" in m or "429" in m or "limit" in m:
        return "Your SerpApi free searches for this month are used up. Use ‘Copy & paste my Scholar page’ instead."
    if "hasn't returned any results" in m or "author_id" in m or "404" in m:
        return ("Google Scholar returned no profile for that link. Check the profile URL (it must contain "
                "‘citations?user=…’) and that your Scholar profile is set to Public.")
    if "ssl" in m or "certificate" in m or "proxy" in m or "connection" in m or "timed out" in m:
        return ("Could not reach serpapi.com from this computer (internet, firewall or institute proxy). "
                "Try another network, or use ‘Copy & paste my Scholar page’.")
    return msg


def fetch_serpapi(aid: str, api_key: str, timeout: int = 40, max_pages: int = 10) -> dict:
    """Google Scholar author profile via SerpApi (engine=google_scholar_author).
    Pages through the article list (100 per page) so every paper on the profile is returned.
    Errors are turned into plain-language messages and never contain the API key."""
    api_key = (api_key or "").strip()
    aid = (aid or "").strip()
    snap, start = None, 0
    for _ in range(max_pages):
        try:
            r = requests.get("https://serpapi.com/search.json",
                             params={"engine": "google_scholar_author", "author_id": aid, "api_key": api_key,
                                     "hl": "en", "num": 100, "start": start}, timeout=timeout)
        except requests.RequestException as e:
            raise ScholarFetchError(_friendly(type(e).__name__ + ": " + str(e).replace(api_key, "***"))) from None
        try:
            d = r.json()
        except ValueError:
            d = {}
        if r.status_code >= 400 or d.get("error"):
            raise ScholarFetchError(_friendly(f"{r.status_code} {d.get('error', '')}"))
        page = parse_serpapi(d)
        if snap is None:
            snap = page
        else:
            snap["articles"] += page["articles"]
        if len(page["articles"]) < 100:
            break
        start += 100
    if not snap or not (snap.get("metrics") or snap.get("articles")):
        raise ScholarFetchError(_friendly("hasn't returned any results"))
    return snap


def parse_serpapi(d: dict) -> dict:
    if d.get("error"):
        raise ValueError(d["error"])
    a = d.get("author") or {}
    cb = d.get("cited_by") or {}
    table = {}
    for row in cb.get("table") or []:
        for metric, vals in row.items():
            since = next((k for k in vals if k.startswith("since_")), None)
            table[metric] = {"all": vals.get("all"), "since": vals.get(since) if since else None,
                             "since_year": int(since.split("_")[1]) if since else None}
    graph = {int(g["year"]): int(g.get("citations") or 0) for g in (cb.get("graph") or []) if g.get("year")}
    arts = [{"title": x.get("title", ""), "authors": [s.strip() for s in (x.get("authors") or "").split(",") if s.strip()],
             "venue": x.get("publication", ""), "year": int(x["year"]) if str(x.get("year", "")).isdigit() else None,
             "citations": (x.get("cited_by") or {}).get("value") or 0, "url": x.get("link", ""),
             "source": "Google Scholar"} for x in d.get("articles") or []]
    return {"name": a.get("name", ""), "affiliation": a.get("affiliations", ""),
            "interests": [i.get("title") for i in a.get("interests") or []], "thumbnail": a.get("thumbnail", ""),
            "metrics": table, "graph": graph, "articles": arts,
            "source": "SerpApi (Google Scholar)", "updated": time.time()}


def manual_snapshot(citations_all: int, citations_since: int, h_all: int, h_since: int, i10_all: int,
                    i10_since: int, since_year: int, graph: dict[int, int]) -> dict:
    return {"metrics": {"citations": {"all": citations_all, "since": citations_since, "since_year": since_year},
                        "h_index": {"all": h_all, "since": h_since, "since_year": since_year},
                        "i10_index": {"all": i10_all, "since": i10_since, "since_year": since_year}},
            "graph": {int(k): int(v) for k, v in graph.items() if str(k).isdigit()}, "articles": [],
            "source": "Entered by you from your Google Scholar profile", "updated": time.time()}


def parse_pasted_profile(text: str) -> dict:
    """Read the numbers from text the researcher copied from their OWN Google Scholar profile page
    (Ctrl+A, Ctrl+C on the page, then paste). Nothing is downloaded — this only parses the pasted text.
    Returns a snapshot like the other routes; missing parts are left empty for the user to fill in."""
    import re
    t = text.replace("\u00a0", " ")
    metrics = {}
    since = re.search(r"Since\s+((?:19|20)\d\d)", t)
    sy = int(since.group(1)) if since else None
    for key, label in (("citations", r"Citations"), ("h_index", r"h-index"), ("i10_index", r"i10-index")):
        m = re.search(label + r"\s+([\d,]+)\s+([\d,]+)", t)
        if m:
            metrics[key] = {"all": int(m.group(1).replace(",", "")), "since": int(m.group(2).replace(",", "")),
                            "since_year": sy}
    # graph: a run of consecutive years followed by the same number of counts
    nums = [int(x) for x in re.findall(r"(?<![\d.])(\d{1,6})(?![\d.])", t[t.find("i10-index"):] if "i10-index" in t else t)]
    graph = {}
    for i in range(len(nums)):
        run = [nums[i]]
        while i + len(run) < len(nums) and nums[i + len(run)] == run[-1] + 1 and 1950 < run[-1] < 2100:
            run.append(nums[i + len(run)])
        if len(run) >= 3 and 1950 < run[0] < 2100:
            after = nums[i + len(run): i + 2 * len(run)]
            if len(after) == len(run):
                graph = dict(zip(run, after))
            break
    # articles: blocks ending in a line "<cited-by> <year>" or "<year>"
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    arts = []
    for k, ln in enumerate(lines):
        m = re.match(r"^(?:(\d+)\*?\s+)?((?:19|20)\d\d)$", ln)
        if m and k >= 3 and "," in lines[k - 2] or (m and k >= 3 and re.search(r"(19|20)\d\d", lines[k - 1] or "")):
            title, authors, venue = lines[k - 3], lines[k - 2], lines[k - 1]
            bad = ("title", "cited by", "year", "citations", "h-index", "i10-index", "all", "since", "view all")
            if (len(title) < 12 or any(x.lower().startswith(bad) for x in (title, authors, venue))
                    or any(len(re.findall(r"[A-Za-z]", x)) < 3 for x in (title, authors, venue))):
                continue
            arts.append({"title": title, "authors": [a.strip() for a in authors.split(",") if a.strip()],
                         "venue": re.sub(r",?\s*(19|20)\d\d\s*$", "", venue).strip(),
                         "year": int(m.group(2)), "citations": int(m.group(1) or 0), "source": "Google Scholar"})
    return {"metrics": metrics, "graph": graph, "articles": arts,
            "source": "Copied from your Google Scholar page", "updated": time.time()}


DEMO_SNAPSHOT = {  # FICTIONAL numbers for the offline demo account
    "name": "A. Demo (demo)", "affiliation": "Demo Institute of Management",
    "interests": ["HR analytics", "Explainable AI", "Generative AI"],
    "metrics": {"citations": {"all": 512, "since": 431, "since_year": 2021},
                "h_index": {"all": 11, "since": 10, "since_year": 2021},
                "i10_index": {"all": 11, "since": 9, "since_year": 2021}},
    "graph": {2018: 9, 2019: 24, 2020: 37, 2021: 55, 2022: 71, 2023: 88, 2024: 109, 2025: 141, 2026: 106},
    "articles": [  # fictional Scholar counts (Scholar usually counts more citations than OpenAlex)
        {"title": "Predicting Voluntary Employee Attrition with Explainable Gradient Boosting: Evidence from Indian IT Services",
         "authors": ["R. Menon", "S. Iyer", "A. Demo"], "year": 2025, "venue": "Journal of Business Research", "citations": 19,
         "source": "Google Scholar"},
        {"title": "Learning Analytics for Early Identification of At-Risk Postgraduate Management Students",
         "authors": ["N. Reddy", "A. Demo"], "year": 2024, "venue": "Computers & Education", "citations": 27,
         "source": "Google Scholar"},
        {"title": "Explainable Credit Scoring for Thin-File Borrowers Using Alternative Data",
         "authors": ["V. Krishnan", "A. Demo", "T. Bose"], "year": 2024, "venue": "Finance Research Letters",
         "citations": 41, "source": "Google Scholar"},
        {"title": "Customer Churn Prediction in Retail Banking Using Ensemble Learning",
         "authors": ["A. Demo", "S. Iyer"], "year": 2018, "venue": "Expert Systems with Applications", "citations": 63,
         "source": "Google Scholar"},
        {"title": "HR Analytics Teaching Cases for Indian Business Schools (book chapter, fictional)",
         "authors": ["A. Demo", "K. Rao"], "year": 2023, "venue": "Handbook of People Analytics Education",
         "type": "book-chapter", "citations": 4, "source": "Google Scholar"},
    ],
    "source": "Demo data (fictional)", "updated": time.time(),
}
