"""Multi-paper synthesis: comparison matrix + cited literature-review draft + research agenda."""
from __future__ import annotations

from collections import Counter

import pandas as pd

from .llm import LLM
from .summarizer import PaperSummarizer, _as_text
from .text_utils import split_sentences, tfidf_matrix, top_keywords


def cite(p: dict) -> str:
    authors = p.get("authors") or []
    yr = p.get("year") or "n.d."
    if not authors:
        return f"({p.get('title', 'Anon')[:30]}…, {yr})"
    last = authors[0].split()[-1]
    if len(authors) == 1:
        return f"({last}, {yr})"
    if len(authors) == 2:
        return f"({last} & {authors[1].split()[-1]}, {yr})"
    return f"({last} et al., {yr})"


def _first(v, n=1) -> str:
    if isinstance(v, list):
        return " ".join(v[:n])
    return str(v or "")


class LiteratureReviewer:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM("local")
        self.summarizer = PaperSummarizer(self.llm)

    def review(self, papers: list[dict], topic: str = "") -> dict:
        """`papers`: records with title/authors/year and either `text` (full text) or `abstract`."""
        summaries = []
        for p in papers:
            text = p.get("text") or f"{p['title']}\n\nAbstract: {p.get('abstract', '')}"
            s = self.summarizer.summarize(text, title=p["title"])
            summaries.append((p, s))
        matrix = pd.DataFrame([{
            "Paper": f"{p['title'][:70]} {cite(p)}",
            "Year": p.get("year"),
            "Method": _first(s["fields"].get("methodology")),
            "Data": _first(s["fields"].get("data")),
            "Key finding": _first(s["fields"].get("key_findings")),
            "Limitation": _first(s["fields"].get("limitations")) or "Not stated",
            "Faithfulness": s["faithfulness"],
        } for p, s in summaries])
        topic = topic or ", ".join(top_keywords([p["title"] for p in papers], 3))
        consensus = self._consensus(summaries)
        gaps = self._gaps(summaries)
        narrative = self._narrative(summaries, topic, consensus, gaps)
        return {"topic": topic, "matrix": matrix, "summaries": [s for _, s in summaries],
                "consensus_terms": consensus, "gaps": gaps, "narrative": narrative,
                "references": [self._apa(p) for p, _ in summaries]}

    @staticmethod
    def _consensus(summaries) -> list[str]:
        """Concepts that recur in the findings of several papers (agreement signal)."""
        per_paper = [set(top_keywords([_as_text(s["fields"].get("key_findings"))], 12)) for _, s in summaries]
        c = Counter(t for terms in per_paper for t in terms)
        return [t for t, n in c.most_common(10) if n >= 2]

    @staticmethod
    def _gaps(summaries) -> list[str]:
        out = []
        for p, s in summaries:
            for f in ("future_work", "limitations"):
                for g in (s["fields"].get(f) or [])[:1]:
                    out.append(f"{g.rstrip('. ')} {cite(p)}.")
        return out[:8]

    def _narrative(self, summaries, topic, consensus, gaps) -> str:
        if self.llm.available:
            rows = "\n".join(
                f"- {cite(p)} {p['title']}: method={_first(s['fields'].get('methodology'), 2)}; "
                f"findings={_first(s['fields'].get('key_findings'), 2)}; "
                f"limitations={_first(s['fields'].get('limitations'))}" for p, s in summaries)
            try:
                return self.llm.generate(
                    f"Write a structured literature review (≈450 words) on '{topic}' using ONLY these "
                    f"paper summaries. Sections: Overview, Methodological approaches, Converging evidence, "
                    f"Contradictions, Research gaps & agenda. Cite with the given (Author, Year) tags.\n\n{rows}")
            except Exception:
                pass
        # local, template-guided synthesis
        parts = [f"**Overview.** This review synthesises {len(summaries)} studies on {topic} "
                 f"published between {min((p.get('year') or 9999) for p, _ in summaries)} and "
                 f"{max((p.get('year') or 0) for p, _ in summaries)}."]
        parts.append("**Methodological approaches.** " + " ".join(
            f"{cite(p)} {self._lower_first(_first(s['fields'].get('methodology')))}"
            for p, s in summaries))
        parts.append("**Key findings.** " + " ".join(
            f"{cite(p)} report that {self._lower_first(_first(s['fields'].get('key_findings')))}"
            for p, s in summaries))
        if consensus:
            parts.append("**Converging evidence.** Findings across studies repeatedly involve: "
                         + ", ".join(consensus[:6]) + ".")
        if gaps:
            parts.append("**Research gaps & agenda.** " + " ".join(gaps[:5]))
        return "\n\n".join(parts)

    @staticmethod
    def _lower_first(s: str) -> str:
        s = s.strip()
        return s[0].lower() + s[1:] if len(s) > 1 and s[0].isupper() and s[1].islower() else s

    @staticmethod
    def _apa(p: dict) -> str:
        authors = p.get("authors") or ["Anon."]
        a = ", ".join(authors[:6]) + (", et al." if len(authors) > 6 else "")
        doi = f" https://doi.org/{p['doi']}" if p.get("doi") else ""
        venue = f" *{p['venue']}*." if p.get("venue") else ""
        return f"{a} ({p.get('year') or 'n.d.'}). {p['title']}.{venue}{doi}"
