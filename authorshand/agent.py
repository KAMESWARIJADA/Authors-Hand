"""The autonomous research agent: Plan → Act (tools) → Reflect → Report.

Given a natural-language goal, the agent decides which tools to call, in what
order, checks the quality of its own output (faithfulness gate) and retries in
strict mode when evidence support is weak. Every step is recorded in a trace so
the user can audit exactly what the agent did.

Planning: an LLM planner (JSON plan) when a model is configured, otherwise a
deterministic intent router — so the agent is autonomous even with no key.
The same tools are exposed as LangChain `StructuredTool`s (`as_langchain_tools`)
for use with any tool-calling chat model / LangGraph.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from . import connectors, demo
from .config import Settings
from .connectors import ARXIV_RE, clean_doi, extract_orcid
from .litreview import LiteratureReviewer
from .llm import LLM
from .profile import ResearcherProfile
from .rag import PaperIndex
from .summarizer import PaperSummarizer

INTENTS = {
    "profile": "Analyse a researcher from an ORCID iD (and ResearchGate link)",
    "summarize": "Find and summarise one paper (DOI, arXiv id, title or uploaded text)",
    "review": "Search a topic, read several papers and write a literature review",
    "venue": "Recommend journals for a manuscript / abstract",
    "question": "Answer a question from the papers already loaded",
}


@dataclass
class Step:
    n: int
    thought: str
    tool: str
    input: str
    output: str = ""
    seconds: float = 0.0
    ok: bool = True


@dataclass
class AgentResult:
    goal: str
    intent: str
    plan: list
    trace: list = field(default_factory=list)
    output: dict = field(default_factory=dict)
    seconds: float = 0.0


class ResearchAgent:
    def __init__(self, llm: LLM | None = None, settings: Settings | None = None,
                 profile: ResearcherProfile | None = None, demo_mode: bool | None = None):
        self.s = settings or Settings()
        self.llm = llm or LLM(self.s.llm_provider, self.s.llm_model)
        self.demo = self.s.demo_mode if demo_mode is None else demo_mode
        self.profile = profile
        self.summarizer = PaperSummarizer(self.llm)
        self.reviewer = LiteratureReviewer(self.llm)
        self.index = PaperIndex(self.llm, self.s.chunk_size, self.s.chunk_overlap, use_embeddings=False)
        self.loaded: list[str] = []

    # ================================================================= tools
    def tool_search(self, query: str, n: int = 5) -> list[dict]:
        return demo.search(query, n) if self.demo else connectors.search_all(query, n, self.s)

    def tool_get_paper(self, identifier: str) -> dict:
        return demo.get(identifier) if self.demo else connectors.resolve_identifier(identifier, self.s)

    def tool_read(self, paper: dict) -> str:
        if paper.get("text"):
            return paper["text"]
        return connectors.fetch_fulltext(paper, self.s)

    def tool_summarize(self, text: str, title: str, strict: bool = False) -> dict:
        return self.summarizer.summarize(text, title=title, strict=strict)

    def tool_index(self, text: str, title: str):
        if title not in self.loaded:
            self.index.add_paper(text, title)
            self.loaded.append(title)

    def tool_profile(self, orcid: str, researchgate_url: str = "", openalex_id: str = "") -> ResearcherProfile:
        if self.demo or orcid == demo.DEMO_ORCID:
            p = ResearcherProfile.from_dict(demo.load_profile_dict())
            p.add_researchgate_export(demo.researchgate_export())
            p.researchgate = researchgate_url or "https://www.researchgate.net/profile/A-Demo"
        else:
            p = ResearcherProfile.from_orcid(orcid, self.s, researchgate_url, openalex_id=openalex_id)
        self.profile = p
        return p

    # =============================================================== planning
    def plan(self, goal: str) -> tuple[str, dict, list[str]]:
        intent, args = None, {}
        if self.llm.available:
            try:
                d = self.llm.generate_json(
                    f"Classify the research goal into one intent {list(INTENTS)} ({INTENTS}). Extract "
                    f"arguments: query, identifier, orcid, n (papers, default 4). Goal: {goal!r}. "
                    f'Return {{"intent": ..., "args": {{...}}}}')
                if d.get("intent") in INTENTS:
                    intent, args = d["intent"], d.get("args") or {}
            except Exception:
                intent = None
        if intent is None:
            intent, args = self._route(goal)
        steps = {
            "profile": ["validate ORCID", "fetch ORCID + OpenAlex + ResearchGate", "merge & de-duplicate works",
                        "compute bibliometrics", "cluster themes", "audit profile health", "find gap opportunities"],
            "summarize": ["resolve identifier", "fetch open-access full text", "segment sections",
                          "structured summary", "ground claims (faithfulness)", "reflect / retry if weak",
                          "personalise to my profile", "index for Q&A"],
            "review": ["federated search", "rank & select papers", "read each paper",
                       "summarise each paper", "build comparison matrix", "synthesise review + gaps"],
            "venue": ["search similar published papers", "score journal fit"],
            "question": ["retrieve evidence chunks", "answer with citations"],
        }[intent]
        return intent, args, steps

    def _route(self, goal: str) -> tuple[str, dict]:
        g = goal.lower()
        orcid = extract_orcid(goal)
        if orcid or "orcid" in g or "my profile" in g:
            return "profile", {"orcid": orcid or demo.DEMO_ORCID}
        if any(w in g for w in ("journal", "venue", "where to publish", "where should i publish")):
            return "venue", {"query": goal}
        if any(w in g for w in ("review", "survey", "state of the art", "literature", "compare papers")):
            n = re.search(r"\b(\d{1,2})\s+papers?", g)
            q = re.sub(r"(?i)^.*?\b(review|survey|literature)\b( review)?( of| on| about)?", "", goal)
            q = re.sub(r"(?i)\s*(with|using|from)?\s*\d{1,2}\s+papers?", "", q).strip(" :?.")
            return "review", {"query": q or goal, "n": int(n.group(1)) if n else 4}
        if clean_doi(goal) or ARXIV_RE.search(goal) or g.startswith(("summarize", "summarise", "explain paper")):
            ident = clean_doi(goal) or (ARXIV_RE.search(goal).group(1) if ARXIV_RE.search(goal) else
                                         re.sub(r"(?i)^(summari[sz]e|explain paper)\s*(the paper)?\s*", "", goal))
            return "summarize", {"identifier": ident.strip(" :\"'")}
        if self.loaded:
            return "question", {"query": goal}
        return "summarize", {"identifier": goal}

    # ================================================================ running
    def run(self, goal: str, verbose: bool = False) -> AgentResult:
        t0 = time.time()
        intent, args, steps = self.plan(goal)
        res = AgentResult(goal=goal, intent=intent, plan=steps)
        log = res.trace

        def act(thought, tool, inp, fn):
            st = Step(len(log) + 1, thought, tool, str(inp)[:160])
            t = time.time()
            try:
                out = fn()
                st.output = _brief(out)
                return out
            except Exception as e:
                st.ok, st.output = False, f"ERROR: {e}"
                raise
            finally:
                st.seconds = round(time.time() - t, 2)
                log.append(st)
                if verbose:
                    print(f"[{st.n}] {tool}({st.input}) → {st.output}")

        try:
            if intent == "profile":
                orcid = args.get("orcid") or demo.DEMO_ORCID
                ok = act("Check the ORCID checksum before calling any API", "validate_orcid", orcid,
                         lambda: connectors.valid_orcid(orcid))
                if not ok:
                    raise ValueError("Invalid ORCID iD")
                p = act("Build the unified profile from ORCID, OpenAlex and ResearchGate", "build_profile",
                        orcid, lambda: self.tool_profile(orcid, args.get("researchgate", "")))
                res.output = {
                    "profile": p,
                    "metrics": act("Compute bibliometrics", "metrics", p.name, p.metrics),
                    "themes": act("Cluster research themes & momentum", "themes", p.name, p.themes),
                    "health": act("Audit discoverability", "health_audit", p.name, p.health_audit),
                    "ideas": act("Find untouched theme intersections", "gap_opportunities", p.name,
                                 lambda: p.next_paper_ideas(self.llm)),
                }
            elif intent == "summarize":
                ident = args.get("identifier") or goal
                paper = act("Resolve the identifier to a paper record", "get_paper", ident,
                            lambda: self.tool_get_paper(ident))
                text = act("Get the full text (open access PDF, else abstract)", "read_fulltext",
                           paper["title"], lambda: self.tool_read(paper))
                summ = act("Write a structured, evidence-grounded summary", "summarize", paper["title"],
                           lambda: self.tool_summarize(text, paper["title"]))
                if summ["faithfulness"] < self.s.min_faithfulness:
                    summ = act(f"Faithfulness {summ['faithfulness']:.2f} below gate "
                               f"{self.s.min_faithfulness} → retry in strict mode", "summarize_strict",
                               paper["title"], lambda: self.tool_summarize(text, paper["title"], strict=True))
                rel = None
                if self.profile:
                    rel = act("Relate the paper to my own publications", "relevance_to_me", paper["title"],
                              lambda: PaperSummarizer.relevance_to_profile(summ, self.profile.works))
                act("Index the paper so follow-up questions can be answered", "index_paper", paper["title"],
                    lambda: self.tool_index(text, paper["title"]))
                res.output = {"paper": paper, "summary": summ, "relevance": rel}
            elif intent == "review":
                q, n = args.get("query") or goal, int(args.get("n") or 4)
                hits = act("Federated search across scholarly indexes", "search_papers", q,
                           lambda: self.tool_search(q, n))
                papers = []
                for h in hits[:n]:
                    text = act("Read candidate paper", "read_fulltext", h["title"], lambda h=h: self.tool_read(h))
                    papers.append(dict(h, text=text))
                    self.tool_index(text, h["title"])
                rev = act("Synthesise matrix, consensus, gaps and narrative", "literature_review",
                          f"{len(papers)} papers", lambda: self.reviewer.review(papers, q))
                res.output = {"review": rev, "papers": papers}
            elif intent == "venue":
                q = args.get("query") or goal
                cands = act("Find similar published papers", "search_papers", q, lambda: self.tool_search(q, 10))
                prof = self.profile or ResearcherProfile(orcid="")
                res.output = {"venues": act("Score journal fit", "recommend_venues", q,
                                            lambda: prof.recommend_venues(q, cands))}
            elif intent == "question":
                q = args.get("query") or goal
                res.output = act("Retrieve evidence and answer with citations", "ask_papers", q,
                                 lambda: self.index.ask(q))
        except Exception as e:
            res.output = dict(res.output, error=str(e))
        res.seconds = round(time.time() - t0, 2)
        return res

    # ===================================================== LangChain bridge
    def as_langchain_tools(self):
        """Expose the agent's tools to any LangChain tool-calling model / LangGraph."""
        from langchain_core.tools import StructuredTool

        def search_papers(query: str, n: int = 5) -> str:
            """Search scholarly literature (OpenAlex, Semantic Scholar, arXiv)."""
            return str([{k: p.get(k) for k in ("title", "year", "venue", "doi", "citations")}
                        for p in self.tool_search(query, n)])

        def summarize_paper(identifier: str) -> str:
            """Summarise a paper given a DOI, arXiv id or title. Returns structured JSON."""
            r = self.run(f"summarize {identifier}")
            return str(r.output.get("summary", {}).get("fields", r.output))

        def researcher_profile(orcid: str) -> str:
            """Analyse a researcher by ORCID iD: metrics, themes, health, gaps."""
            r = self.run(f"profile {orcid}")
            return str({k: v for k, v in r.output.items() if k != "profile"})

        def ask_papers(question: str) -> str:
            """Answer a question from loaded papers with [S#] citations."""
            return self.index.ask(question)["answer"]

        return [StructuredTool.from_function(f) for f in
                (search_papers, summarize_paper, researcher_profile, ask_papers)]


def _brief(out) -> str:
    if isinstance(out, ResearcherProfile):
        return f"profile '{out.name}' with {len(out.works)} works"
    if isinstance(out, list):
        return f"{len(out)} items" + (f": {out[0].get('title', '')[:60]}…" if out and isinstance(out[0], dict) else "")
    if isinstance(out, dict):
        if "faithfulness" in out:
            return f"summary ({out['summary_words']} words, faithfulness {out['faithfulness']:.2f})"
        if "title" in out:
            return f"paper: {out['title'][:70]}"
        if "matrix" in out:
            return f"review of {len(out['matrix'])} papers"
        if "score" in out:
            return f"score {out['score']}"
        return ", ".join(list(out)[:5])
    if isinstance(out, str):
        return f"{len(out.split())} words of text"
    return str(out)[:80]
