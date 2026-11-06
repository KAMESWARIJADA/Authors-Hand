"""Offline test-suite (pytest). API connectors are tested against recorded-format
fixtures so parsing logic is verified without network access."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from authorshand import LLM, PaperIndex, PaperSummarizer, ResearchAgent, demo, evaluation  # noqa: E402
from authorshand import connectors as C  # noqa: E402
from authorshand.pdf_reader import split_sections  # noqa: E402


# --------------------------------------------------------------- identity
def test_orcid_checksum():
    assert C.valid_orcid("0000-0002-1825-0097")       # ORCID's official example iD
    assert not C.valid_orcid("0000-0002-1825-0098")
    assert C.extract_orcid("https://orcid.org/0000-0002-1825-0097") == "0000-0002-1825-0097"


def test_researchgate_url_and_bibtex():
    assert C.ResearchGateLinker.valid_profile_url("https://www.researchgate.net/profile/Jane-Doe-3")
    assert not C.ResearchGateLinker.valid_profile_url("https://example.com/jane")
    works = C.ResearchGateLinker.parse_bibtex(demo.researchgate_export())
    assert len(works) == 3 and works[0]["year"] == 2023


def test_ris_parser():
    ris = "TY  - JOUR\nTI  - A test paper\nAU  - Doe, J.\nPY  - 2021\nJO  - Test Journal\nDO  - 10.1016/abc\nER  - \n"
    w = C.ResearchGateLinker.parse_ris(ris)
    assert w[0]["title"] == "A test paper" and w[0]["doi"] == "10.1016/abc"


def test_merge_dedups_by_doi_and_title():
    a = [C.paper(title="Deep Learning for HR", doi="10.1016/X", source="ORCID")]
    b = [C.paper(title="Deep learning for HR.", citations=12, source="OpenAlex"),
         C.paper(title="Something else", source="OpenAlex")]
    m = C.merge_works(a, b)
    assert len(m) == 2 and m[0]["citations"] == 12 and set(m[0]["sources"]) == {"ORCID", "OpenAlex"}


# ------------------------------------------------------ connector parsing
class FakeHTTP(C.HTTP):
    def __init__(self, payloads):
        super().__init__()
        self.payloads = payloads

    def get(self, url, params=None, headers=None, as_json=True):
        for key, val in self.payloads.items():
            if key in url:
                return val
        raise AssertionError(f"unexpected url {url}")


def test_orcid_works_parsing():
    payload = {"group": [{"work-summary": [{
        "put-code": 1, "title": {"title": {"value": "Paper A"}}, "type": "journal-article",
        "publication-date": {"year": {"value": "2022"}}, "journal-title": {"value": "J"},
        "external-ids": {"external-id": [{"external-id-type": "doi", "external-id-value": "10.5555/AbC"}]}}]}]}
    works = C.OrcidClient(FakeHTTP({"/works": payload})).works("0000-0002-1825-0097")
    assert works[0]["title"] == "Paper A" and works[0]["year"] == 2022 and works[0]["doi"] == "10.5555/abc"


def test_orcid_person_detects_researchgate():
    payload = {"name": {"given-names": {"value": "Jane"}, "family-name": {"value": "Doe"}},
               "researcher-urls": {"researcher-url": [
                   {"url-name": "ResearchGate", "url": {"value": "https://www.researchgate.net/profile/Jane-Doe"}}]}}
    p = C.OrcidClient(FakeHTTP({"/person": payload})).person("0000-0002-1825-0097")
    assert p["name"] == "Jane Doe" and "researchgate.net" in p["researchgate"]


def test_openalex_abstract_reconstruction():
    assert C.reconstruct_abstract({"Hello": [0], "world": [1]}) == "Hello world"


def test_arxiv_atom_parsing():
    xml = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Agents  for Science</title><summary>We study agents.</summary><published>2024-01-01</published>
    <author><name>A B</name></author><link title="pdf" href="http://arxiv.org/pdf/2401.00001v1"/></entry></feed>"""
    p = C.ArxivClient(FakeHTTP({"arxiv": xml}))._parse(xml)[0]
    assert p["title"] == "Agents for Science" and p["year"] == 2024 and p["oa_pdf"].endswith("v1")


