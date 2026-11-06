"""Connectors to open scholarly infrastructure.

All sources below are free and need no paid key:
  * ORCID Public API v3.0      – researcher identity, works, employment, linked URLs
  * OpenAlex                    – citations, h-index, topics, co-authors, abstracts, OA links
  * Semantic Scholar Graph API  – paper search, AI TL;DRs, open-access PDFs
  * arXiv API                   – pre-prints and full-text PDFs
  * Crossref                    – authoritative DOI metadata
  * Unpaywall                   – legal open-access PDF location for a DOI
  * ResearchGate                – NO public API exists and scraping breaches its
                                   Terms of Service, so Author's Hand links the
                                   profile URL (often already listed on ORCID)
                                   and imports the researcher's own BibTeX / RIS
                                   export, then de-duplicates it against ORCID.

Every paper is normalised to one dictionary schema (see `paper()`).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Any

import requests

from .config import Settings
from .text_utils import normalize_title

ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.I)
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.I)
ARXIV_RE = re.compile(r"(?:arxiv[:/ ]|abs/|pdf/)?(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
RG_PROFILE_RE = re.compile(r"^https?://(www\.)?researchgate\.net/profile/[\w\-%.]+/?", re.I)


# --------------------------------------------------------------------------- utils
def paper(**kw) -> dict:
    """Canonical paper record used everywhere in Author's Hand."""
    base = {"id": "", "title": "", "authors": [], "year": None, "venue": "", "doi": "",
            "abstract": "", "citations": 0, "oa_pdf": "", "url": "", "source": "",
            "tldr": "", "topics": [], "type": "", "volume": "", "issue": "", "pages": "", "publisher": "",
            "place": "", "edition": "", "editors": [], "isbn": "", "issn": ""}
    base.update({k: v for k, v in kw.items() if v is not None})
    if base["doi"]:
        base["doi"] = clean_doi(base["doi"])
    return base


def clean_doi(doi: str) -> str:
    m = DOI_RE.search(doi or "")
    return m.group(1).rstrip(".,;)").lower() if m else ""


def extract_orcid(text: str) -> str:
    m = ORCID_RE.search(text or "")
    return m.group(1).upper() if m else ""


def valid_orcid(orcid: str) -> bool:
    """ISO 7064 MOD 11-2 checksum, exactly as ORCID specifies."""
    digits = (orcid or "").replace("-", "").upper()
    if not re.fullmatch(r"\d{15}[\dX]", digits):
        return False
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def reconstruct_abstract(inv: dict | None) -> str:
    """OpenAlex stores abstracts as an inverted index; rebuild the text."""
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def normalize_author(name: str) -> str:
    """'Rao, K.' -> 'K. Rao' so the same person matches across sources."""
    name = re.sub(r"\s+", " ", name or "").strip()
    if "," in name:
        last, first = [x.strip() for x in name.split(",", 1)]
        name = f"{first} {last}".strip()
    return name


class HTTP:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or Settings()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.s.user_agent})

    def get(self, url: str, params: dict | None = None, headers: dict | None = None,
            as_json: bool = True) -> Any:
        r = self.session.get(url, params=params, headers=headers, timeout=self.s.http_timeout)
        r.raise_for_status()
        return r.json() if as_json else r.content


