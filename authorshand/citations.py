"""Full-fidelity citations: CSL-JSON records + reference formatting in many styles.

* Records keep every bibliographic field a style can need — all authors AND
  editors, container, volume, issue, pages / article number, edition,
  publisher, place, conference, ISBN/ISSN, DOI, URL, accessed date.
* Built-in formatters (work offline): APA 7, MLA 9, Chicago 17 author-date,
  Chicago 17 notes-bibliography, Harvard (Cite Them Right), IEEE, Vancouver,
  AMA 11, Nature — for journal articles, books, edited books, chapters,
  conference papers, reports, theses, preprints and web pages.
* Live formatter: any of the 10,000+ CSL styles (Elsevier, Springer, Emerald,
  SAGE, Taylor & Francis, AOM …) through DOI content negotiation.
* Output as Markdown (italics kept), HTML (paste into Word keeps styling),
  plain text, DOCX, BibTeX, RIS and EndNote.
"""
from __future__ import annotations

import re
from datetime import date

import requests

STYLES = {
    "apa": "APA 7th", "mla": "MLA 9th", "chicago-ad": "Chicago 17th (author-date)",
    "chicago-nb": "Chicago 17th (notes-bibliography)", "harvard": "Harvard (Cite Them Right)",
    "ieee": "IEEE", "vancouver": "Vancouver", "ama": "AMA 11th", "nature": "Nature",
}
# popular journal/publisher CSL styles reachable through the live formatter
LIVE_STYLES = {
    "elsevier-harvard": "Elsevier – Harvard", "springer-basic-author-date": "Springer – author-date",
    "taylor-and-francis-chicago-author-date": "Taylor & Francis – Chicago AD",
    "emerald-harvard": "Emerald – Harvard", "sage-harvard": "SAGE – Harvard",
    "academy-of-management-review": "Academy of Management", "american-psychological-association": "APA (CSL)",
    "ieee": "IEEE (CSL)", "vancouver": "Vancouver (CSL)", "modern-language-association": "MLA (CSL)",
    "harvard-cite-them-right": "Harvard CTR (CSL)", "nature": "Nature (CSL)",
}

CROSSREF_TYPES = {"journal-article": "article-journal", "book-chapter": "chapter", "book-section": "chapter",
                  "proceedings-article": "paper-conference", "book": "book", "edited-book": "book",
                  "monograph": "book", "reference-book": "book", "report": "report", "dissertation": "thesis",
                  "posted-content": "article", "dataset": "dataset", "journal-issue": "article-journal"}


# ======================================================================= records
def _person(name) -> dict:
    if isinstance(name, dict):
        return {"family": name.get("family", "") or name.get("name", ""), "given": name.get("given", "")}
    name = (name or "").strip()
    if "," in name:
        fam, giv = [x.strip() for x in name.split(",", 1)]
    else:
        parts = name.split()
        fam, giv = (parts[-1], " ".join(parts[:-1])) if len(parts) > 1 else (name, "")
    return {"family": fam, "given": giv}


def from_paper(p: dict) -> dict:
    """Build a CSL-JSON record from Author's Hand's simple paper dict (keeps any rich fields present)."""
    if p.get("csl") and not p.get("csl_stale"):
        rec = dict(p["csl"])
        if p.get("notes"):
            rec["note"] = p["notes"]
        if p.get("tags"):
            rec["keyword"] = p["tags"]
        return rec
    typ = {"journal-article": "article-journal", "book-chapter": "chapter", "book": "book",
           "proceedings-article": "paper-conference", "dissertation": "thesis", "thesis": "thesis",
           "report": "report", "posted-content": "article", "preprint": "article", "dataset": "dataset",
           "grey": "report", "webpage": "webpage", "case-study": "report", "working-paper": "report",
           "patent": "report", "conference-abstract": "paper-conference", "poster": "paper-conference",
           "edited-book": "book", "magazine-article": "article-magazine"}.get(p.get("type", ""), "article-journal")
    if p.get("venue", "").lower() == "arxiv":
        typ = "article"
    rec = {"id": p.get("id") or p.get("doi") or p.get("title", "")[:30], "type": typ,
           "title": p.get("title", ""), "author": [_person(a) for a in p.get("authors") or []],
           "container-title": p.get("venue", ""), "issued": {"date-parts": [[p["year"]]]} if p.get("year") else {},
           "DOI": p.get("doi", ""), "URL": p.get("url", "")}
    for k_src, k_csl in (("volume", "volume"), ("issue", "issue"), ("pages", "page"), ("publisher", "publisher"),
                         ("place", "publisher-place"), ("edition", "edition"), ("isbn", "ISBN"), ("issn", "ISSN")):
        if p.get(k_src):
            rec[k_csl] = p[k_src]
    if p.get("editors"):
        rec["editor"] = [_person(e) for e in p["editors"]]
    if p.get("notes"):
        rec["note"] = p["notes"]
    if p.get("tags"):
        rec["keyword"] = p["tags"]
    if p.get("genre"):
        rec["genre"] = p["genre"]
    return {k: v for k, v in rec.items() if v not in ("", [], {}, None)}


