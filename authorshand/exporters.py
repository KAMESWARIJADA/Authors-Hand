"""Export helpers: Markdown summary, BibTeX, and the one-page 'Research Passport'."""
from __future__ import annotations

import re

from .summarizer import FIELDS

LABELS = {"tldr": "TL;DR", "problem": "Research problem", "objectives": "Objectives",
          "methodology": "Methodology", "data": "Data", "key_findings": "Key findings",
          "contributions": "Contributions", "limitations": "Limitations", "future_work": "Future work"}


def summary_markdown(s: dict) -> str:
    out = [f"# {s['title']}", "",
           f"*Engine: {s['engine']} · Faithfulness: {s['faithfulness']:.2f} · "
           f"Compression: {s['compression']:.1%} · Keywords: {', '.join(s['keywords'])}*", ""]
    for k in FIELDS:
        v = s["fields"].get(k)
        out.append(f"## {LABELS[k]}")
        if isinstance(v, list):
            out += [f"- {x}" for x in v] or ["- Not reported in the paper."]
        else:
            out.append(v or "Not reported in the paper.")
        out.append("")
    out.append("## Evidence trail")
    for e in s["evidence"]:
        out.append(f"- **{LABELS.get(e['field'], e['field'])}** ({e['section']}, support {e['support']:.2f}): "
                   f"{e['evidence']}")
    return "\n".join(out)


def _bibkey(w: dict, i: int) -> str:
    last = re.sub(r"\W", "", ((w.get("authors") or ["anon"])[0].split() or ["anon"])[-1]).lower()
    word = re.sub(r"\W", "", (w.get("title") or "x").split()[0]).lower()
    return f"{last}{w.get('year') or ''}{word}{i}"


def to_bibtex(works: list[dict]) -> str:
    out = []
    for i, w in enumerate(works):
        fields = {"title": w.get("title"), "author": " and ".join(w.get("authors") or []),
                  "journal": w.get("venue"), "year": w.get("year"), "doi": w.get("doi"),
                  "url": w.get("url") or w.get("oa_pdf")}
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        out.append(f"@article{{{_bibkey(w, i)},\n{body}\n}}")
    return "\n\n".join(out)


def research_passport(profile) -> str:
    m = profile.metrics()
    h = profile.health_audit()
    themes = profile.themes()
    lines = [f"# Research Passport — {profile.name or profile.orcid}", "",
             f"**ORCID:** https://orcid.org/{profile.orcid}  ",
             f"**ResearchGate:** {profile.researchgate or 'not linked'}  ",
             f"**Affiliation:** {', '.join(profile.institutions) or (profile.employments[0]['organization'] if profile.employments else '—')}",
             "", "## Impact", f"Works **{m['works']}** · Citations **{m['citations']}** · "
             f"h-index **{m['h_index']}** · i10-index **{m['i10_index']}** · Open access **{m['open_access_share']:.0%}**",
             "", "## Research themes"]
    lines += [f"- **{t['theme']}** — {t['works']} works, {t['momentum']}" for t in themes]
    lines += ["", "## Frequent co-authors"] + [f"- {a} ({n})" for a, n in profile.coauthors(8)]
    lines += ["", "## Top venues"] + [f"- {v} ({n})" for v, n in profile.venues(6)]
    lines += ["", f"## Profile health: {h['score']}/100"] + [f"- {f}" for f in h["fixes"]]
    lines += ["", "## Most cited works"]
    for w in sorted(profile.works, key=lambda w: -(w.get("citations") or 0))[:5]:
        lines.append(f"- {w['title']} ({w.get('year')}) — {w.get('citations', 0)} citations")
    return "\n".join(lines)
