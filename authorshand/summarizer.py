"""Evidence-grounded structured summarisation of research papers.

Two engines share one output schema:
  * LLM engine   – section-aware map-reduce with a JSON schema, followed by a
                   self-verification pass that rewrites unsupported claims.
  * Local engine – section routing + cue-biased TextRank (runs with no key).

Every summary is then *grounded*: each claim is linked to the closest source
sentence and given a support score, producing a faithfulness score that the
agent uses as a quality gate.
"""
from __future__ import annotations

import re
import time
from collections import OrderedDict

import numpy as np

from .llm import LLM
from .pdf_reader import guess_title, split_sections
from .text_utils import (cosine_sim, split_sentences, textrank, tfidf_matrix, tokenize, normalize_title,
                         top_keywords, word_count)

FIELDS = OrderedDict([
    ("tldr", "One-sentence TL;DR of the whole paper"),
    ("problem", "The research problem / gap the paper addresses"),
    ("objectives", "Research objectives or questions"),
    ("methodology", "Research design, models, techniques"),
    ("data", "Data, sample, setting"),
    ("key_findings", "Main results (with numbers where reported)"),
    ("contributions", "Theoretical / practical contributions"),
    ("limitations", "Stated limitations"),
    ("future_work", "Suggested future research"),
])

# section routing + cue words for the local engine
ROUTES = {
    "problem": (["introduction", "abstract", "body"], ["gap", "however", "little", "problem", "lack",
                                                         "challenge", "unclear", "limited", "remains"]),
    "objectives": (["introduction", "abstract", "body"], ["aim", "objective", "this study", "this paper",
                                                           "we propose", "purpose", "investigate", "examine"]),
    "methodology": (["methodology", "abstract", "body"], ["method", "model", "approach", "framework",
                                                           "regression", "algorithm", "trained", "design",
                                                           "survey", "we use", "employ"]),
    "data": (["data", "methodology", "abstract", "body"], ["data", "sample", "respondents", "dataset",
                                                            "records", "collected", "observations", "n ="]),
    "key_findings": (["results", "abstract", "discussion", "conclusion", "body"],
                     ["found", "results", "significant", "improve", "outperform", "accuracy", "%",
                      "percent", "increase", "reduce", "show", "indicate", "reveal", "achieved",
                      "reached", "times", "than", "fell", "rose"]),
    "contributions": (["conclusion", "discussion", "introduction", "body"],
                      ["contribut", "implication", "novel", "first", "extend", "practitioners", "managers"]),
    "limitations": (["limitations", "conclusion", "discussion", "body"],
                    ["limitation", "limited", "caution", "generaliz", "only", "cross-sectional", "bias"]),
    "future_work": (["future_work", "limitations", "conclusion", "body"],
                    ["future", "further research", "extend", "could explore", "should examine"]),
}

PERSONAS = {
    "researcher": "a domain researcher who wants methodological detail",
    "student": "a postgraduate student; explain jargon in plain words",
    "executive": "a busy manager/practitioner; focus on implications and numbers",
}