def from_crossref(m: dict) -> dict:
    """CSL-JSON from a Crossref /works message (authors, editors, pages, publisher …)."""
    def people(key):
        return [{"family": a.get("family", a.get("name", "")), "given": a.get("given", "")} for a in m.get(key, [])]
    dp = ((m.get("issued") or m.get("published-print") or m.get("published-online") or {}).get("date-parts") or [[None]])[0]
    rec = {"id": m.get("DOI", ""), "type": CROSSREF_TYPES.get(m.get("type", ""), "article-journal"),
           "title": (m.get("title") or [""])[0], "author": people("author"), "editor": people("editor"),
           "container-title": (m.get("container-title") or [""])[0],
           "collection-title": (m.get("series-title") or [""])[0] if m.get("series-title") else "",
           "volume": m.get("volume", ""), "issue": m.get("issue", ""), "page": m.get("page", ""),
           "number": m.get("article-number", ""), "publisher": m.get("publisher", ""),
           "publisher-place": m.get("publisher-location", ""), "edition": str(m.get("edition-number", "") or ""),
           "ISBN": (m.get("ISBN") or [""])[0], "ISSN": (m.get("ISSN") or [""])[0],
           "event": (m.get("event") or {}).get("name", "") if isinstance(m.get("event"), dict) else "",
           "issued": {"date-parts": [[x for x in dp if x]]} if dp and dp[0] else {},
           "DOI": m.get("DOI", ""), "URL": m.get("URL", "")}
    return {k: v for k, v in rec.items() if v not in ("", [], {}, None)}


def fetch_csl(doi: str, timeout: int = 20) -> dict:
    """Full CSL-JSON for a DOI via content negotiation (works for Crossref, DataCite, mEDRA DOIs)."""
    r = requests.get(f"https://doi.org/{doi}", headers={"Accept": "application/vnd.citationstyles.csl+json"},
                     timeout=timeout)
    r.raise_for_status()
    d = r.json()
    for k in ("author", "editor"):
        d[k] = [{"family": a.get("family", a.get("literal", "")), "given": a.get("given", "")} for a in d.get(k, [])]
    return {k: v for k, v in d.items() if v not in ("", [], {}, None)}


def format_live(doi: str, style: str = "apa", locale: str = "en-GB", timeout: int = 20) -> str:
    """Format with ANY CSL style id (citationstyles.org) through doi.org content negotiation."""
    r = requests.get(f"https://doi.org/{doi}",
                     headers={"Accept": f"text/x-bibliography; style={style}; locale={locale}"}, timeout=timeout)
    r.raise_for_status()
    return r.content.decode("utf-8").strip()


# ====================================================================== helpers
def _year(r):
    dp = (r.get("issued") or {}).get("date-parts") or [[None]]
    return dp[0][0] if dp and dp[0] else None


def _initials(given: str, dots=True, space=True) -> str:
    parts = [p for p in re.split(r"[\s\-]+", given or "") if p]
    out = []
    for p in parts:
        p = p.strip(".")
        if not p:
            continue
        out.append(p[0].upper() + ("." if dots else ""))
    return (" " if space else "").join(out)


def _doi_url(r):
    return f"https://doi.org/{r['DOI']}" if r.get("DOI") else (r.get("URL") or "")


def _pages(r, dash="–"):
    p = str(r.get("page", "") or "").replace("--", "-").replace("-", dash)
    return p


