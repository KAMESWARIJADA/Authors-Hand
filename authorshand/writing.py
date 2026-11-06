"""Writing Studio: turns a set of selected articles into material for every
stage of a research paper — overall summary, introduction, literature review,
research gap, methodology, model development, research questions, hypotheses,
future study and references — each with data for an infographic view.

Local engine: transparent lexicons + pattern extraction (no key needed).
LLM engine: the same structure, with paraphrased drafts and richer extraction.

Academic-integrity note: local drafts re-use source sentences (always cited).
They are scaffolds — paraphrase before submission. Drafts are labelled so.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from .citations import from_paper, in_text, narrative_cite
from .llm import LLM
from .summarizer import PaperSummarizer, _as_text
from .text_utils import split_sentences, top_keywords

METHODS = {
    "Logistic regression": ["logistic regression"],
    "Random forest": ["random forest"],
    "Gradient boosting": ["xgboost", "lightgbm", "gradient boosting", "catboost"],
    "Survival analysis": ["survival analysis", "cox proportional", "hazard"],
    "Difference-in-differences": ["difference-in-differences", "diff-in-diff"],
    "Randomised experiment": ["randomised controlled", "randomized controlled", "field experiment",
                              "randomised field", "randomly assigned", "rct"],
    "Survey / questionnaire": ["survey", "questionnaire", "respondents", "likert"],
    "SEM / PLS-SEM": ["structural equation", "pls-sem", "smartpls", "cb-sem"],
    "Regression (OLS / panel)": ["ols regression", "panel regression", "fixed effects", "linear regression"],
    "Explainable AI": ["shap", "lime", "counterfactual explanation", "explainable"],
    "NLP / text mining": ["natural language processing", "topic model", "text mining", "sentiment analysis"],
    "LLM / generative AI": ["large language model", "llm", "generative ai", "gpt", "copilot"],
    "Retrieval-augmented generation": ["retrieval-augmented", "retrieval augmented"],
    "Deep learning": ["neural network", "deep learning", "transformer", "bart", "pegasus", "lstm"],
    "Qualitative (interviews / case)": ["interview", "case study", "thematic analysis", "focus group"],
    "Systematic review / bibliometrics": ["systematic review", "meta-analysis", "bibliometric"],
    "Clustering": ["k-means", "clustering", "cluster analysis"],
    "Human evaluation": ["human evaluat", "pairwise comparison", "inter-rater", "kappa"],
}
DESIGNS = {
    "Experimental": ["randomised", "randomized", "randomly assigned", "controlled trial", "field experiment"],
    "Quasi-experimental": ["difference-in-differences", "pilot cohort", "propensity", "not randomised",
                           "previous cohort"],
    "Survey-based": ["survey", "questionnaire", "respondents"],
    "Secondary / archival data": ["records", "dataset", "applications", "transactions", "log", "lms data",
                                  "data from"],
    "Qualitative": ["interview", "case study", "focus group", "thematic analysis"],
    "Design science / artefact": ["we propose", "pipeline", "framework", "system", "we release", "prototype"],
    "Review": ["systematic review", "meta-analysis", "bibliometric", "literature review of"],
}
CONTEXTS = {
    "IT / technology firms": ["it services", "software", "technology firm", "it firms"],
    "Banking & finance": ["bank", "banking", "credit", "loan", "loans", "lending", "nbfc", "borrower", "borrowers"],
    "Insurance": ["insurance", "insurer", "policyholder"],
    "Education": ["student", "university", "school", "pgdm", "learning management", "lms", "mba"],
    "Healthcare": ["hospital", "patient", "clinical", "health"],
    "Retail / e-commerce": ["retail", "e-commerce", "customer", "shopper"],
    "Manufacturing": ["manufactur", "plant", "factory"],
    "Public sector": ["public sector", "government", "public-sector"],
    "Scholarly publishing": ["scholarly", "scientific papers", "scientific literature", "publications",
                             "research papers"],
}
UNITS = r"(employees|employee records|records|analysts|students|papers|articles|applications|loan applications|" \
        r"respondents|firms|customers|patients|borrowers|tasks|transcripts|observations|participants|" \
        r"teachers|managers|banks|hospitals|interviews)"
GAP_TYPES = {
    "Population / context gap": ["single", "only", "one industry", "one lender", "one country", "three firms",
                                 "single institution", "single bank", "english", "generalis", "generaliz",
                                 "other sectors", "multiple institutions", "public-sector", "regions"],
    "Methodological gap": ["not randomised", "not randomized", "randomised trial", "cross-sectional", "self-report",
                           "approximate", "causal", "reviewers", "bias", "metric", "field experiment"],
    "Temporal gap": ["horizon", "long-term", "long-run", "longitudinal", "downturn", "period", "over time", "stress"],
    "Theoretical / variable gap": ["not capture", "informal", "not examined", "climate", "perceptions", "mechanism",
                                   "personal", "moderat", "mediat", "fairness"],
    "Data / measurement gap": ["tables", "figures", "multimodal", "multilingual", "survey text", "measure", "parsed"],
}
FAMILIES = {
    "Machine-learning prediction": ["Logistic regression", "Random forest", "Gradient boosting", "Deep learning",
                                    "Survival analysis", "Clustering"],
    "Causal & experimental designs": ["Randomised experiment", "Difference-in-differences", "Regression (OLS / panel)"],
    "Generative AI & NLP": ["LLM / generative AI", "Retrieval-augmented generation", "NLP / text mining"],
    "Explainable & responsible AI": ["Explainable AI"],
    "Survey & structural modelling": ["Survey / questionnaire", "SEM / PLS-SEM"],
    "Qualitative inquiry": ["Qualitative (interviews / case)"],
    "Evidence synthesis": ["Systematic review / bibliometrics"],
}
DESCRIPTIVE_SECTIONS = ("abstract", "introduction", "methodology", "data", "results", "body")
FINDING_SECTIONS = ("abstract", "results", "body")

SOURCE_TYPES = {"journal-article": "Journal article", "proceedings-article": "Conference paper",
                "book-chapter": "Book chapter", "book": "Book", "dissertation": "Thesis / dissertation",
                "thesis": "Thesis / dissertation", "report": "Technical report", "posted-content": "Preprint",
                "preprint": "Preprint", "dataset": "Dataset", "grey": "Grey literature", "webpage": "Web page",
                "article": "Preprint"}

STAGES = ["Summaries", "Introduction", "Literature review", "Research gap", "Methodology", "Model development",
          "Research questions", "Hypotheses", "Future study", "References"]

_VERBS_POS = r"increased|increases|improved|improves|raised|raises|enhanced|enhances|boosted|predicts|predicted|" \
             r"drives|drove|expanded|expands|outperformed"
_VERBS_NEG = r"reduced|reduces|lowered|lowers|decreased|decreases|cut|cuts|removed"
_REL = re.compile(rf"(?P<iv>[A-Za-z][\w\s\-]{{2,60}}?)\s+(?P<verb>{_VERBS_POS}|{_VERBS_NEG})\s+"
                  rf"(?P<dv>[\w\s\-]{{2,70}}?)(?=\s+by\b|\s+from\b|\s+at\b|\s+over\b|\s+in\b|\s+compared\b|[.,;]|$)", re.I)
_DRIVER = re.compile(r"(?P<iv>[A-Za-z][\w\s\-]{2,60}?)\s+(?:was|were|is|are)\s+the\s+(?:single\s+)?"
                     r"(?:most important|strongest|key|main)\s+(?:driver|predictor|determinant)s?", re.I)
_MODERATOR = re.compile(r"(?:gains|benefits|effects?)\s+(?:were\s+)?(?:largest|strongest|greater|highest|smaller)\s+"
                        r"for\s+(?P<group>[\w\s\-]{3,40}?)(?:[.,;]|\s+while|\s+compared|$)", re.I)
_STOP_LEAD = re.compile(r"^(the|a|an|this|that|our|we|it|in addition,?|however,?|overall,?)\s+", re.I)


def _clean_phrase(s: str) -> str:
    s = s.strip(" ,.;:")
    for _ in range(3):
        s = _STOP_LEAD.sub("", s)
    s = re.sub(r"\s+", " ", s)
    return s[:60]


def _match(text: str, lex: dict) -> list[str]:
    t = text.lower()
    return [k for k, kws in lex.items()
            if any(re.search(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])", t) for kw in kws)]


def _and(items: list[str]) -> str:
    items = [i[0].lower() + i[1:] if i[1:2].islower() else i for i in items]
    return items[0] if len(items) == 1 else (", ".join(items[:-1]) + " and " + items[-1] if items else "")


def _match_sources(text: str, lex: dict) -> dict:
    """{category: {"term": matched term, "sentence": first sentence containing it}} — shows WHY it was detected."""
    out = {}
    sents = split_sentences(text, min_words=3)
    for k, kws in lex.items():
        for kw in kws:
            pat = re.compile(r"(?<![a-z])" + re.escape(kw) + r"(?![a-z])")
            hit = next((s for s in sents if pat.search(s.lower())), None)
            if hit:
                out[k] = {"term": kw, "sentence": hit}
                break
    return out


def merge_lexicon(base: dict, extra: dict | None) -> dict:
    out = {k: list(v) for k, v in base.items()}
    for name, terms in (extra or {}).items():
        out.setdefault(name, [])
        out[name] += [t.strip().lower() for t in terms if t.strip()]
    return out


MEASURE_CUES = ("measured", "measure", "scale", "auc", "f1", "gini", "accuracy", "recall", "precision", "rouge",
                "kappa", "completion time", "quality score", "ks statistic", "factual consistency", "rate")


def measures_info(text: str) -> list[str]:
    out = []
    for s in split_sentences(text, min_words=4):
        sl = s.lower()
        if any(c in sl for c in MEASURE_CUES) and ("measur" in sl or "evaluat" in sl or "using" in sl or "score" in sl):
            out.append(s)
    return out[:2]


def family_of(methods: list[str]) -> str:
    best, n = "Other approaches", 0
    for fam, ms in FAMILIES.items():
        k = sum(1 for m in methods if m in ms)
        if k > n:
            best, n = fam, k
    return best


def _sections_text(text: str, names) -> str:
    from .pdf_reader import split_sections
    secs = split_sections(text)
    picked = [v for k, v in secs.items() if k in names]
    return " ".join(picked) if picked else " ".join(v for k, v in secs.items() if k != "front_matter")


def key_numbers(text: str, k: int = 6) -> list[str]:
    """Sentences fragments carrying the paper's headline numbers."""
    out = []
    for s in split_sentences(text):
        if re.search(r"\d+(\.\d+)?\s*(percent|%)|\b(auc|f1|gini|accuracy|r2|r²|ks)\b[^.]{0,30}\d|\d+(\.\d+)?\s+times", s, re.I):
            out.append(s)
    seen, res = set(), []
    for s in out:
        key = re.sub(r"\W", "", s.lower())[:60]
        if key not in seen:
            seen.add(key)
            res.append(s)
    return res[:k]


