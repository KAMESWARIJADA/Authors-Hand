"""
Optional REST API (FastAPI) so Author's Hand can be plugged into other systems
(e.g. an institutional research portal).   Run:  uvicorn api:app --reload
Interactive docs at http://127.0.0.1:8000/docs
"""
from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from authorshand import PaperSummarizer, ResearchAgent, Settings, read_pdf
from authorshand.connectors import valid_orcid

settings = Settings()
agent = ResearchAgent(settings=settings)
app = FastAPI(title="Author's Hand API", version="1.0.0",
              description="Autonomous AI Research Agent — summarise papers, profile researchers, review literature.")


class Goal(BaseModel):
    goal: str


class Question(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok", "engine": agent.llm.label, "demo_mode": agent.demo}


@app.post("/agent")
def run_agent(g: Goal):
    r = agent.run(g.goal)
    out = dict(r.output)
    if "profile" in out:
        p = out.pop("profile")
        out["profile"] = {"name": p.name, "orcid": p.orcid, "works": len(p.works)}
    if "review" in out:
        rv = out["review"]
        out["review"] = {"matrix": rv["matrix"].to_dict("records"), "narrative": rv["narrative"],
                         "references": rv["references"]}
        out.pop("papers", None)
    return {"intent": r.intent, "plan": r.plan, "trace": [s.__dict__ for s in r.trace],
            "seconds": r.seconds, "output": out}


@app.post("/summarize")
async def summarize(file: UploadFile = File(...)):
    raw = await file.read()
    text = read_pdf(raw) if file.filename.lower().endswith(".pdf") else raw.decode("utf-8", "ignore")
    s = PaperSummarizer(agent.llm).summarize(text)
    agent.tool_index(text, s["title"])
    return s


@app.post("/ask")
def ask(q: Question):
    return agent.index.ask(q.question)


@app.get("/profile/{orcid}")
def profile(orcid: str):
    if not valid_orcid(orcid):
        raise HTTPException(400, "Invalid ORCID iD")
    p = agent.tool_profile(orcid)
    return {"name": p.name, "metrics": p.metrics(), "themes": p.themes(), "health": p.health_audit(),
            "ideas": p.next_paper_ideas(agent.llm), "researchgate": p.researchgate}