# ---------------------------------------------------------------------- ORCID
class OrcidClient:
    BASE = "https://pub.orcid.org/v3.0"

    def __init__(self, http: HTTP | None = None):
        self.http = http or HTTP()

    def _get(self, orcid: str, part: str) -> dict:
        return self.http.get(f"{self.BASE}/{orcid}/{part}", headers={"Accept": "application/json"})

    def person(self, orcid: str) -> dict:
        d = self._get(orcid, "person")
        name = d.get("name") or {}
        given = ((name.get("given-names") or {}).get("value") or "")
        family = ((name.get("family-name") or {}).get("value") or "")
        urls = [{"name": u.get("url-name") or "", "url": (u.get("url") or {}).get("value", "")}
                for u in (d.get("researcher-urls") or {}).get("researcher-url", [])]
        ext = [{"type": e.get("external-id-type"), "value": e.get("external-id-value"),
                "url": (e.get("external-id-url") or {}).get("value", "")}
               for e in (d.get("external-identifiers") or {}).get("external-identifier", [])]
        return {
            "orcid": orcid,
            "name": f"{given} {family}".strip(),
            "biography": ((d.get("biography") or {}).get("content") or ""),
            "keywords": [k.get("content") for k in (d.get("keywords") or {}).get("keyword", [])],
            "urls": urls,
            "external_ids": ext,
            "researchgate": next((u["url"] for u in urls if "researchgate.net" in u["url"].lower()), ""),
        }

    def search(self, email: str = "", given: str = "", family: str = "", rows: int = 10) -> list[dict]:
        """Find ORCID iDs by (public) e-mail and/or name — the 'link with my e-mail' step."""
        parts = []
        if email:
            parts.append(f"email:{email}")
        if family:
            parts.append(f"family-name:{family}")
        if given:
            parts.append(f"given-names:{given}")
        if not parts:
            return []
        d = self.http.get(f"{self.BASE}/expanded-search/", params={"q": " AND ".join(parts), "rows": rows},
                          headers={"Accept": "application/json"})
        return [{"orcid": r.get("orcid-id"), "name": f"{r.get('given-names', '')} {r.get('family-names', '')}".strip(),
                 "institutions": r.get("institution-name") or []} for r in (d.get("expanded-result") or [])]

    def employments(self, orcid: str) -> list[dict]:
        d = self._get(orcid, "employments")
        out = []
        for g in d.get("affiliation-group", []):
            for s in g.get("summaries", []):
                e = s.get("employment-summary", {})
                start = ((e.get("start-date") or {}).get("year") or {}).get("value")
                out.append({"organization": (e.get("organization") or {}).get("name", ""),
                            "role": e.get("role-title") or "", "start": start})
        return out

    def works(self, orcid: str) -> list[dict]:
        d = self._get(orcid, "works")
        out = []
        for g in d.get("group", []):
            ws = g.get("work-summary") or []
            if not ws:
                continue
            w = ws[0]
            doi = ""
            for x in (w.get("external-ids") or {}).get("external-id", []):
                if (x.get("external-id-type") or "").lower() == "doi":
                    doi = x.get("external-id-value", "")
            year = ((w.get("publication-date") or {}).get("year") or {}).get("value")
            out.append(paper(
                id=f"orcid:{w.get('put-code')}",
                title=((w.get("title") or {}).get("title") or {}).get("value", ""),
                year=int(year) if year else None,
                venue=((w.get("journal-title") or {}).get("value") or ""),
                doi=doi, url=((w.get("url") or {}).get("value") or ""),
                type=w.get("type") or "", source="ORCID"))
        return out