# ------------------------------------------------------- core NLP pipeline
@pytest.fixture(scope="module")
def corpus():
    return demo.load_corpus()


def test_sections(corpus):
    secs = split_sections(corpus["papers"][0]["text"])
    for s in ("abstract", "introduction", "methodology", "results", "limitations"):
        assert s in secs


def test_summary_schema_and_grounding(corpus):
    s = PaperSummarizer().summarize(corpus["papers"][0]["text"], corpus["papers"][0]["title"])
    assert s["fields"]["tldr"] and s["fields"]["key_findings"] and s["evidence"]
    assert 0 <= s["faithfulness"] <= 1 and s["compression"] < 1


def test_hallucination_is_flagged(corpus):
    p = corpus["papers"][1]
    r = evaluation.hallucination_probe(PaperSummarizer(), p["text"], p["title"],
                                       "The copilot doubled revenue in European branches.")
    assert r["flagged"]


def test_rag_answers_with_citation(corpus):
    idx = PaperIndex(use_embeddings=False)
    for p in corpus["papers"]:
        idx.add_paper(p["text"], p["title"])
    ans = idx.ask("How many analysts took part in the copilot experiment?")
    assert "412" in ans["answer"] and "[S" in ans["answer"]


# ---------------------------------------------------------------- agent
def test_agent_routes_intents():
    a = ResearchAgent(demo_mode=True)
    assert a.plan("profile 0000-0002-1825-0097")[0] == "profile"
    assert a.plan("summarize 10.1016/j.jbusres.2020.01.001")[0] == "summarize"
    assert a.plan("literature review on attrition with 3 papers")[0] == "review"
    assert a.plan("which journal should I target for my paper")[0] == "venue"


def test_agent_end_to_end_demo():
    a = ResearchAgent(demo_mode=True)
    r = a.run("summarize the paper on credit scoring for thin-file borrowers")
    assert "error" not in r.output and r.output["summary"]["fields"]["key_findings"]
    q = a.run("What Gini coefficient did the alternative data model achieve?")
    assert q.intent == "question" and "0.58" in q.output["answer"]


# ------------------------------------------- LLM path with a fake model
class FakeLLM(LLM):
    def __init__(self):
        super().__init__("local")
        self.provider, self.model = "fake", "unit-test"

    def generate(self, prompt, system="", retries=0):
        if "Classify the research goal" in prompt:
            return json.dumps({"intent": "summarize", "args": {"identifier": "credit"}})
        if "Fill this JSON schema" in prompt or "Check each statement" in prompt:
            return "```json\n" + json.dumps({"tldr": "Alternative data raises Gini from 0.41 to 0.58.",
                                             "key_findings": ["Gini coefficient of 0.58 compared with 0.41"],
                                             "limitations": ["data from one lender"]}) + "\n```"
        return "Bullet notes."


def test_llm_engine_and_planner():
    a = ResearchAgent(llm=FakeLLM(), demo_mode=True)
    r = a.run("please look into that thin-file lending study")
    s = r.output["summary"]
    assert r.intent == "summarize" and s["engine"].startswith("fake") and s["faithfulness"] > 0.2


# ======================================================== v2: writing workspace
from authorshand import citations as CI  # noqa: E402
from authorshand import tools_hub  # noqa: E402
from authorshand.cheatsheet import cheatsheet_pdf  # noqa: E402
from authorshand.citation_map import build_map  # noqa: E402
from authorshand.journal_quality import JournalChecker, load_list  # noqa: E402
from authorshand.refresh import refresh_project  # noqa: E402
from authorshand.store import Workspace  # noqa: E402
from authorshand.writing import WritingStudio  # noqa: E402

CHAPTER = {"type": "chapter", "title": "Explainable AI in HR", "author": [{"family": "Demo", "given": "Asha"}],
           "editor": [{"family": "Rao", "given": "Kiran"}, {"family": "Sharma", "given": "Priya"}],
           "container-title": "Handbook of People Analytics", "edition": "2", "page": "45-67",
           "publisher": "Routledge", "publisher-place": "London", "issued": {"date-parts": [[2023]]}}