def _and_list(names, conj="and", oxford=True):
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} {conj} {names[1]}"
    return ", ".join(names[:-1]) + ("," if oxford else "") + f" {conj} {names[-1]}"


def _ed(n, short=True):
    if not n:
        return ""
    n = str(n)
    if n in ("1", "1st"):
        return ""
    suf = {"1": "st", "2": "nd", "3": "rd"}.get(n[-1], "th") if n.isdigit() and not n.endswith(("11", "12", "13")) else "th"
    return f"{n}{suf} ed." if n.isdigit() else n


def _kind(r):
    t = r.get("type", "article-journal")
    if t == "chapter" or (t == "paper-conference" and r.get("editor")):
        return "chapter"
    if t == "book":
        return "book"
    if t == "paper-conference":
        return "conference"
    if t in ("article", "report", "thesis", "webpage", "dataset", "manuscript"):
        return t
    return "journal"


# ==================================================================== formatters
def apa(r) -> str:
    def nm(p):
        return f"{p['family']}, {_initials(p['given'])}".strip(", ")
    au = [nm(a) for a in r.get("author", [])]
    if len(au) > 20:
        au = au[:19] + ["…", au[-1]]
        authors = ", ".join(au[:-2]) + ", … " + au[-1]
    elif len(au) >= 2:
        authors = ", ".join(au[:-1]) + ", & " + au[-1]
    else:
        authors = au[0] if au else ""
    y = _year(r) or "n.d."
    k, title = _kind(r), r.get("title", "")
    eds = [f"{_initials(e['given'])} {e['family']}".strip() for e in r.get("editor", [])]
    ed_str = (_and_list(eds, "&", oxford=len(eds) > 2) + (" (Eds.)" if len(eds) > 1 else " (Ed.)")) if eds else ""
    if not authors and eds:  # edited book cited as a whole
        authors = ", ".join(f"{e['family']}, {_initials(e['given'])}" for e in r["editor"]) + \
                  (" (Eds.)" if len(eds) > 1 else " (Ed.)")
        ed_str = ""
    edn = _ed(r.get("edition"))
    doi = _doi_url(r)
    if k == "journal":
        vi = f", *{r['volume']}*" if r.get("volume") else ""
        vi += f"({r['issue']})" if r.get("issue") else ""
        pg = f", {_pages(r)}" if r.get("page") else (f", Article {r['number']}" if r.get("number") else "")
        s = f"{authors} ({y}). {title}. *{r.get('container-title', '')}*{vi}{pg}."
    elif k == "book":
        meta = ", ".join(x for x in [edn, f"Vol. {r['volume']}" if r.get("volume") else ""] if x)
        s = f"{authors} ({y}). *{title}*{f' ({meta})' if meta else ''}. {r.get('publisher', '')}".rstrip() + "."
    elif k in ("chapter", "conference"):
        inner = ", ".join(x for x in [edn, f"pp. {_pages(r)}" if r.get("page") else ""] if x)
        cont = f"*{r.get('container-title', '')}*" + (f" ({inner})" if inner else "")
        pre = f"In {ed_str}, " if ed_str else "In "
        s = f"{authors} ({y}). {title}. {pre}{cont}. {r.get('publisher', '')}".rstrip() + "."
    elif k == "article":
        s = f"{authors} ({y}). *{title}* [Preprint]. {r.get('container-title') or r.get('publisher', '')}."
    elif k == "thesis":
        s = f"{authors} ({y}). *{title}* [{r.get('genre', 'Doctoral dissertation')}, {r.get('publisher', '')}]."
    elif k == "dataset":
        s = f"{authors} ({y}). *{title}* [Data set]. {r.get('publisher') or r.get('container-title', '')}."
    elif k == "report":
        num = f" ({r['number']})" if r.get("number") else ""
        s = f"{authors} ({y}). *{title}*{num}. {r.get('publisher') or r.get('container-title', '')}."
    else:
        s = f"{authors} ({y}). *{title}*. {r.get('publisher') or r.get('container-title', '')}."
    s = s.replace(" .", ".").replace("..", ".")
    return f"{s} {doi}".strip()