class PaperSummarizer:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM("local")

    # ------------------------------------------------------------------ API
    def summarize(self, text: str, title: str | None = None, persona: str = "researcher",
                  strict: bool = False, pages: list[str] | None = None) -> dict:
        t0 = time.time()
        sections = split_sections(text)
        title = title or guess_title(text)
        engine = "local"
        if self.llm.available:
            try:
                fields = self._llm_summary(sections, title, persona, strict)
                engine = self.llm.label
            except Exception as e:  # graceful degradation, never crash the user
                fields = self._local_summary(sections)
                engine = f"local (LLM failed: {str(e)[:80]})"
        else:
            fields = self._local_summary(sections)
        evidence = ground(fields, sections, pages)
        all_text = " ".join(sections.values())
        summary_text = " ".join(_as_text(v) for v in fields.values())
        return {
            "title": title,
            "fields": fields,
            "executive_summary": executive_summary(fields),
            "keywords": top_keywords(list(sections.values()), k=8),
            "evidence": evidence,
            "faithfulness": round(float(np.mean([e["support"] for e in evidence])) if evidence else 0.0, 3),
            "sections_found": [s for s in sections.keys() if s != "front_matter"],
            "source_words": word_count(all_text),
            "summary_words": word_count(summary_text),
            "compression": round(word_count(summary_text) / max(1, word_count(all_text)), 3),
            "engine": engine,
            "persona": persona,
            "latency_s": round(time.time() - t0, 2),
        }

    # -------------------------------------------------------------- engines
    def _local_summary(self, sections: "OrderedDict[str, str]") -> dict:
        def sents_from(names):
            out = []
            for n in names:
                if n in sections:
                    out += split_sentences(sections[n])
            return out

        all_sents = sents_from(list(sections.keys()))
        used: set[str] = set()
        fields: dict = {}
        abstract = sections.get("abstract") or sections.get("body") or " ".join(sections.values())
        tl_cues = ["this study", "this paper", "we ", "propose", "show", "find", "reduced", "improved",
                   "percent", "outperform", "achieved", "raised"]
        tl = textrank(split_sentences(abstract), top_n=3, bias=tl_cues)
        fields["tldr"] = max(tl, key=lambda x: _cue_score(x, tl_cues)) if tl else ""
        for f, (secs, cues) in ROUTES.items():
            n = 3 if f == "key_findings" else 2
            if f in ("limitations", "future_work"):
                # prefer the paper's own dedicated section; never invent limitations
                own = [s for s in sents_from([f]) if s not in used]
                if own:
                    fields[f] = own[:n]
                    used.update(fields[f])
                    continue
            pool = [s for s in sents_from(secs) if s not in used and not _near_dup(s, used)]
            cued = [s for s in pool if any(c in s.lower() for c in cues)
                    or (f == "key_findings" and re.search(r"\d", s))]
            if f in ("limitations", "future_work") and not cued:
                fields[f] = []
                continue
            cand = cued or pool or [s for s in all_sents if s not in used]
            ranked = textrank(cand, top_n=min(len(cand), n * 3), bias=cues)
            picked: list[str] = []
            for c in sorted(ranked, key=lambda x: -_cue_score(x, cues)):   # MMR-style: no near-duplicates
                if not _near_dup(c, set(picked) | used, 0.4):
                    picked.append(c)
                if len(picked) == n:
                    break
            picked = [c for c in cand if c in picked]                          # keep reading order
            used.update(picked)
            fields[f] = picked
        return fields

    def _llm_summary(self, sections, title, persona, strict) -> dict:
        # MAP: compress long sections independently (keeps within context limits)
        notes = []
        for name, body in sections.items():
            if name == "front_matter":
                continue
            chunk = body[:12000]
            if len(body) > 4000:
                chunk = self.llm.generate(
                    f"Section '{name}' of the paper '{title}'. Extract every factual claim, method detail, "
                    f"number, dataset and limitation as terse bullet points. Do not add anything not in the "
                    f"text.\n\nTEXT:\n{chunk}")
            notes.append(f"## {name}\n{chunk}")
        context = "\n\n".join(notes)[:60000]
        schema = {k: ("string" if k == "tldr" else "list of 1-4 short strings") for k in FIELDS}
        rule = ("Use ONLY information stated in the notes. If a field is not reported write an empty list. "
                "Copy numbers exactly.")
        if strict:
            rule += (" STRICT MODE: a previous draft contained unsupported claims. Paraphrase closely, "
                     "stay close to the source wording, never generalise beyond it.")
        # REDUCE
        data = self.llm.generate_json(
            f"You are summarising the research paper '{title}' for {PERSONAS.get(persona, persona)}.\n"
            f"{rule}\nFill this JSON schema: {schema}\nField meanings: {dict(FIELDS)}\n\nPAPER NOTES:\n{context}")
        fields = {k: data.get(k, [] if k != "tldr" else "") for k in FIELDS}
        # VERIFY: self-check pass removes unsupported statements
        check = self.llm.generate_json(
            "Check each statement of this summary against the paper notes. Return the same JSON with any "
            "statement that is NOT supported by the notes deleted or corrected.\n\n"
            f"SUMMARY:\n{fields}\n\nPAPER NOTES:\n{context[:40000]}")
        if isinstance(check, dict):
            fields = {k: check.get(k, fields[k]) for k in FIELDS}
        return fields

    # ----------------------------------------------------- personalisation
    @staticmethod
    def relevance_to_profile(summary: dict, profile_works: list[dict], top_k: int = 3) -> dict:
        """How does this paper connect to MY research? (ORCID-linked personalisation)"""
        docs = [f"{w.get('title', '')}. {w.get('abstract', '')}" for w in profile_works]
        if not docs:
            return {"score": 0.0, "related_own_works": []}
        paper_doc = summary["title"] + ". " + " ".join(_as_text(v) for v in summary["fields"].values())
        _, m = tfidf_matrix(docs + [paper_doc])
        sims = cosine_sim(m[-1], m[:-1]).ravel()
        own = [i for i, w in enumerate(profile_works)
               if normalize_title(w.get("title", "")) == normalize_title(summary["title"])]
        for i in own:
            sims[i] = -1          # don't relate a paper to itself
        order = sims.argsort()[::-1][:top_k]
        score = float(np.clip(max(sims.max(), 0) * 2.5, 0, 1))  # rescale raw cosine to an intuitive 0-1
        return {"score": round(score, 2), "is_own_work": bool(own),
                "related_own_works": [{"title": profile_works[i]["title"],
                                       "year": profile_works[i].get("year"),
                                       "similarity": round(float(sims[i]), 3)} for i in order if sims[i] > 0]}