def sample_info(text: str) -> list[str]:
    hits = re.findall(rf"(\d{{1,3}}(?:,\d{{3}})+|\d{{2,6}})\s+((?:(?!percent|for|of|by)[a-z\-]+\s+){{0,2}}){UNITS}",
                      text, re.I)
    seen, out = set(), []
    for n, mid, unit in hits:
        if n in seen:
            continue
        seen.add(n)
        out.append(f"{n} {(mid + unit).strip()}")
    return out[:4]


def outcome_guess(title: str) -> str:
    t = title.lower()
    m = re.search(r"(?:predicting|of|on|for)\s+([a-z\- ]{3,40}?)(?:\s+with|\s+using|\s+in|:|$)", t)
    if m:
        return _clean_phrase(m.group(1))
    kw = top_keywords([title], 1)
    return kw[0] if kw else "the outcome"


_BAD_START = re.compile(r"^(by|from|to|and|or|of|\d|percent|whether|that)\b", re.I)


def _strip_reporting(s: str) -> str:
    """'SHAP analysis revealed that X …' → 'X …'; 'examines whether X …' → 'X …'."""
    return re.sub(r"(?i)^.*?\b(revealed|showed|shows|found|find|indicate[sd]?|suggests?|whether|demonstrate[sd]?)\s+(that\s+)?",
                  "", s, count=1)