def test_citation_styles_keep_editors_and_italics():
    apa = CI.format_reference(CHAPTER, "apa")
    assert "K. Rao & P. Sharma (Eds.)" in apa and "*Handbook of People Analytics*" in apa and "2nd ed." in apa
    assert "Kiran Rao and Priya Sharma" in CI.format_reference(CHAPTER, "chicago-ad")
    assert "Rao K, Sharma P, editors" in CI.format_reference(CHAPTER, "vancouver")
    assert CI.in_text(CHAPTER, "apa") == "(Demo, 2023)" and CI.in_text(CHAPTER, "ieee", 3) == "[3]"
    assert "<i>Handbook of People Analytics</i>" in CI.md_to_html(CI.apa(CHAPTER))
    for st in CI.STYLES:
        assert CI.format_reference(CHAPTER, st, 1)


def test_reference_exports():
    assert "editor = {Rao, Kiran and Sharma, Priya}" in CI.to_bibtex([CHAPTER])
    ris = CI.to_ris([CHAPTER])
    assert "TY  - CHAP" in ris and "ED  - Rao, Kiran" in ris and "EP  - 67" in ris
    back = C.import_references(ris, "Zotero")[0]
    assert back["editors"] == ["Kiran Rao", "Priya Sharma"] and back["pages"] == "45-67"


def test_workspace_projects_folders_alerts(tmp_path):
    ws = Workspace(str(tmp_path / "w.db"))
    ws.user("a@b.edu")
    pid = ws.create_project("a@b.edu", "P1", topic_query="attrition")
    f = ws.add_folder(pid, "Core")
    p = demo.load_corpus()["papers"][0]
    aid = ws.add_article(pid, p, f, p["text"])
    assert ws.add_article(pid, p, f, p["text"]) is None          # de-duplicated
    ws.move_articles([aid], ws.add_folder(pid, "Inbox"))
    assert len(ws.articles(pid)) == 1 and ws.projects("a@b.edu")[0]["n_articles"] == 1
    rep = refresh_project(ws, pid, demo_mode=True)
    assert rep["new_alerts"] >= 1 and ws.alerts(pid)


def test_writing_studio_all_stages():
    papers = demo.load_corpus()["papers"]
    S = WritingStudio().build([{"paper": p, "text": p["text"]} for p in papers], "AI in organisations")
    for k in ("overall", "introduction", "lit_review", "gaps", "methodology", "model", "questions", "hypotheses", "future"):
        assert S[k]
    assert any(h["dv"] == "voluntary employee attrition" for h in S["hypotheses"])
    assert S["gaps"]["types"] and S["questions"] and "digraph" in S["model"]["dot"]


def test_cheatsheet_pdf():
    p = demo.load_corpus()["papers"][1]
    art = WritingStudio().profile_article(p, p["text"])
    assert cheatsheet_pdf(art).startswith(b"%PDF")


def test_journal_quality_demo():
    L = load_list(str(demo.DEMO_DIR / "sample_quality_list.csv"), "ABDC (sample)")
    good = JournalChecker(demo_mode=True, lists=[L]).check("Journal of Demo Analytics")
    bad = JournalChecker(demo_mode=True).check("Rapid Multidisciplinary")
    assert good["colour"] == "green" and bad["colour"] == "red" and bad["red_flags"]


def test_tool_registry_and_links():
    ids = [t["id"] for t in tools_hub.REGISTRY]
    assert len(ids) == len(set(ids)) and {"litmaps", "scispace", "jane", "zotero", "jqc"} <= set(ids)
    assert all(t["connection"] in tools_hub.CONNECTION_LABEL for t in tools_hub.REGISTRY)
    assert tools_hub.launch_url(tools_hub.get("googlescholar"), "rag survey").endswith("q=rag+survey")
    assert tools_hub.for_stage("Methodology")


def test_citation_map_demo():
    seeds = demo.load_corpus()["papers"][:2]
    m = build_map(seeds, demo_mode=True, per_seed=4)
    assert sum(n["kind"] == "seed" for n in m["nodes"]) == 2 and m["edges"]