# --------------------------------------------------------------------- OpenAlex
class OpenAlexClient:
    BASE = "https://api.openalex.org"

    def __init__(self, http: HTTP | None = None):
        self.http = http or HTTP()

    def _params(self, extra: dict | None = None) -> dict:
        p = dict(extra or {})
        if self.http.s.contact_email:
            p["mailto"] = self.http.s.contact_email
        return p

    def author_by_orcid(self, orcid: str) -> dict:
        a = self.http.get(f"{self.BASE}/authors/orcid:{orcid}", params=self._params())
        stats = a.get("summary_stats") or {}
        return {
            "openalex_id": a.get("id", "").rsplit("/", 1)[-1],
            "name": a.get("display_name", ""),
            "works_count": a.get("works_count", 0),
            "cited_by_count": a.get("cited_by_count", 0),
            "h_index": stats.get("h_index"),
            "i10_index": stats.get("i10_index"),
            "two_year_mean_citedness": stats.get("2yr_mean_citedness"),
            "counts_by_year": a.get("counts_by_year", []),
            "topics": [t.get("display_name") for t in (a.get("topics") or [])[:15]],
            "institutions": [i.get("display_name") for i in (a.get("last_known_institutions") or [])],
        }

    def _to_paper(self, w: dict) -> dict:
        loc = (w.get("primary_location") or {})
        src = (loc.get("source") or {}) or {}
        return paper(
            id=w.get("id", "").rsplit("/", 1)[-1],
            title=w.get("title") or w.get("display_name") or "",
            authors=[(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])],
            year=w.get("publication_year"), venue=src.get("display_name") or "",
            doi=w.get("doi") or "", abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
            citations=w.get("cited_by_count", 0),
            oa_pdf=(w.get("open_access") or {}).get("oa_url") or "",
            url=w.get("id", ""), source="OpenAlex", type=w.get("type") or "",
            topics=[t.get("display_name") for t in (w.get("topics") or [])[:5]],
            issn=",".join((src.get("issn") or [])[:2]),
            oa_authors=[{"id": ((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1],
                         "name": (a.get("author") or {}).get("display_name", ""),
                         "orcid": extract_orcid((a.get("author") or {}).get("orcid") or "")}
                        for a in w.get("authorships", [])])

    # ---- fallbacks when OpenAlex has no author record linked to the ORCID iD
    def works_by_orcid(self, orcid: str, max_works: int = 400) -> list[dict]:
        out, cursor = [], "*"
        while cursor and len(out) < max_works:
            d = self.http.get(f"{self.BASE}/works", params=self._params(
                {"filter": f"author.orcid:{orcid}", "per-page": 200, "cursor": cursor}))
            out += [self._to_paper(w) for w in d.get("results", [])]
            cursor = (d.get("meta") or {}).get("next_cursor")
            if not d.get("results"):
                break
        return out

    def works_by_dois(self, dois: list[str]) -> list[dict]:
        dois = [clean_doi(x) for x in dois if clean_doi(x)]
        out = []
        for i in range(0, len(dois), 40):
            chunk = dois[i:i + 40]
            d = self.http.get(f"{self.BASE}/works", params=self._params(
                {"filter": "doi:" + "|".join(chunk), "per-page": 50}))
            out += [self._to_paper(w) for w in d.get("results", [])]
        return out

    def work_by_title(self, title: str, year=None) -> dict | None:
        if len(normalize_title(title)) < 12:
            return None
        d = self.http.get(f"{self.BASE}/works", params=self._params({"search": title[:250], "per-page": 5}))
        for w in d.get("results", []):
            p = self._to_paper(w)
            if SequenceMatcher(None, normalize_title(p["title"]), normalize_title(title)).ratio() >= 0.92 and (
                    not year or not p["year"] or abs(int(p["year"]) - int(year)) <= 1):
                return p
        return None

    def author_by_id(self, aid: str) -> dict:
        a = self.http.get(f"{self.BASE}/authors/{aid}", params=self._params())
        stats = a.get("summary_stats") or {}
        return {"openalex_id": aid, "name": a.get("display_name", ""), "works_count": a.get("works_count", 0),
                "cited_by_count": a.get("cited_by_count", 0), "h_index": stats.get("h_index"),
                "i10_index": stats.get("i10_index"), "two_year_mean_citedness": stats.get("2yr_mean_citedness"),
                "counts_by_year": a.get("counts_by_year", []),
                "topics": [t.get("display_name") for t in (a.get("topics") or [])[:15]],
                "institutions": [i.get("display_name") for i in (a.get("last_known_institutions") or [])],
                "matched_by": "works"}

    def author_works(self, openalex_id: str, max_works: int = 400) -> list[dict]:
        out, cursor = [], "*"
        while cursor and len(out) < max_works:
            d = self.http.get(f"{self.BASE}/works", params=self._params(
                {"filter": f"author.id:{openalex_id}", "per-page": 200, "cursor": cursor}))
            out += [self._to_paper(w) for w in d.get("results", [])]
            cursor = (d.get("meta") or {}).get("next_cursor")
            if not d.get("results"):
                break
        return out

    def search(self, query: str, n: int = 10, from_year: int | None = None) -> list[dict]:
        p = {"search": query, "per-page": n}
        if from_year:
            p["filter"] = f"from_publication_date:{from_year}-01-01"
        d = self.http.get(f"{self.BASE}/works", params=self._params(p))
        return [self._to_paper(w) for w in d.get("results", [])]


def guess_openalex_author(works: list[dict], name: str, orcid: str = "") -> str:
    """The OpenAlex author id that appears on most of the researcher's own works (ORCID first, then name)."""
    from collections import Counter
    toks = {t for t in re.findall(r"[a-z]+", (name or "").lower()) if len(t) > 2}
    c = Counter()
    for w in works:
        for a in w.get("oa_authors") or []:
            if not a.get("id"):
                continue
            if orcid and a.get("orcid") == orcid:
                c[a["id"]] += 3
            elif toks and toks & set(re.findall(r"[a-z]+", (a.get("name") or "").lower())):
                c[a["id"]] += 1
    return c.most_common(1)[0][0] if c else ""