def _norm_dv(dv: str) -> str:
    return re.sub(r"\s+(measured|scores?|levels?)$", "", dv).strip()


def relations(text: str, title: str, max_n: int = 3) -> list[dict]:
    rels = []
    outcome = outcome_guess(title)
    for s in split_sentences(text):
        core = _strip_reporting(s)
        for m in _REL.finditer(core):
            iv, dv, verb = _clean_phrase(m.group("iv")), _clean_phrase(m.group("dv")), m.group("verb").lower()
            if (not iv or not dv or len(iv.split()) > 7 or len(dv.split()) > 8 or verb.startswith("outperform")
                    or _BAD_START.match(iv) or _BAD_START.match(dv) or re.search(r"\d", dv)):
                continue
            sign = "−" if re.match(_VERBS_NEG, verb) else "+"
            rels.append({"iv": iv, "dv": _norm_dv(dv), "sign": sign, "evidence": s})
        for m in _DRIVER.finditer(core):
            dv_m = re.search(r"(?:driver|predictor|determinant)s?\s+of\s+([\w\s\-]{3,40}?)(?:[.,;]|$)", core, re.I)
            rels.append({"iv": _clean_phrase(m.group("iv")), "dv": _clean_phrase(dv_m.group(1)) if dv_m else outcome,
                         "sign": "+", "evidence": s})
    uniq, seen = [], set()
    for r in rels:
        k = (r["iv"].lower(), r["dv"].lower())
        if k not in seen and not any(r["dv"].lower() in u["dv"].lower() and r["iv"].lower() == u["iv"].lower() for u in uniq):
            seen.add(k)
            uniq.append(r)
    return uniq[:max_n]