# ================================================= v3: accounts & trust features
from authorshand import auth as AU  # noqa: E402
from authorshand import evidence as EV  # noqa: E402
from authorshand import gscholar as GS  # noqa: E402
from authorshand import review as RV  # noqa: E402


def test_signup_signin_reset_and_sessions(tmp_path):
    ws = Workspace(str(tmp_path / "a.db"))
    u, code = AU.sign_up(ws, "Dr Test", "tester@gmail.com", "0000-0002-1825-0097", "secret123", "secret123")
    assert u["email"] == "tester@gmail.com" and "secret123" not in u["password_hash"]
    assert AU.sign_in(ws, "tester@gmail.com", "secret123")["name"] == "Dr Test"
    assert AU.sign_in(ws, "0000-0002-1825-0097", "secret123")["email"] == "tester@gmail.com"   # ORCID login
    with pytest.raises(AU.AuthError):
        AU.sign_in(ws, "tester@gmail.com", "wrong-pass1")
    with pytest.raises(AU.AuthError):                                                          # duplicate sign-up
        AU.sign_up(ws, "X", "tester@gmail.com", "", "secret123", "secret123")
    with pytest.raises(AU.AuthError):                                                          # bad ORCID
        AU.sign_up(ws, "X", "", "0000-0002-1825-0098", "secret123", "secret123")
    AU.reset_password(ws, "tester@gmail.com", code, "newpass99")
    assert AU.sign_in(ws, "tester@gmail.com", "newpass99")
    tok = AU.new_session(ws, "tester@gmail.com")
    assert AU.session_account(ws, tok) == "tester@gmail.com"
    AU.end_session(ws, tok)
    assert AU.session_account(ws, tok) is None


def test_orcid_only_account_and_oidc(tmp_path):
    ws = Workspace(str(tmp_path / "b.db"))
    u, _ = AU.sign_up(ws, "O Only", "", "0000-0002-1825-0097", "secret123", "secret123")
    assert u["email"] == "orcid:0000-0002-1825-0097"
    v = AU.oidc_sign_in(ws, "orcid", {"sub": "0000-0002-1825-0097", "name": "O Only"})
    assert v["email"] == u["email"] and v["orcid_verified"] == 1
    g = AU.oidc_sign_in(ws, "google", {"email": "someone@gmail.com", "email_verified": True, "name": "G"})
    assert g["email"] == "someone@gmail.com" and "google" in g["providers"]
    assert "[auth.orcid]" in AU.oidc_secrets_toml("http://localhost:8765/oauth2callback", None, ("APP-1", "s"))


def test_backup_restore_and_delete(tmp_path):
    ws = Workspace(str(tmp_path / "c.db"))
    demo.seed_workspace(ws, "me@x.org")
    b = ws.export_user("me@x.org")
    assert b["projects"] and "password_hash" not in b["account"]
    assert ws.import_user("other@x.org", b) == len(b["projects"])
    assert ws.projects("other@x.org")[0]["n_articles"] == b["projects"][0]["articles"].__len__()
    ws.delete_user("me@x.org")
    assert ws.projects("me@x.org") == [] and ws.find_user("me@x.org") is None


def test_evidence_pages_labels_and_disagreement():
    p = demo._with_pdf_pages(demo.load_corpus()["papers"][0])
    assert p["pages_count"] == 3 and EV.text_source(p, p["text"]).startswith("Full text (PDF, 3 pages)")
    s = PaperSummarizer().summarize(p["text"], p["title"], pages=p["pages_text"])
    assert all(e["page"] for e in s["evidence"]) and {e["strength"] for e in s["evidence"]} <= {"strong", "moderate", "weak"}
    art = WritingStudio().profile_article(p, p["text"], s)
    tr = EV.trace_statements("XGBoost outperformed the other models with an AUC of 0.89 (Menon et al., 2025). "
                             "Quantum annealing transforms every HR department overnight.", [art])
    assert tr[0]["kind"] == "extracted" and tr[0]["page"] and tr[1]["strength"] == "weak"
    d = EV.disagreements([{"dv": "attrition", "sign": "+", "cite": "(A, 2020)"},
                          {"dv": "Attrition", "sign": "−", "cite": "(B, 2021)"}])
    assert d and d[0]["positive"] == ["(A, 2020)"]
    assert EV.text_source({"abstract": "x"}, "") == "Abstract only" and EV.text_source({}, "") == "Metadata only"