def mla(r) -> str:
    a = r.get("author", [])
    if not a:
        authors = ""
    elif len(a) == 1:
        authors = f"{a[0]['family']}, {a[0]['given']}"
    elif len(a) == 2:
        authors = f"{a[0]['family']}, {a[0]['given']}, and {a[1]['given']} {a[1]['family']}"
    else:
        authors = f"{a[0]['family']}, {a[0]['given']}, et al"
    authors = authors.strip(", ") + ("." if authors else "")
    y, k = _year(r) or "n.d.", _kind(r)
    eds = [f"{e['given']} {e['family']}".strip() for e in r.get("editor", [])]
    parts = []
    if k == "book":
        parts = [f"*{r.get('title', '')}*.", (f"Edited by {_and_list(eds)}," if eds else ""),
                 (_ed(r.get("edition")) + "," if r.get("edition") else ""), f"{r.get('publisher', '')},", f"{y}."]
    else:
        cont = [f"*{r.get('container-title', '')}*,"]
        if eds:
            cont.append(f"edited by {_and_list(eds)},")
        if r.get("volume"):
            cont.append(f"vol. {r['volume']},")
        if r.get("issue"):
            cont.append(f"no. {r['issue']},")
        if k in ("chapter", "conference") and r.get("publisher"):
            cont.append(f"{r['publisher']},")
        cont.append(f"{y},")
        if r.get("page"):
            cont.append(f"pp. {_pages(r, '-')},")
        parts = [f"“{r.get('title', '')}.”"] + cont
    s = " ".join(x for x in [authors] + parts if x).rstrip(",. ")
    doi = _doi_url(r).replace("https://", "")
    return (s + (f", {doi}." if doi else ".")).replace(",.", ".").replace("..", ".")


def chicago_ad(r) -> str:
    a = r.get("author", [])
    names = [f"{a[0]['family']}, {a[0]['given']}"] + [f"{x['given']} {x['family']}" for x in a[1:]] if a else []
    if len(names) > 10:
        names = names[:7] + ["et al."]
        authors = ", ".join(names)
    else:
        authors = f"{names[0]}, and {names[1]}" if len(names) == 2 else _and_list(names)
    y, k = _year(r) or "n.d.", _kind(r)
    eds = [f"{e['given']} {e['family']}".strip() for e in r.get("editor", [])]
    if k == "journal":
        s = (f"{authors}. {y}. “{r.get('title', '')}.” *{r.get('container-title', '')}* {r.get('volume', '')}"
             + (f" ({r['issue']})" if r.get("issue") else "") + (f": {_pages(r)}" if r.get("page") else "") + ".")
    elif k == "book":
        s = (f"{authors}. {y}. *{r.get('title', '')}*." + (f" {_ed(r.get('edition'))}" if _ed(r.get('edition')) else "")
             + f" {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}.")
    else:
        s = (f"{authors}. {y}. “{r.get('title', '')}.” In *{r.get('container-title', '')}*"
             + (f", edited by {_and_list(eds)}" if eds else "") + (f", {_pages(r)}" if r.get("page") else "")
             + f". {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}.")
    s = s.replace(" .", ".").replace("..", ".")
    return f"{s} {_doi_url(r)}".strip()


def chicago_nb(r) -> str:
    a = r.get("author", [])
    names = [f"{a[0]['family']}, {a[0]['given']}"] + [f"{x['given']} {x['family']}" for x in a[1:]] if a else []
    authors = (f"{names[0]}, and {names[1]}" if len(names) == 2 else _and_list(names)) if len(names) <= 10 \
        else ", ".join(names[:7]) + ", et al."
    y, k = _year(r) or "n.d.", _kind(r)
    eds = [f"{e['given']} {e['family']}".strip() for e in r.get("editor", [])]
    if k == "journal":
        s = (f"{authors}. “{r.get('title', '')}.” *{r.get('container-title', '')}* {r.get('volume', '')}"
             + (f", no. {r['issue']}" if r.get("issue") else "") + f" ({y})" + (f": {_pages(r)}" if r.get("page") else "") + ".")
    elif k == "book":
        s = (f"{authors}. *{r.get('title', '')}*." + (f" Edited by {_and_list(eds)}." if eds else "")
             + f" {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}, {y}.")
    else:
        s = (f"{authors}. “{r.get('title', '')}.” In *{r.get('container-title', '')}*"
             + (f", edited by {_and_list(eds)}" if eds else "") + (f", {_pages(r)}" if r.get("page") else "")
             + f". {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}, {y}.")
    s = s.replace(" .", ".").replace("..", ".")
    return f"{s} {_doi_url(r)}".strip()