def moderators(text: str) -> list[dict]:
    return [{"group": _clean_phrase(m.group("group")), "evidence": s}
            for s in split_sentences(text) for m in _MODERATOR.finditer(s)][:3]


def classify_gap(sentence: str) -> str:
    t = sentence.lower()
    best, score = "Empirical gap", 0
    for g, kws in GAP_TYPES.items():
        sc = sum(1 for k in kws if k in t)
        if sc > score:
            best, score = g, sc
    return best


class WritingStudio:
    def __init__(self, llm: LLM | None = None, style: str = "apa", lexicon: dict | None = None):
        """`lexicon` = project-specific terms: {"methods": {name: [terms]}, "designs": {...}, "contexts": {...}}."""
        self.llm = llm or LLM("local")
        self.summarizer = PaperSummarizer(self.llm)
        self.style = style
        lx = lexicon or {}
        self.methods = merge_lexicon(METHODS, lx.get("methods"))
        self.designs = merge_lexicon(DESIGNS, lx.get("designs"))
        self.contexts = merge_lexicon(CONTEXTS, lx.get("contexts"))

    # ------------------------------------------------------------- per article
    def profile_article(self, paper: dict, text: str, summary: dict | None = None) -> dict:
        from .evidence import text_source
        src = paper.get("text_source") or text_source(paper, text)
        text = text or f"{paper.get('title', '')}\n\nAbstract: {paper.get('abstract', '')}"
        s = summary or self.summarizer.summarize(text, title=paper.get("title"), pages=paper.get("pages_text"))
        rec = from_paper(paper)
        desc = _sections_text(text, DESCRIPTIVE_SECTIONS)
        finds = _sections_text(text, FINDING_SECTIONS)
        msrc = _match_sources(desc, self.methods)
        methods = [m for m in self.methods if m in msrc]
        if "Regression (OLS / panel)" in methods and len(methods) > 2:
            methods.remove("Regression (OLS / panel)")
        dsrc, csrc = _match_sources(desc, self.designs), _match_sources(desc, self.contexts)
        ov = paper.get("extraction") or {}          # the user's corrections win
        methods = ov.get("methods") or methods
        f = s["fields"]
        a = {
            "paper": paper, "csl": rec, "cite": in_text(rec, "apa"), "narrative": narrative_cite(rec),
            "summary": s, "exec": s.get("executive_summary", ""), "key_numbers": key_numbers(finds),
            "methods": methods, "family": ov.get("family") or family_of(methods),
            "designs": ov.get("designs") or [d for d in self.designs if d in dsrc] or ["Not classified"],
            "contexts": ov.get("contexts") or [c for c in self.contexts if c in csrc] or ["Unspecified"],
            "sample": ov.get("sample") or sample_info(desc),
            "method_sources": msrc, "design_sources": dsrc, "context_sources": csrc,
            "measures": ov.get("measures") or measures_info(desc + " " + finds),
            "relations": relations(finds, paper.get("title", "")), "moderators": moderators(finds),
            "year": paper.get("year"), "text_source": src, "pages": paper.get("pages_text"),
            "text": text, "source_type": paper.get("type") or "journal-article",
        }
        a["table"] = {
            "Study": a["cite"], "Source type": SOURCE_TYPES.get(a["source_type"], a["source_type"]),
            "Text used": src,
            "Sample": ov.get("table_sample") or "; ".join(a["sample"][:2]) or "Not reported",
            "Setting / context": ov.get("table_setting") or ", ".join(a["contexts"][:2]),
            "Data": ov.get("table_data") or (f.get("data") or ["Not reported"])[0],
            "Method": ov.get("table_method") or ", ".join(methods[:3]) or "Not classified",
            "Measures": ov.get("table_measures") or (a["measures"] or ["Not reported"])[0],
            "Key findings": ov.get("table_findings") or (f.get("key_findings") or ["Not reported"])[0],
            "Limitations": ov.get("table_limitations") or (f.get("limitations") or ["Not stated by the authors"])[0],
        }
        return a

    # -------------------------------------------------------------- synthesis
    def build(self, items: list[dict], topic: str = "") -> dict:
        """items: [{paper, text, summary?}] → everything the Writing Studio tabs show."""
        A = [self.profile_article(i["paper"], i.get("text", ""), i.get("summary")) for i in items]
        topic = topic or "the selected studies"
        out = {"topic": topic, "articles": A}
        out["overall"] = self._overall(A, topic)
        out["introduction"] = self._intro(A, topic)
        out["lit_review"] = self._lit_review(A, topic)
        out["gaps"] = self._gaps(A)
        out["methodology"] = self._methodology(A)
        out["model"] = self._model(A)
        out["questions"] = self._questions(A, out["gaps"], out["model"])
        out["hypotheses"] = self._hypotheses(A, out["model"])
        out["future"] = self._future(A)
        if self.llm.available:
            self._llm_enrich(out)
        return out

    def _overall(self, A, topic) -> str:
        yrs = [a["year"] for a in A if a["year"]]
        meth = Counter(m for a in A for m in a["methods"]).most_common(4)
        lines = [f"Overall summary — {len(A)} studies on {topic}" + (f" ({min(yrs)}–{max(yrs)})." if yrs else ".")]
        lines.append("Methods used: " + ", ".join(f"{m} ({n})" for m, n in meth) + "." if meth else "")
        for a in A:
            f = a["summary"]["fields"]
            kf = (f.get("key_findings") or [""])[0]
            lines.append(f"• {a['cite']}: {f.get('tldr', '')}" + (f" Key finding: {kf}" if kf else ""))
        lim = [(a["summary"]["fields"].get("limitations") or [None])[0] for a in A]
        lim = [l for l in lim if l]
        if lim:
            lines.append("Common limitations: " + " ".join(lim[:3]))
        return "\n".join(l for l in lines if l)

    def _intro(self, A, topic) -> dict:
        stats = []
        for a in A:
            intro = a["summary"]["fields"].get("problem") or []
            for s in intro + a["key_numbers"][:1]:
                if re.search(r"\d", s):
                    stats.append({"text": s, "cite": a["cite"]})
        problems = [{"text": (a["summary"]["fields"].get("problem") or [""])[0], "cite": a["cite"]} for a in A
                    if a["summary"]["fields"].get("problem")]
        paras = [f"{topic[:1].upper() + topic[1:]} is attracting growing research and practitioner attention. "
                 + " ".join(f"{s['text'].rstrip('.')} {s['cite']}." for s in stats[:2]),
                 "Despite this progress, important problems remain. "
                 + " ".join(f"{p['text'].rstrip('.')} {p['cite']}." for p in problems[:3]),
                 "[Gap statement — see the Research gap tab] Accordingly, this study addresses "
                 "[research question 1] and contributes by [contribution]."]
        return {"stats": stats[:6], "problems": problems, "draft": "\n\n".join(paras),
                "funnel": ["Broad context", "Specific problem", "Gap in prior work", "Purpose & contribution"]}

    def _lit_review(self, A, topic) -> dict:
        groups = defaultdict(list)
        for a in A:
            groups[a["family"]].append(a)
        themes = []
        for fam, arts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            sents = []
            for a in arts:
                f = a["summary"]["fields"]
                k = (f.get("key_findings") or [""])[0].rstrip(".")
                k = k[0].lower() + k[1:] if k[1:2].islower() else k
                meth = _and(a["methods"][:3]) or "an empirical design"
                data = f" with {a['sample'][0]}" if a["sample"] else ""
                sents.append(f"Using {meth}{data}, {a['narrative']} report that {k}.")
            lead = (f"{len(arts)} {'studies' if len(arts) > 1 else 'study'} in this set "
                    f"{'follow' if len(arts) > 1 else 'follows'} a {fam.lower()} approach.")
            themes.append({"theme": fam, "n": len(arts), "cites": [a["cite"] for a in arts],
                           "text": f"**{fam}.** {lead} " + " ".join(sents)})
        timeline = sorted([{"year": a["year"], "cite": a["cite"], "title": a["paper"]["title"]} for a in A if a["year"]],
                          key=lambda x: x["year"])
        draft = (f"This review synthesises {len(A)} studies on {topic}, organised by research approach.\n\n"
                 + "\n\n".join(t["text"] for t in themes))
        return {"themes": themes, "timeline": timeline, "draft": draft}

    def _gaps(self, A) -> dict:
        items = []
        for a in A:
            f = a["summary"]["fields"]
            for src in ("limitations", "future_work"):
                for s in f.get(src) or []:
                    items.append({"type": classify_gap(s), "text": s, "cite": a["cite"], "source": src})
        matrix = defaultdict(lambda: defaultdict(int))
        for g in items:
            matrix[g["cite"]][g["type"]] += 1
        mcount = Counter(m for a in A for m in a["methods"])
        methods = sorted(m for m, _ in mcount.most_common(8))
        contexts = sorted({c for a in A for c in a["contexts"]} - {"Unspecified"})
        coverage = {m: {c: sum(1 for a in A if m in a["methods"] and c in a["contexts"]) for c in contexts}
                    for m in methods}
        white = [(m, c) for m in methods for c in contexts if coverage[m][c] == 0]
        by_type = Counter(g["type"] for g in items)
        draft = "Prior studies leave several gaps. " + " ".join(
            f"{t} — {', '.join(sorted({g['cite'] for g in items if g['type'] == t}))} note that "
            f"{next(g['text'] for g in items if g['type'] == t)[0].lower()}{next(g['text'] for g in items if g['type'] == t)[1:]}"
            for t, _ in by_type.most_common(3))
        if white:
            draft += (f" Moreover, no study in this set applies {white[0][0].lower()} in the "
                      f"{white[0][1].lower()} context, which remains unexplored.")
        return {"items": items, "matrix": {k: dict(v) for k, v in matrix.items()}, "types": dict(by_type),
                "coverage": coverage, "white_space": white[:8], "draft": draft}

    def _methodology(self, A) -> dict:
        mc = Counter(m for a in A for m in a["methods"])
        dc = Counter(d for a in A for d in a["designs"])
        table = [{"Study": a["cite"], "Design": ", ".join(a["designs"][:2]), "Methods": ", ".join(a["methods"][:3]),
                  "Sample": "; ".join(a["sample"][:2]) or "—", "Context": ", ".join(a["contexts"][:2])} for a in A]
        top_d = dc.most_common(1)[0][0] if dc else "a mixed design"
        top_m = ", ".join(m for m, _ in mc.most_common(3))
        draft = (f"Most reviewed studies adopt a {top_d.lower()} design and rely on {top_m}. "
                 "Building on this evidence, the proposed study will: (1) define the population and sampling frame "
                 "[population, sampling technique]; (2) estimate the required sample size a priori (e.g., with G*Power "
                 "for the planned test, α = .05, power = .80); (3) operationalise constructs with validated measures "
                 "[instrument/source]; (4) analyse data using [technique] with robustness checks; and (5) address "
                 "validity threats identified in prior work (" + "; ".join(
                     f"{g}" for g in ("single-site samples", "non-random assignment", "short horizons")) + ").")
        checklist = ["Research philosophy & approach stated", "Population, sampling frame & technique",
                     "A-priori sample size / power analysis", "Validated measurement instruments",
                     "Reliability & validity tests (α, CR, AVE, HTMT for SEM)", "Common-method bias check",
                     "Robustness / sensitivity analysis", "Ethics approval & informed consent", "Data & code availability"]
        return {"methods": dict(mc), "designs": dict(dc), "table": table, "draft": draft, "checklist": checklist}

    def _model(self, A) -> dict:
        rels = []
        for a in A:
            for r in a["relations"]:
                rels.append(dict(r, cite=a["cite"]))
        mods = [dict(m, cite=a["cite"]) for a in A for m in a["moderators"]]
        nodes = sorted({r["iv"] for r in rels} | {r["dv"] for r in rels})
        lines = ['digraph G {', 'rankdir=LR; bgcolor="transparent";',
                 'node [shape=box, style="rounded,filled", fillcolor="#E6F2F1", color="#0F766E", '
                 'fontname="Helvetica", fontsize=11];', 'edge [fontname="Helvetica", fontsize=10];']
        for i, r in enumerate(rels):
            col = "#0F766E" if r["sign"] == "+" else "#B45309"
            lines.append(f'"{r["iv"]}" -> "{r["dv"]}" [label="{r["sign"]}", color="{col}", fontcolor="{col}"];')
        for m in mods:
            lines.append(f'"{m["group"]}" [shape=ellipse, fillcolor="#FDF1E3", color="#B45309"];')
            if rels:
                lines.append(f'"{m["group"]}" -> "{rels[0]["dv"]}" [style=dashed, color="#B45309", label="moderates"];')
        lines.append("}")
        return {"relations": rels, "moderators": mods, "constructs": nodes, "dot": "\n".join(lines)}

    def _hypotheses(self, A, model) -> list[dict]:
        hyps = []
        for r in model["relations"]:
            for iv in [x.strip() for x in re.split(r"\s+and\s+|,\s*", r["iv"]) if x.strip()]:
                direction = "positive" if r["sign"] == "+" else "negative"
                hyps.append({"id": f"H{len(hyps) + 1}",
                             "text": f"There is a {direction} effect of {iv} on {r['dv']}.",
                             "iv": iv, "dv": r["dv"], "support": r["cite"], "evidence": r["evidence"], "sign": r["sign"]})
        for m in model["moderators"]:
            base = next((r for r in model["relations"] if r["cite"] == m["cite"]), None)
            if base:
                hyps.append({"id": f"H{len(hyps) + 1}",
                             "text": f"The effect of {base['iv']} on {base['dv']} is stronger for {m['group']}.",
                             "iv": base["iv"], "dv": base["dv"], "support": m["cite"], "evidence": m["evidence"],
                             "sign": "mod", "moderator": m["group"]})
        return hyps

    def _questions(self, A, gaps, model) -> list[dict]:
        qs = []
        rels = model["relations"]

        def rel_for(cite):
            r = next((x for x in rels if x["cite"] == cite), None) or (rels[0] if rels else None)
            return f"the effect of {r['iv']} on {r['dv']}" if r else "the reported effects"
        used = set()
        templates = {
            "Population / context gap": "Does {rel} hold in other sectors, institutions and countries beyond those studied by {cite}?",
            "Methodological gap": "Does {rel} remain when tested with a randomised or longitudinal design (cf. {cite})?",
            "Temporal gap": "How does {rel} evolve over a longer time horizon than examined by {cite}?",
            "Theoretical / variable gap": "Which mechanisms or omitted factors (e.g., those flagged by {cite}) explain {rel}?",
            "Data / measurement gap": "How do richer data sources (text, tables, multimodal inputs) change {rel} (cf. {cite})?",
            "Empirical gap": "What further empirical evidence is needed to confirm {rel} (cf. {cite})?",
        }
        for g in gaps["items"]:
            if g["type"] in used:
                continue
            used.add(g["type"])
            qs.append({"id": f"RQ{len(qs) + 1}", "type": g["type"],
                       "text": templates[g["type"]].format(rel=rel_for(g["cite"]), cite=g["cite"].strip("()")),
                       "from_gap": g["text"]})
        for m, c in gaps["white_space"][:2]:
            qs.append({"id": f"RQ{len(qs) + 1}", "type": "White-space (method × context)",
                       "text": f"Can {m.lower()} be applied effectively in the {c.lower()} context?",
                       "from_gap": "No selected study combines this method and context."})
        return qs[:7]

    def _future(self, A) -> dict:
        grouped = defaultdict(list)
        for a in A:
            for s in a["summary"]["fields"].get("future_work") or []:
                grouped[classify_gap(s)].append({"text": s, "cite": a["cite"]})
        draft = "Future research directions emerging from the reviewed studies:\n" + "\n".join(
            f"• {t}: " + " ".join(f"{x['text'].rstrip('.')} {x['cite']}." for x in xs) for t, xs in grouped.items())
        return {"grouped": dict(grouped), "draft": draft}

    def _llm_enrich(self, out):
        """With an LLM: paraphrased drafts (no verbatim reuse) built on the extracted structure."""
        ctx = "\n".join(f"{a['cite']} {a['paper']['title']}: {a['exec']}" for a in out["articles"])
        for key, instr in (("introduction", "a 4-paragraph funnel introduction (context, problem, gap, purpose)"),
                           ("lit_review", "a thematic literature review grouped by approach"),
                           ("gaps", "a research-gap statement naming gap types")):
            try:
                out[key]["draft"] = self.llm.generate(
                    f"Using ONLY these study summaries, write {instr} on '{out['topic']}'. Paraphrase — never copy "
                    f"sentences. Cite with the given (Author, Year) tags.\n\n{ctx}")
                out[key]["paraphrased"] = True
            except Exception:
                pass