def test_provenance_and_corrections(tmp_path):
    ws = Workspace(str(tmp_path / "d.db"))
    pid = ws.create_project("me@x.org", "P")
    p = demo.load_corpus()["papers"][1]
    aid = ws.add_article(pid, p, None, p["text"])
    a = ws.article(aid)
    assert a["paper"]["provenance"]["title"]["source"] == "Demo corpus"
    new = dict(a["paper"], volume="99")
    new["provenance"] = EV.mark_edited(a["paper"], new)
    assert new["provenance"]["volume"]["source"] == "Edited by you"
    ex = {"methods": ["Survey / questionnaire"], "table_sample": "corrected sample"}
    art = WritingStudio().profile_article(dict(a["paper"], extraction=ex), a["text"])
    assert art["methods"] == ["Survey / questionnaire"] and art["table"]["Sample"] == "corrected sample"


def test_custom_lexicon_terms():
    p = demo.load_corpus()["papers"][3]
    art = WritingStudio(lexicon={"methods": {"Early-warning analytics": ["early-warning"]}}).profile_article(p, p["text"])
    assert "Early-warning analytics" in art["methods"]
    assert art["method_sources"]["Early-warning analytics"]["sentence"]


def test_systematic_review_workflow(tmp_path):
    ws = Workspace(str(tmp_path / "e.db"))
    pid = ws.create_project("me@x.org", "Review")
    RV.run_search(ws, pid, ["OpenAlex", "Semantic Scholar"], "explainable machine learning", {}, 5, demo_mode=True)
    c = RV.prisma_counts(ws, pid)
    assert c["identified"] == sum(c["by_database"].values()) and c["duplicates_removed"] >= 1
    recs = RV.records(ws, pid)
    RV.set_decision(ws, recs[0]["id"], "include")
    RV.set_decision(ws, recs[1]["id"], "exclude", "Wrong study design")
    c = RV.prisma_counts(ws, pid)
    assert c["included"] == 1 and c["exclusion_reasons"] == {"Wrong study design": 1}
    para = RV.methods_paragraph(ws, pid, {"review_type": "Systematic review", "question": "Q?"})
    assert "OpenAlex" in para and "duplicates" in para and "digraph" in RV.prisma_dot(c)


def test_google_scholar_parsing():
    assert GS.author_id("https://scholar.google.com/citations?user=EicYvbwAAAAJ&hl=en") == "EicYvbwAAAAJ"
    snap = GS.parse_serpapi({"author": {"name": "X", "interests": [{"title": "AI"}]},
                             "cited_by": {"table": [{"citations": {"all": 100, "since_2021": 60}},
                                                    {"h_index": {"all": 5, "since_2021": 4}},
                                                    {"i10_index": {"all": 3, "since_2021": 2}}],
                                          "graph": [{"year": 2024, "citations": 30}, {"year": 2025, "citations": 40}]},
                             "articles": [{"title": "P", "authors": "A, B", "year": "2024",
                                           "cited_by": {"value": 7}}]})
    assert snap["metrics"]["citations"]["since_year"] == 2021 and snap["graph"][2025] == 40
    assert snap["articles"][0]["citations"] == 7
    m = GS.manual_snapshot(10, 8, 2, 2, 1, 1, 2021, {"2024": 5})
    assert m["graph"] == {2024: 5} and "Entered by you" in m["source"]


def test_real_paper_evaluation_protocol():
    p = demo._with_pdf_pages(demo.load_corpus()["papers"][0])
    r = evaluation.evaluate_own_papers(PaperSummarizer(), [{"title": p["title"], "text": p["text"]}])
    assert "failures" in r and (r["n"] == 1 or len(r["failures"]))


def test_citation_notes_tags_and_new_types():
    rec = CI.from_paper({"title": "T", "authors": ["A B"], "year": 2024, "type": "dataset", "publisher": "Zenodo",
                         "notes": "my note", "tags": "hr, ai"})
    assert "[Data set]" in CI.apa(rec)
    ris = CI.to_ris([rec])
    assert "N1  - my note" in ris and "KW  - hr" in ris
    assert "note = {my note}" in CI.to_bibtex([rec])