def harvard(r, accessed: str | None = None) -> str:
    a = r.get("author", [])
    names = [f"{x['family']}, {_initials(x['given'], space=False)}" for x in a]
    authors = (names[0] + " et al." if len(names) > 3 else _and_list(names, "and", oxford=False)) if names else ""
    y, k = _year(r) or "no date", _kind(r)
    eds = [f"{e['family']}, {_initials(e['given'], space=False)}" for e in r.get("editor", [])]
    edn = (f" {r['edition']}{'nd' if str(r['edition']) == '2' else 'rd' if str(r['edition']) == '3' else 'th'} edn."
           if r.get("edition") and str(r["edition"]) not in ("1",) else "")
    place = f"{r['publisher-place']}: " if r.get("publisher-place") else ""
    if k == "journal":
        s = (f"{authors} ({y}) ‘{r.get('title', '')}’, *{r.get('container-title', '')}*"
             + (f", {r['volume']}" if r.get("volume") else "") + (f"({r['issue']})" if r.get("issue") else "")
             + (f", pp. {_pages(r)}" if r.get("page") else "") + ".")
    elif k == "book":
        s = f"{authors} ({y}) *{r.get('title', '')}*.{edn} {place}{r.get('publisher', '')}."
    else:
        s = (f"{authors} ({y}) ‘{r.get('title', '')}’, in "
             + (f"{_and_list(eds, 'and', oxford=False)} ({'eds' if len(eds) > 1 else 'ed.'}) " if eds else "")
             + f"*{r.get('container-title', '')}*.{edn} {place}{r.get('publisher', '')}"
             + (f", pp. {_pages(r)}" if r.get("page") else "") + ".")
    s = s.replace(" .", ".").replace("..", ".")
    if r.get("DOI"):
        s += f" Available at: https://doi.org/{r['DOI']}"
        if accessed:
            s += f" (Accessed: {accessed})"
        s += "."
    return s


def ieee(r, n: int | None = None) -> str:
    a = r.get("author", [])
    names = [f"{_initials(x['given'])} {x['family']}".strip() for x in a]
    authors = names[0] + " *et al.*" if len(names) > 6 else _and_list(names, "and", oxford=len(names) > 2)
    y, k = _year(r) or "", _kind(r)
    eds = [f"{_initials(e['given'])} {e['family']}".strip() for e in r.get("editor", [])]
    pre = f"[{n}] " if n else ""
    if k == "journal":
        s = (f"{authors}, “{r.get('title', '')},” *{r.get('container-title', '')}*"
             + (f", vol. {r['volume']}" if r.get("volume") else "") + (f", no. {r['issue']}" if r.get("issue") else "")
             + (f", pp. {_pages(r)}" if r.get("page") else (f", Art. no. {r['number']}" if r.get("number") else ""))
             + f", {y}" + (f", doi: {r['DOI']}." if r.get("DOI") else "."))
    elif k == "book":
        s = (f"{authors}, *{r.get('title', '')}*" + (f", {_ed(r.get('edition')).rstrip('.')}" if _ed(r.get('edition')) else "")
             + f". {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}, {y}.")
    elif k == "conference":
        s = (f"{authors}, “{r.get('title', '')},” in *{_proc(r.get('container-title') or r.get('event', ''))}*, {y}"
             + (f", pp. {_pages(r)}" if r.get("page") else "") + (f", doi: {r['DOI']}." if r.get("DOI") else "."))
    else:
        s = (f"{authors}, “{r.get('title', '')},” in *{r.get('container-title', '')}*"
             + (f", {_and_list(eds)}, {'Eds' if len(eds) > 1 else 'Ed'}." if eds else "")
             + f" {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}, {y}"
             + (f", pp. {_pages(r)}" if r.get("page") else "") + ".")
    return pre + s.replace(",,", ",")