# ------------------------------------------------------------ Semantic Scholar
class SemanticScholarClient:
    BASE = "https://api.semanticscholar.org/graph/v1"
    FIELDS = "title,abstract,year,authors,venue,citationCount,openAccessPdf,tldr,externalIds,url"

    def __init__(self, http: HTTP | None = None):
        self.http = http or HTTP()

    def _headers(self):
        k = self.http.s.semantic_scholar_key
        return {"x-api-key": k} if k else None

    def citations_by_doi(self, dois: list[str]) -> dict:
        """{doi: citationCount} for up to 500 DOIs (one batch call)."""
        dois = [clean_doi(x) for x in dois if clean_doi(x)][:500]
        if not dois:
            return {}
        r = self.http.session.post(f"{self.BASE}/paper/batch", params={"fields": "citationCount,externalIds"},
                                   json={"ids": [f"DOI:{d}" for d in dois]}, headers=self._headers(),
                                   timeout=self.http.s.http_timeout)
        r.raise_for_status()
        out = {}
        for d, p in zip(dois, r.json()):
            if p:
                out[d] = p.get("citationCount") or 0
        return out

    def _to_paper(self, p: dict) -> dict:
        ext = p.get("externalIds") or {}
        return paper(id=p.get("paperId", ""), title=p.get("title") or "",
                     authors=[a.get("name", "") for a in p.get("authors") or []],
                     year=p.get("year"), venue=p.get("venue") or "", doi=ext.get("DOI") or "",
                     abstract=p.get("abstract") or "", citations=p.get("citationCount") or 0,
                     oa_pdf=(p.get("openAccessPdf") or {}).get("url") or "",
                     url=p.get("url") or "", tldr=(p.get("tldr") or {}).get("text") or "",
                     source="SemanticScholar")

    def search(self, query: str, n: int = 10) -> list[dict]:
        d = self.http.get(f"{self.BASE}/paper/search",
                          params={"query": query, "limit": n, "fields": self.FIELDS},
                          headers=self._headers())
        return [self._to_paper(p) for p in d.get("data", [])]

    def by_doi(self, doi: str) -> dict:
        return self._to_paper(self.http.get(f"{self.BASE}/paper/DOI:{doi}",
                                            params={"fields": self.FIELDS}, headers=self._headers()))


# ------------------------------------------------------------------------ arXiv
class ArxivClient:
    BASE = "https://export.arxiv.org/api/query"
    NS = {"a": "http://www.w3.org/2005/Atom"}

    def __init__(self, http: HTTP | None = None):
        self.http = http or HTTP()

    def _parse(self, xml_bytes: bytes) -> list[dict]:
        root = ET.fromstring(xml_bytes)
        out = []
        for e in root.findall("a:entry", self.NS):
            pdf = ""
            for link in e.findall("a:link", self.NS):
                if link.get("title") == "pdf":
                    pdf = link.get("href", "")
            aid = (e.findtext("a:id", "", self.NS) or "").rsplit("/", 1)[-1]
            out.append(paper(
                id=f"arXiv:{aid}", title=re.sub(r"\s+", " ", e.findtext("a:title", "", self.NS)).strip(),
                authors=[a.findtext("a:name", "", self.NS) for a in e.findall("a:author", self.NS)],
                year=int((e.findtext("a:published", "", self.NS) or "0000")[:4]) or None,
                abstract=re.sub(r"\s+", " ", e.findtext("a:summary", "", self.NS)).strip(),
                oa_pdf=pdf, url=f"https://arxiv.org/abs/{aid}", venue="arXiv", source="arXiv"))
        return out

    def search(self, query: str, n: int = 10) -> list[dict]:
        raw = self.http.get(self.BASE, params={"search_query": f"all:{query}", "max_results": n,
                                               "sortBy": "relevance"}, as_json=False)
        return self._parse(raw)

    def by_id(self, arxiv_id: str) -> dict:
        raw = self.http.get(self.BASE, params={"id_list": arxiv_id}, as_json=False)
        res = self._parse(raw)
        if not res:
            raise LookupError(f"arXiv id {arxiv_id} not found")
        return res[0]


# --------------------------------------------------------- Crossref / Unpaywall
class CrossrefClient:
    BASE = "https://api.crossref.org/works"

    def __init__(self, http: HTTP | None = None):
        self.http = http or HTTP()

    def by_doi(self, doi: str) -> dict:
        m = self.http.get(f"{self.BASE}/{doi}").get("message", {})
        from .citations import from_crossref
        csl = from_crossref(m)
        year = (((m.get("issued") or {}).get("date-parts") or [[None]])[0] or [None])[0]
        abstract = re.sub(r"<[^>]+>", " ", m.get("abstract") or "")
        return paper(id=f"doi:{doi}", title=(m.get("title") or [""])[0],
                     authors=[f"{a.get('given', '')} {a.get('family', '')}".strip()
                              for a in m.get("author", [])],
                     year=year, venue=(m.get("container-title") or [""])[0], doi=doi,
                     abstract=re.sub(r"\s+", " ", abstract).strip(),
                     citations=m.get("is-referenced-by-count", 0), url=m.get("URL", ""),
                     source="Crossref", type=m.get("type", ""), volume=m.get("volume", ""),
                     issue=m.get("issue", ""), pages=m.get("page", ""), publisher=m.get("publisher", ""),
                     editors=[f"{e.get('given', '')} {e.get('family', '')}".strip() for e in m.get("editor", [])],
                     csl=csl)