def test_publications_list_and_coauthors():
    from authorshand import ResearchAgent, publications as PB
    prof = ResearchAgent(demo_mode=True).tool_profile(demo.DEMO_ORCID, "")
    works = PB.merge_scholar(prof.works, [{"title": prof.works[0]["title"], "citations": 99},
                                          {"title": "A Scholar-only paper", "authors": ["A. Demo", "Z. Khan"],
                                           "year": 2024, "venue": "Some Conference Proceedings", "citations": 3}])
    works = PB.merge_extra(works, [{"title": "A Scholar-only paper"}, {"title": "RG chapter", "type": "book-chapter",
                                                                        "authors": ["A. Demo"], "source": "ResearchGate"}])
    df = PB.publication_table(works, "A. Demo", [{"name": "ABDC", "index": {"t:" + __import__(
        "authorshand.text_utils", fromlist=["x"]).normalize_title(prof.works[0]["venue"]): "A*"}}])
    assert len(df) == len(prof.works) + 2
    assert df["Citations (Scholar)"].max() == 99 and (df["Indexing (your lists)"] == "ABDC: A*").any()
    assert set(df["Type"]) >= {"Journal article", "Book chapter"} and df["Citation"].str.len().min() > 10
    ct = PB.coauthor_table(works, "A. Demo")
    assert "A. Demo" not in set(ct["Co-author"]) and ct.iloc[0]["Joint papers"] >= ct.iloc[-1]["Joint papers"]
    assert PB.summary_counts(df)["total"] == len(df)


def test_manual_papers_yearwise_and_official_email(tmp_path):
    from authorshand import publications as PB, verify as VF, auth as AU
    w = PB.manual_work("Case study", "HR at a Demo Bank", "Jada, K.; Rao, P.", "2024", "Demo Case Collection",
                       indexing="ABDC: B")
    assert w["type"] == "case-study" and PB.type_label(w) == "Case study" and w["authors"] == ["Jada, K.", "Rao, P."]
    df = PB.publication_table([w, PB.manual_work("Conference paper", "Paper X", "Jada, K.", "2023", "IIM Conf")], "Jada")
    assert "ABDC: B" in set(df["Indexing (your lists)"])
    ys = PB.year_summary(df)
    assert set(ys["Year"]) == {2023, 2024} and ys["Papers"].sum() == 2
    code, pending = VF.new_code()
    assert not VF.check_code(pending, "x")[0] and VF.check_code(pending, code)[0]
    assert VF.is_institutional("k.jada@ssim.ac.in") and not VF.is_institutional("k@gmail.com")
    ws = Workspace(str(tmp_path / "o.db"))
    u, _ = AU.sign_up(ws, "K", "k@gmail.com", "", "research2026", "research2026")
    ws.update_user(u["email"], official_email="k.jada@ssim.ac.in", official_verified=1.0)
    assert AU.sign_in(ws, "k.jada@ssim.ac.in", "research2026")["email"] == "k@gmail.com"
    toml = AU.oidc_secrets_toml("http://localhost:8501/oauth2callback", None, None, "x", ("lid", "lsec"))
    assert "[auth.linkedin]" in toml and "client_secret_post" in toml