def _proc(name: str) -> str:
    """IEEE abbreviates 'Proceedings of the …' to 'Proc. …'."""
    n = re.sub(r"(?i)^proceedings of (the )?", "", name or "").strip()
    return f"Proc. {n}" if n else ""


def _vanc_name(x):
    return f"{x['family']} {_initials(x['given'], dots=False, space=False)}".strip()


def vancouver(r, n: int | None = None) -> str:
    a = [_vanc_name(x) for x in r.get("author", [])]
    authors = ", ".join(a[:6]) + (", et al" if len(a) > 6 else "")
    y, k = _year(r) or "", _kind(r)
    pre = f"{n}. " if n else ""
    if k == "journal":
        s = (f"{authors}. {r.get('title', '')}. {r.get('container-title', '')}. {y}"
             + (f";{r['volume']}" if r.get("volume") else "") + (f"({r['issue']})" if r.get("issue") else "")
             + (f":{_pages(r, '-')}" if r.get("page") else "") + ".")
    elif k == "book":
        s = (f"{authors}. {r.get('title', '')}." + (f" {_ed(r.get('edition'))}" if _ed(r.get('edition')) else "")
             + f" {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}{r.get('publisher', '')}; {y}.")
    else:
        eds = ", ".join(_vanc_name(e) for e in r.get("editor", []))
        s = (f"{authors}. {r.get('title', '')}. In: " + (f"{eds}, {'editors' if len(r.get('editor', [])) > 1 else 'editor'}. " if eds else "")
             + f"{r.get('container-title', '')}. {r.get('publisher-place', '') + ': ' if r.get('publisher-place') else ''}"
             f"{r.get('publisher', '')}; {y}." + (f" p. {_pages(r, '-')}." if r.get("page") else ""))
    if r.get("DOI"):
        s += f" doi:{r['DOI']}"
    return pre + s.replace("..", ".")


def ama(r, n: int | None = None) -> str:
    a = [_vanc_name(x) for x in r.get("author", [])]
    authors = ", ".join(a[:3]) + ", et al" if len(a) > 6 else ", ".join(a)
    y, k = _year(r) or "", _kind(r)
    pre = f"{n}. " if n else ""
    if k == "journal":
        s = (f"{authors}. {r.get('title', '')}. *{r.get('container-title', '')}*. {y}"
             + (f";{r['volume']}" if r.get("volume") else "") + (f"({r['issue']})" if r.get("issue") else "")
             + (f":{_pages(r, '-')}" if r.get("page") else "") + ".")
    elif k == "book":
        s = (f"{authors}. *{r.get('title', '')}*." + (f" {_ed(r.get('edition'))}" if _ed(r.get('edition')) else "")
             + f" {r.get('publisher', '')}; {y}.")
    else:
        eds = ", ".join(_vanc_name(e) for e in r.get("editor", []))
        s = (f"{authors}. {r.get('title', '')}. In: " + (f"{eds}, eds. " if eds else "")
             + f"*{r.get('container-title', '')}*. {r.get('publisher', '')}; {y}:{_pages(r, '-')}.")
    if r.get("DOI"):
        s += f" doi:{r['DOI']}"
    return pre + s.replace("..", ".")


def nature(r, n: int | None = None) -> str:
    a = [f"{x['family']}, {_initials(x['given'])}".strip(", ") for x in r.get("author", [])]
    if len(a) > 5:
        authors = a[0] + " et al."
    elif len(a) >= 2:
        authors = ", ".join(a[:-1]) + " & " + a[-1]
    else:
        authors = a[0] if a else ""
    y, k = _year(r) or "", _kind(r)
    pre = f"{n}. " if n else ""
    if k == "journal":
        s = (f"{authors} {r.get('title', '')}. *{r.get('container-title', '')}* **{r.get('volume', '')}**, "
             f"{_pages(r) or r.get('number', '')} ({y}).")
    elif k == "book":
        s = f"{authors} *{r.get('title', '')}* ({r.get('publisher', '')}, {y})."
    else:
        eds = ", ".join(f"{e['family']}, {_initials(e['given'])}" for e in r.get("editor", []))
        s = (f"{authors} {r.get('title', '')}. in *{r.get('container-title', '')}*"
             + (f" (eds {eds})" if eds else "") + f" {_pages(r)} ({r.get('publisher', '')}, {y}).")
    return pre + s.replace(" ,", ",")