def executive_summary(fields: dict) -> str:
    """Compact abstract-length summary assembled from the structured fields."""
    def first(k, n=1):
        v = fields.get(k) or []
        return v[:n] if isinstance(v, list) else [v]
    parts = first("tldr") + first("data") + first("methodology") + first("key_findings", 2) \
        + first("limitations") + first("future_work")
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return " ".join(out)


def _cue_score(s: str, cues) -> float:
    return sum(1 for c in cues if c in s.lower()) + 0.5 * len(re.findall(r"\d+(?:\.\d+)?", s))


def _near_dup(s: str, used: set, thr: float = 0.5) -> bool:
    """Skip sentences that largely repeat one already used (abstract vs results)."""
    a = set(tokenize(s))
    return any(len(a & set(tokenize(u))) / max(1, len(a | set(tokenize(u)))) >= thr for u in used)


# ---------------------------------------------------------------- grounding
def _as_text(v) -> str:
    return " ".join(v) if isinstance(v, list) else str(v or "")


def ground(fields: dict, sections: "OrderedDict[str, str]", pages: list[str] | None = None) -> list[dict]:
    """Link each summary claim to its best supporting source sentence (with section, page and strength)."""
    from .evidence import page_of, support_label
    src, src_sec = [], []
    for name, body in sections.items():
        for s in split_sentences(body, min_words=4):
            src.append(s)
            src_sec.append(name)
    claims = []
    for f, v in fields.items():
        for c in (v if isinstance(v, list) else [v]):
            if c and str(c).strip():
                claims.append((f, str(c)))
    if not src or not claims:
        return []
    vec, m = tfidf_matrix(src + [c for _, c in claims])
    S, C = m[:len(src)], m[len(src):]
    sims = cosine_sim(C, S)
    out = []
    for i, (f, c) in enumerate(claims):
        j = int(sims[i].argmax())
        sc = float(sims[i, j])
        out.append({"field": f, "claim": c, "evidence": src[j], "section": src_sec[j],
                    "page": page_of(src[j], pages), "support": round(sc, 3), "strength": support_label(sc),
                    "context": " ".join(src[max(0, j - 1): j + 2])})
    return out