class UnpaywallClient:
    BASE = "https://api.unpaywall.org/v2"

    def __init__(self, http: HTTP | None = None):
        self.http = http or HTTP()

    def pdf_url(self, doi: str) -> str:
        email = self.http.s.contact_email or "authorshand@example.org"
        d = self.http.get(f"{self.BASE}/{doi}", params={"email": email})
        loc = d.get("best_oa_location") or {}
        return loc.get("url_for_pdf") or loc.get("url") or ""


# ------------------------------------------------------------------ ResearchGate
class ResearchGateLinker:
    """ResearchGate offers no public API; we never scrape it. Instead we
    (1) store/validate the profile URL (auto-detected from ORCID researcher-urls)
    (2) parse the BibTeX / RIS citations a researcher exports from ResearchGate."""

    @staticmethod
    def valid_profile_url(url: str) -> bool:
        return bool(RG_PROFILE_RE.match(url or ""))

    @staticmethod
    def parse_bibtex(text: str, source: str = "ResearchGate") -> list[dict]:
        """BibTeX → papers, keeping volume/issue/pages/editors/publisher/edition for full citations."""
        out = []
        for entry in re.split(r"\n(?=@\w+\s*\{)", "\n" + text):
            if not entry.strip().startswith("@"):
                continue
            etype = re.match(r"@(\w+)", entry.strip()).group(1).lower()

            def f(name):
                m = re.search(rf"\b{name}\s*=\s*[{{\"](.+?)[}}\"]\s*,?\s*\n", entry, re.I | re.S)
                return re.sub(r"[{}\s]+", " ", m.group(1)).strip() if m else ""
            year = re.findall(r"\d{4}", f("year"))
            typ = {"article": "journal-article", "incollection": "book-chapter", "inbook": "book-chapter",
                   "inproceedings": "proceedings-article", "conference": "proceedings-article",
                   "book": "book"}.get(etype, "journal-article")
            out.append(paper(id=f"{source[:3].lower()}:{len(out)}", title=f("title"),
                             authors=[normalize_author(a) for a in f("author").split(" and ") if a.strip()],
                             year=int(year[0]) if year else None,
                             venue=f("journal") or f("booktitle"), doi=f("doi"),
                             abstract=f("abstract"), url=f("url"), source=source, type=typ,
                             volume=f("volume"), issue=f("number"), pages=f("pages").replace("--", "-"),
                             publisher=f("publisher"), place=f("address"), edition=f("edition"),
                             isbn=f("isbn"), issn=f("issn"),
                             editors=[normalize_author(a) for a in f("editor").split(" and ") if a.strip()]))
        return [p for p in out if p["title"]]

    @staticmethod
    def parse_ris(text: str, source: str = "ResearchGate") -> list[dict]:
        out, cur = [], {}
        types = {"JOUR": "journal-article", "CHAP": "book-chapter", "CONF": "proceedings-article",
                 "CPAPER": "proceedings-article", "BOOK": "book"}
        for line in text.splitlines():
            m = re.match(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$", line)
            if not m:
                continue
            tag, val = m.group(1), m.group(2).strip()
            if tag == "ER":
                if cur.get("title"):
                    if cur.get("sp"):
                        cur["pages"] = cur.pop("sp") + (f"-{cur.pop('ep')}" if cur.get("ep") else "")
                    cur.pop("ep", None)
                    out.append(paper(id=f"{source[:3].lower()}:{len(out)}", source=source, **cur))
                cur = {}
            elif tag == "TY":
                cur["type"] = types.get(val, "journal-article")
            elif tag in ("TI", "T1"):
                cur["title"] = val
            elif tag in ("AU", "A1"):
                cur.setdefault("authors", []).append(normalize_author(val))
            elif tag in ("ED", "A2") and cur.get("type") in ("book-chapter", "proceedings-article", "book"):
                cur.setdefault("editors", []).append(normalize_author(val))
            elif tag in ("PY", "Y1", "DA") and re.search(r"\d{4}", val):
                cur["year"] = int(re.search(r"\d{4}", val).group())
            elif tag in ("JO", "JF", "T2", "BT"):
                cur["venue"] = val
            elif tag == "VL":
                cur["volume"] = val
            elif tag == "IS":
                cur["issue"] = val
            elif tag == "SP":
                cur["sp"] = val
            elif tag == "EP":
                cur["ep"] = val
            elif tag == "PB":
                cur["publisher"] = val
            elif tag == "CY":
                cur["place"] = val
            elif tag == "ET":
                cur["edition"] = val
            elif tag == "DO":
                cur["doi"] = val
            elif tag == "AB":
                cur["abstract"] = val
            elif tag == "UR":
                cur["url"] = val
        return out


def import_references(text: str, source: str = "Import") -> list[dict]:
    """Import a BibTeX or RIS export from Litmaps, ResearchRabbit, Zotero, Mendeley, ResearchGate, Scopus …"""
    return ResearchGateLinker.parse_bibtex(text, source) or ResearchGateLinker.parse_ris(text, source)


# ------------------------------------------------------------------- merging
def merge_works(*lists: list[dict]) -> list[dict]:
    """Unify works from several sources: match by DOI, else by fuzzy title
    (>= 0.92 similarity); richer fields win; provenance is kept in `sources`."""
    merged: list[dict] = []
    for lst in lists:
        for p in lst:
            match = None
            for m in merged:
                if p["doi"] and m["doi"] and p["doi"] == m["doi"]:
                    match = m
                    break
                a, b = normalize_title(p["title"]), normalize_title(m["title"])
                if a and b and SequenceMatcher(None, a, b).ratio() >= 0.92:
                    match = m
                    break
            if match is None:
                q = dict(p)
                q["sources"] = [p["source"]]
                merged.append(q)
            else:
                for k, v in p.items():
                    if k in ("source",):
                        continue
                    if (not match.get(k)) and v:
                        match[k] = v
                    elif k == "citations":
                        match[k] = max(match.get(k) or 0, v or 0)
                if p["source"] not in match["sources"]:
                    match["sources"].append(p["source"])
    return merged


def search_all(query: str, n: int = 8, settings: Settings | None = None) -> list[dict]:
    """Federated search over OpenAlex + Semantic Scholar + arXiv (failures tolerated)."""
    http = HTTP(settings)
    results, errors = [], []
    for client in (OpenAlexClient(http), SemanticScholarClient(http), ArxivClient(http)):
        try:
            results.append(client.search(query, n))
        except Exception as e:
            errors.append(f"{type(client).__name__}: {e}")
    merged = merge_works(*results) if results else []
    merged.sort(key=lambda p: (p.get("citations") or 0), reverse=True)
    if not merged and errors:
        raise ConnectionError("; ".join(errors))
    return merged


def fetch_fulltext(p: dict, settings: Settings | None = None) -> str:
    """Download and read the open-access PDF if one exists, else fall back to the abstract."""
    from .pdf_reader import read_pdf
    http = HTTP(settings)
    url = p.get("oa_pdf") or ""
    if not url and p.get("doi"):
        try:
            url = UnpaywallClient(http).pdf_url(p["doi"])
        except Exception:
            url = ""
    if url:
        try:
            content = http.get(url, as_json=False)
            if content[:4] == b"%PDF":
                return read_pdf(content)
        except Exception:
            pass
    return f"{p.get('title', '')}\n\nAbstract: {p.get('abstract', '')}"


def resolve_identifier(text: str, settings: Settings | None = None) -> dict:
    """Turn a DOI / arXiv id / title into a paper record."""
    http = HTTP(settings)
    doi = clean_doi(text)
    if doi:
        for fn in (lambda: SemanticScholarClient(http).by_doi(doi), lambda: CrossrefClient(http).by_doi(doi)):
            try:
                p = fn()
                if p["title"]:
                    return p
            except Exception:
                continue
    m = ARXIV_RE.search(text)
    if m and ("arxiv" in text.lower() or re.fullmatch(r"\s*\d{4}\.\d{4,5}(v\d+)?\s*", text)):
        return ArxivClient(http).by_id(m.group(1))
    res = search_all(text, n=3, settings=settings)
    if not res:
        raise LookupError("Paper not found")
    return res[0]