FORMATTERS = {"apa": apa, "mla": mla, "chicago-ad": chicago_ad, "chicago-nb": chicago_nb, "harvard": harvard,
              "ieee": ieee, "vancouver": vancouver, "ama": ama, "nature": nature}
NUMBERED = {"ieee", "vancouver", "ama", "nature"}


def format_reference(rec: dict, style: str = "apa", n: int | None = None) -> str:
    f = FORMATTERS[style]
    out = f(rec, n) if style in NUMBERED else f(rec)
    # tidy records with missing fields (e.g. no journal name): drop empty italics and doubled punctuation
    out = re.sub(r"\*\*|__|\(\)|“”|\"\"", "", out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    out = re.sub(r"([.,;:])\s+[.,;:]", r"\1", out)
    out = re.sub(r"([.,])([”’\"])[.,]", r"\1\2", out)
    out = re.sub(r"(?<!\.)\.\.(?!\.)", ".", out)          # doubled full stop
    out = re.sub(r"\.\*\.", ".*", out)                    # *J. Bus. Res.*.
    out = re.sub(r"([’”\"]),\.", r"\1.", out)
    out = re.sub(r"\.,\s*\(", ". (", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return re.sub(r"[,;:]$", ".", out)


def in_text(rec: dict, style: str = "apa", n: int | None = None) -> str:
    a = rec.get("author", [])
    fam = [x["family"] for x in a] or [rec.get("title", "Anon")[:20]]
    y = _year(rec) or "n.d."
    if style in NUMBERED:
        return {"ieee": f"[{n or 1}]", "vancouver": f"({n or 1})"}.get(style, f"^{n or 1}^")
    if style == "mla":
        return f"({fam[0]}{' and ' + fam[1] if len(fam) == 2 else ' et al.' if len(fam) > 2 else ''})"
    if len(fam) == 1:
        return f"({fam[0]}, {y})" if style in ("apa", "harvard") else f"({fam[0]} {y})"
    if len(fam) == 2:
        j = " & " if style == "apa" else " and "
        return f"({fam[0]}{j}{fam[1]}, {y})" if style in ("apa", "harvard") else f"({fam[0]} and {fam[1]} {y})"
    return f"({fam[0]} et al., {y})" if style in ("apa", "harvard") else f"({fam[0]} et al. {y})"


def narrative_cite(rec: dict) -> str:
    """Narrative (author-prominent) form: 'Menon et al. (2025)'."""
    fam = [x["family"] for x in rec.get("author", [])] or [rec.get("title", "Anon")[:20]]
    y = _year(rec) or "n.d."
    if len(fam) == 1:
        return f"{fam[0]} ({y})"
    if len(fam) == 2:
        return f"{fam[0]} and {fam[1]} ({y})"
    return f"{fam[0]} et al. ({y})"


def bibliography(recs: list[dict], style: str = "apa") -> list[str]:
    if style in NUMBERED:
        return [format_reference(r, style, i + 1) for i, r in enumerate(recs)]
    key = lambda r: ((r.get("author") or [{"family": r.get("title", "")}])[0]["family"].lower(), _year(r) or 0)
    return [format_reference(r, style) for r in sorted(recs, key=key)]


# ================================================================ conversions
def md_to_plain(s: str) -> str:
    return re.sub(r"\^(.+?)\^", r"\1", s.replace("**", "").replace("*", ""))


def md_to_html(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
    return re.sub(r"\^(.+?)\^", r"<sup>\1</sup>", s)


def to_docx(refs_md: list[str], title: str = "References", path_or_buffer=None, hanging: bool = True):
    """Write a .docx where italics/bold survive (hanging indent like journal reference lists)."""
    from docx import Document
    from docx.shared import Cm, Pt
    doc = Document()
    doc.add_heading(title, level=1)
    for ref in refs_md:
        p = doc.add_paragraph()
        if hanging:
            p.paragraph_format.left_indent = Cm(1.27)
            p.paragraph_format.first_line_indent = Cm(-1.27)
        for tok in re.split(r"(\*\*.+?\*\*|\*.+?\*|\^.+?\^)", ref):
            if not tok:
                continue
            if tok.startswith("**"):
                run = p.add_run(tok[2:-2]); run.bold = True
            elif tok.startswith("*"):
                run = p.add_run(tok[1:-1]); run.italic = True
            elif tok.startswith("^"):
                run = p.add_run(tok[1:-1]); run.font.superscript = True
            else:
                run = p.add_run(tok)
            run.font.size = Pt(11)
    doc.save(path_or_buffer)
    return path_or_buffer


def to_bibtex(recs: list[dict]) -> str:
    out = []
    for i, r in enumerate(recs):
        k = _kind(r)
        etype = {"journal": "article", "book": "book", "chapter": "incollection",
                 "conference": "inproceedings", "thesis": "phdthesis"}.get(k, "misc")
        fam = re.sub(r"\W", "", ((r.get("author") or [{"family": "anon"}])[0]["family"] or "anon")).lower()
        key = f"{fam}{_year(r) or ''}{i}"
        f = {"title": r.get("title"), "author": " and ".join(f"{a['family']}, {a['given']}" for a in r.get("author", [])),
             "editor": " and ".join(f"{a['family']}, {a['given']}" for a in r.get("editor", [])),
             ("journal" if k == "journal" else "booktitle"): r.get("container-title"),
             "year": _year(r), "volume": r.get("volume"), "number": r.get("issue"),
             "pages": str(r.get("page", "")).replace("-", "--") if r.get("page") else None,
             "publisher": r.get("publisher"), "address": r.get("publisher-place"), "edition": r.get("edition"),
             "isbn": r.get("ISBN"), "issn": r.get("ISSN"), "doi": r.get("DOI"), "url": r.get("URL"),
             "note": r.get("note"), "keywords": r.get("keyword")}
        body = ",\n".join(f"  {k2} = {{{v}}}" for k2, v in f.items() if v)
        out.append(f"@{etype}{{{key},\n{body}\n}}")
    return "\n\n".join(out)


def to_ris(recs: list[dict]) -> str:
    out = []
    for r in recs:
        ty = {"journal": "JOUR", "book": "BOOK", "chapter": "CHAP", "conference": "CONF", "thesis": "THES"}.get(_kind(r), "GEN")
        lines = [f"TY  - {ty}"]
        lines += [f"AU  - {a['family']}, {a['given']}" for a in r.get("author", [])]
        lines += [f"ED  - {a['family']}, {a['given']}" for a in r.get("editor", [])]
        for tag, key in (("TI", "title"), ("T2", "container-title"), ("VL", "volume"), ("IS", "issue"),
                         ("PB", "publisher"), ("CY", "publisher-place"), ("ET", "edition"), ("SN", "ISSN"),
                         ("DO", "DOI"), ("UR", "URL"), ("N1", "note")):
            if r.get(key):
                lines.append(f"{tag}  - {r[key]}")
        if _year(r):
            lines.append(f"PY  - {_year(r)}")
        if r.get("page"):
            sp, _, ep = str(r["page"]).partition("-")
            lines.append(f"SP  - {sp}")
            if ep:
                lines.append(f"EP  - {ep}")
        for kw in [k.strip() for k in str(r.get("keyword") or "").split(",") if k.strip()]:
            lines.append(f"KW  - {kw}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def to_endnote(recs: list[dict]) -> str:
    out = []
    for r in recs:
        ty = {"journal": "Journal Article", "book": "Book", "chapter": "Book Section",
              "conference": "Conference Paper"}.get(_kind(r), "Generic")
        lines = [f"%0 {ty}"] + [f"%A {a['family']}, {a['given']}" for a in r.get("author", [])]
        lines += [f"%E {a['family']}, {a['given']}" for a in r.get("editor", [])]
        for tag, key in (("%T", "title"), ("%J" if _kind(r) == "journal" else "%B", "container-title"),
                         ("%V", "volume"), ("%N", "issue"), ("%P", "page"), ("%I", "publisher"),
                         ("%C", "publisher-place"), ("%7", "edition"), ("%R", "DOI"), ("%U", "URL")):
            if r.get(key):
                lines.append(f"{tag} {r[key]}")
        if _year(r):
            lines.append(f"%D {_year(r)}")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def today() -> str:
    return date.today().strftime("%d %B %Y")