def test_openalex_fallback_when_orcid_not_linked(monkeypatch):
    """OpenAlex 404 for /authors/orcid:… → works found by DOI/title, author guessed from them, citations kept."""
    from authorshand import connectors as CN
    from authorshand.profile import ResearcherProfile
    oid = "0000-0002-9782-3067"
    orcid_works = [CN.paper(title="Machine learning for HR attrition in Indian banks", doi="10.1/a", year=2024,
                            source="ORCID"),
                   CN.paper(title="Generative AI copilots and moral disengagement at work", year=2025, source="ORCID")]
    def oaw(title, doi, cites):
        return CN.paper(title=title, doi=doi, citations=cites, source="OpenAlex", year=2024,
                        oa_authors=[{"id": "A123", "name": "Kameswari Jada", "orcid": ""}])
    monkeypatch.setattr(CN.OrcidClient, "person", lambda self, o: {"name": "Kameswari Jada", "biography": "",
                        "keywords": [], "urls": [], "researchgate": ""})
    monkeypatch.setattr(CN.OrcidClient, "employments", lambda self, o: [])
    monkeypatch.setattr(CN.OrcidClient, "works", lambda self, o: [dict(w) for w in orcid_works])
    def boom(self, o):
        raise RuntimeError("404 Client Error: Not Found")
    monkeypatch.setattr(CN.OpenAlexClient, "author_by_orcid", boom)
    monkeypatch.setattr(CN.OpenAlexClient, "works_by_orcid", lambda self, o: [])
    monkeypatch.setattr(CN.OpenAlexClient, "works_by_dois", lambda self, d: [oaw(orcid_works[0]["title"], "10.1/a", 12)])
    monkeypatch.setattr(CN.OpenAlexClient, "work_by_title", lambda self, t, y=None: oaw(t, "10.1/b", 5)
                        if "copilots" in t.lower() else None)
    monkeypatch.setattr(CN.OpenAlexClient, "author_by_id", lambda self, a: {"openalex_id": a, "name": "K. Jada",
                        "cited_by_count": 17, "h_index": 2, "i10_index": 1, "counts_by_year": [{"year": 2025,
                        "cited_by_count": 9}], "institutions": ["SSIM"]})
    monkeypatch.setattr(CN.OpenAlexClient, "author_works", lambda self, a, max_works=400: [])
    p = ResearcherProfile.from_orcid(oid)
    m = p.metrics()
    assert m["works"] == 2 and m["citations"] == 17 and m["h_index"] == 2
    assert p.citations_by_year() == {2025: 9} and "paper by paper" in p.notes[0] and not p.warnings
    assert p.openalex["openalex_id"] == "A123"
    # next time the saved OpenAlex id is used directly (no warning, no paper-by-paper search)
    monkeypatch.setattr(CN.OpenAlexClient, "works_by_dois", lambda self, d: (_ for _ in ()).throw(AssertionError()))
    p2 = ResearcherProfile.from_orcid(oid, openalex_id="A123")
    assert p2.metrics()["citations"] == 17 and not p2.warnings and "saved" in p2.notes[0]


def test_scholar_paste_parser():
    txt = ("Employee attrition prediction using machine learning\nK Jada, P Machani\n"
           "International Journal of Management 12 (3), 45-60, 2021\n85\t2021\n"
           "Cited by\nAll\tSince 2021\nCitations\t2,316\t1785\nh-index\t18\t15\ni10-index\t27\t22\n"
           "2019\n2020\n2021\n90\n120\n142\n")
    snap = GS.parse_pasted_profile(txt)
    assert snap["metrics"]["citations"] == {"all": 2316, "since": 1785, "since_year": 2021}
    assert snap["metrics"]["h_index"]["all"] == 18 and snap["metrics"]["i10_index"]["since"] == 22
    assert snap["graph"] == {2019: 90, 2020: 120, 2021: 142}
    assert [a["citations"] for a in snap["articles"]] == [85]


def test_orcid_vs_scholar_reconcile():
    from authorshand import publications as PB
    orcid = [{"title": "Machine Learning for Employee Attrition in Indian Banks", "year": 2024, "doi": "10.1/a",
              "citations": 3, "sources": ["ORCID"]},
             {"title": "A paper only on ORCID about HR analytics", "year": 2023, "sources": ["ORCID"]}]
    scholar = [{"title": "Machine learning for employee attrition in Indian banks", "year": 2023, "citations": 9},
               {"title": "A Scholar-only conference paper on generative AI", "year": 2025, "citations": 1}]
    r = PB.reconcile(orcid, scholar)
    assert list(r["Status"]) == ["✅ In both", "🟠 Only on ORCID", "🔵 Only on Google Scholar"]
    assert r.iloc[0]["Citations (Scholar)"] == 9 and r.iloc[0]["Note"] == "year differs"
    m = PB.compare_metrics({"citations": 3, "h_index": 1, "i10_index": 0}, {"metrics": {"citations": {"all": 10}}}, 2, 2)
    assert m.iloc[1]["Google Scholar"] == 10
