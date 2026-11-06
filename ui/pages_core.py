"""Dashboard · Library · Writing Studio · Paper Reader."""
from __future__ import annotations

import html
import io
import time
import zipfile
from collections import Counter
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from authorshand import PaperIndex, demo, read_pdf
from authorshand import citations as C
from authorshand import connectors
from authorshand.cheatsheet import cheatsheet_pdf
from authorshand.exporters import LABELS
from authorshand.refresh import is_due, refresh_project
from authorshand.summarizer import FIELDS
from authorshand.writing import STAGES, WritingStudio

from .common import (profile_is_demo, empty_project_help, my_works, PALETTE, copy_box, current_settings, demo_banner, fig_style, hero, integrity_note, llm,
                     need_project, project, stat_row, summary_for, tool_buttons, workspace)


# =================================================================== DASHBOARD
import threading

_JOBS: dict = {}


def _start_refresh(pid, settings, demo_mode):
    from authorshand.store import DEFAULT_DB, Workspace
    job = {"done": False, "report": None}
    _JOBS[pid] = job

    def work():
        try:
            job["report"] = refresh_project(Workspace(DEFAULT_DB), pid, settings, demo_mode)
        except Exception as e:  # never crash the UI
            job["report"] = {"project": "", "new_alerts": 0, "citations_updated": 0, "retracted": [],
                             "errors": [str(e)], "mode": "error"}
        job["done"] = True

    threading.Thread(target=work, daemon=True).start()
def page_dashboard():
    hero("Project dashboard", "Your research at a glance, your projects, new papers found by auto-refresh, and the "
         "shape of your library.")
    demo_banner()
    ws = workspace()
    # ---- my research at a glance (from My Research Profile)
    from authorshand import ResearchAgent, gscholar
    u = ws.user(st.session_state.account)
    pdemo = profile_is_demo()
    oid = u.get("orcid") or (demo.DEMO_ORCID if pdemo else "")
    if oid and st.session_state.get("profile") is None:
        with st.spinner("Reading your ORCID / OpenAlex record…"):
            try:
                st.session_state.profile = ResearchAgent(llm=llm(), settings=current_settings(),
                                                         demo_mode=pdemo).tool_profile(
                    oid, u.get("researchgate", ""), (u.get("prefs") or {}).get("openalex_id", ""))
                st.session_state.profile_refreshed = datetime.now()
            except Exception as e:
                st.caption(f"ORCID / OpenAlex not reachable right now ({e}).")
    prof = st.session_state.get("profile")
    gs = u.get("gscholar") or (gscholar.DEMO_SNAPSHOT if pdemo else {})
    mine = my_works()
    if mine or prof or gs:
        st.markdown("#### 👤 My research at a glance")
        gm = gs.get("metrics") or {}
        stat_row([(len(mine) or "—", "my papers"),
                  (prof.metrics()["citations"] if prof else "—", "citations (OpenAlex)"),
                  ((gm.get("citations") or {}).get("all", "—"), "citations (Google Scholar)"),
                  ((gm.get("h_index") or {}).get("all") or (prof.metrics()["h_index"] if prof else "—"), "h-index"),
                  (len(ws.projects(st.session_state.account)), "projects")])
        if st.button("Open My Research Profile →"):
            st.switch_page(st.session_state.pages["profile"])
    else:
        st.info("Link your ORCID iD, Google Scholar or ResearchGate (Settings & privacy) — your papers, citations "
                "and h-index then appear here.")
    st.markdown("#### 📁 Current project")
    p = need_project()
    if not p:
        return
    arts = ws.articles(p["id"])
    if not arts:
        empty_project_help(p, "dash")
        return
    alerts = ws.alerts(p["id"])
    nxt = (p["last_refresh"] + p["auto_refresh_hours"] * 3600) if p["auto_refresh_hours"] else None
    stat_row([(len(arts), "articles"), (len(ws.folders(p["id"])), "folders"), (len(alerts), "new papers to review"),
              (datetime.fromtimestamp(p["last_refresh"]).strftime("%d %b %H:%M") if p["last_refresh"] else "never",
               "last refresh"),
              (datetime.fromtimestamp(nxt).strftime("%d %b %H:%M") if nxt and p["last_refresh"] else "on open",
               "next auto-refresh")])
    st.write("")

    @st.fragment(run_every="20s")
    def auto_refresh():
        """Due projects refresh in a BACKGROUND thread, so the page never freezes on slow networks."""
        proj = project()
        on = st.toggle("Auto-refresh in the background (new & citing papers, citation counts, retractions)",
                       value=True, key="auto_toggle")
        job = _JOBS.get(proj["id"]) if proj else None
        if job and job["done"]:
            rep = job["report"]
            _JOBS.pop(proj["id"], None)
            st.session_state.refresh_log.insert(0, (time.strftime("%H:%M"), rep))
            st.toast(f"Auto-refresh: {rep['new_alerts']} new papers, {rep['citations_updated']} citation updates")
            st.rerun()
        elif job:
            st.caption("⏳ Refreshing in the background…")
        elif on and proj and is_due(proj):
            _start_refresh(proj["id"], current_settings(), st.session_state.get("demo_mode", True))
            st.caption("⏳ Refresh started in the background…")
    auto_refresh()

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("🔄 Refresh now", type="primary"):
            with st.spinner("Searching for new and citing papers…"):
                rep = refresh_project(ws, p["id"], current_settings(), st.session_state.demo_mode)
            st.session_state.refresh_log.insert(0, (time.strftime("%H:%M"), rep))
            st.rerun()
        for t, rep in st.session_state.refresh_log[:3]:
            st.caption(f"{t} · {rep['mode']} · {rep['new_alerts']} new · {rep['citations_updated']} citation updates"
                       + (f" · ⚠ retracted: {rep['retracted']}" if rep["retracted"] else "")
                       + (f" · errors: {rep['errors']}" if rep["errors"] else ""))
    with c2:
        st.markdown(f"**Saved topic:** {p['topic_query'] or '—'}  ·  **style:** {C.STYLES[p['citation_style']]}")
        tq = st.text_input("Edit saved topic search", value=p["topic_query"], key="tq_edit")
        if tq != p["topic_query"]:
            ws.update_project(p["id"], topic_query=tq)

    st.markdown("#### 🔔 New papers since last refresh")
    if not alerts:
        st.caption("Nothing new — run a refresh or wait for the next automatic one.")
    folders = {f["name"]: f["id"] for f in ws.folders(p["id"])}
    for a in alerts[:10]:
        pa = a["paper"]
        cols = st.columns([6, 2, 1, 1])
        cols[0].markdown(f"**{pa.get('title', '')}**  \n<span class='small'>{', '.join((pa.get('authors') or [])[:3])} · "
                         f"{pa.get('year', '')} · {pa.get('venue', '')} · {a['reason']}</span>", unsafe_allow_html=True)
        fsel = cols[1].selectbox("Folder", list(folders), key=f"af{a['id']}", label_visibility="collapsed")
        if cols[2].button("Add", key=f"aa{a['id']}"):
            ws.add_article(p["id"], pa, folders[fsel], pa.get("text", ""))
            ws.mark_alerts_seen([a["id"]])
            st.rerun()
        if cols[3].button("Dismiss", key=f"ad{a['id']}"):
            ws.mark_alerts_seen([a["id"]])
            st.rerun()

    if arts:
        st.markdown("#### 📊 Library at a glance")
        df = pd.DataFrame([{"year": a["year"], "venue": a["venue"] or "—", "status": a["status"],
                            "citations": a["citations"] or 0, "title": a["title"]} for a in arts])
        g1, g2, g3 = st.columns(3)
        yc = df.dropna(subset=["year"]).groupby("year").size().reset_index(name="articles")
        g1.plotly_chart(fig_style(px.bar(yc, x="year", y="articles", title="Articles by year",
                                         color_discrete_sequence=[PALETTE[0]]), 280, False), width="stretch")
        sc = df.groupby("status").size().reset_index(name="n")
        g2.plotly_chart(fig_style(px.pie(sc, names="status", values="n", hole=.55, title="Reading status"), 280),
                        width="stretch")
        vc = df.groupby("venue").size().reset_index(name="n").sort_values("n").tail(6)
        g3.plotly_chart(fig_style(px.bar(vc, y="venue", x="n", orientation="h", title="Top venues",
                                         color_discrete_sequence=[PALETTE[1]]), 280, False), width="stretch")


# ===================================================================== LIBRARY
def _add_articles_panel(p):
    ws = workspace()
    folders = ws.folders(p["id"])
    fmap = {f["name"]: f["id"] for f in folders}
    target = st.selectbox("Add into folder", list(fmap), key="add_target")
    t1, t2, t3, t4, t5 = st.tabs(["🔎 Search online", "🆔 DOI / arXiv", "📄 Upload PDF", "📥 Import BibTeX / RIS",
                                  "👤 From my ORCID"])
    with t1:
        q = st.text_input("Search OpenAlex + Semantic Scholar + arXiv", key="lib_q",
                          value="explainable machine learning HR" if st.session_state.demo_mode else "")
        if st.button("Search", key="lib_search") and q:
            with st.spinner("Searching…"):
                try:
                    st.session_state.lib_hits = (demo.search(q, 8) if st.session_state.demo_mode
                                                 else connectors.search_all(q, 8, current_settings()))
                except Exception as e:
                    st.error(f"Search failed: {e}")
        hits = st.session_state.get("lib_hits") or []
        if hits:
            df = pd.DataFrame([{"add": False, "title": h["title"], "year": h.get("year"), "venue": h.get("venue"),
                                "citations": h.get("citations", 0), "open access": "✔" if h.get("oa_pdf") or h.get("text") else ""}
                               for h in hits])
            ed = st.data_editor(df, hide_index=True, width="stretch", key="hits_ed",
                                column_config={"add": st.column_config.CheckboxColumn("Add")})
            fetch = st.checkbox("Download open-access full text when available", value=True)
            if st.button("Add selected to project", type="primary"):
                n = 0
                for i, row in ed.iterrows():
                    if row["add"]:
                        h = hits[i]
                        text = h.get("text") or (connectors.fetch_fulltext(h, current_settings()) if fetch and not
                                                 st.session_state.demo_mode else "")
                        n += bool(ws.add_article(p["id"], h, fmap[target], text))
                st.success(f"Added {n} article(s) to “{target}”.")
    with t2:
        ident = st.text_input("DOI, arXiv ID or exact title", key="lib_doi")
        if st.button("Fetch & add", key="lib_fetch") and ident:
            try:
                if st.session_state.demo_mode:
                    h = demo.get(ident)
                    text = h["text"]
                else:
                    h = connectors.resolve_identifier(ident, current_settings())
                    if h.get("doi") and not h.get("csl"):
                        try:
                            h["csl"] = C.fetch_csl(h["doi"])
                        except Exception:
                            pass
                    text = connectors.fetch_fulltext(h, current_settings())
                ok = ws.add_article(p["id"], h, fmap[target], text)
                st.success(f"Added: {h['title']}" if ok else "Already in this project.")
            except Exception as e:
                st.error(f"Could not fetch: {e}")
    with t3:
        ups = st.file_uploader("PDF or TXT (several allowed)", type=["pdf", "txt"], accept_multiple_files=True)
        if ups and st.button("Add uploaded files"):
            from authorshand.evidence import parse_report, read_pdf_pages
            from authorshand.pdf_reader import guess_title
            for f in ups:
                raw = f.read()
                pages = read_pdf_pages(raw) if f.name.lower().endswith(".pdf") else None
                text = "\n".join(pages) if pages else raw.decode("utf-8", "ignore")
                doi = connectors.clean_doi(text[:4000])
                paper = connectors.paper(id=f"upload:{f.name}", title=guess_title(text), doi=doi,
                                         source=f"Uploaded file ({f.name})")
                if pages:
                    paper.update(pages_text=pages, pages_count=len(pages), parse=parse_report(text, pages))
                if doi and not st.session_state.demo_mode:
                    try:
                        meta = connectors.resolve_identifier(doi, current_settings())
                        paper.update({k: v for k, v in meta.items() if v})
                    except Exception:
                        pass
                ws.add_article(p["id"], paper, fmap[target], text)
            st.success(f"Added {len(ups)} file(s).")
    with t4:
        st.caption("Exports from **Litmaps, ResearchRabbit, Zotero, Mendeley, EndNote, Scopus, Web of Science or "
                   "ResearchGate** — editors, volume, issue, pages and publisher are kept for full citations.")
        src = st.selectbox("Exported from", ["Litmaps", "ResearchRabbit", "Zotero", "Mendeley", "ResearchGate",
                                             "Scopus", "Web of Science", "Other"])
        f = st.file_uploader("BibTeX (.bib) or RIS (.ris) file", type=["bib", "ris", "txt"], key="imp")
        if f and st.button("Import"):
            recs = connectors.import_references(f.read().decode("utf-8", "ignore"), src)
            n = sum(bool(ws.add_article(p["id"], r, fmap[target], "")) for r in recs)
            st.success(f"Imported {n} new of {len(recs)} records from {src}.")
    with t5:
        user = ws.user(st.session_state.account)
        st.caption(f"ORCID linked: {user.get('orcid') or 'none — add it in Settings → Profile & identities'}")
        if user.get("orcid") and st.button("Import my ORCID works"):
            from authorshand.profile import ResearcherProfile
            prof = (ResearcherProfile.from_dict(demo.load_profile_dict()) if st.session_state.demo_mode
                    else ResearcherProfile.from_orcid(user["orcid"], current_settings(), user.get("researchgate", "")))
            n = sum(bool(ws.add_article(p["id"], w, fmap[target], "")) for w in prof.works)
            st.success(f"Imported {n} of your works.")


def page_library():
    hero("Library", "Arrange each project's articles in folders, then select papers for the Writing Studio.")
    p = need_project()
    if not p:
        return
    ws = workspace()
    folders = ws.folders(p["id"])
    left, right = st.columns([1, 3.2])
    with left:
        st.markdown("**Folders**")
        opts = [0] + [f["id"] for f in folders]
        labels = {0: f"📚 All articles ({sum(f['n'] for f in folders)})",
                  **{f["id"]: f"📁 {f['name']} ({f['n']})" for f in folders}}
        fid = st.radio("Folders", opts, format_func=lambda i: labels[i], label_visibility="collapsed")
        with st.popover("➕ New folder", width="stretch"):
            nf = st.text_input("Folder name", key="nf")
            if st.button("Create folder") and nf:
                ws.add_folder(p["id"], nf)
                st.rerun()
        if fid:
            with st.popover("✏️ Rename / delete", width="stretch"):
                rn = st.text_input("New name", key="rn")
                if st.button("Rename") and rn:
                    ws.rename_folder(fid, rn)
                    st.rerun()
                if st.button("Delete folder (articles move to Inbox)"):
                    ws.delete_folder(fid)
                    st.rerun()
    with right:
        with st.expander("➕ Add articles", expanded=not ws.articles(p["id"])):
            _add_articles_panel(p)
        arts = ws.articles(p["id"], fid or None)
        if not arts:
            st.info("No articles in this folder yet.")
            return
        fname = {f["id"]: f["name"] for f in folders}
        from authorshand.evidence import text_source
        from authorshand.writing import SOURCE_TYPES
        tagq = st.text_input("Filter by tag or word", key="libfilter", placeholder="e.g. attrition, method")
        if tagq:
            ql = tagq.lower()
            arts = [a for a in arts if ql in (a.get("tags") or "").lower() or ql in a["title"].lower()
                    or ql in (a.get("notes") or "").lower()]
        df = pd.DataFrame([{"select": a["id"] in st.session_state.selected_ids, "★": bool(a["starred"]),
                            "title": a["title"], "year": a["year"],
                            "type": SOURCE_TYPES.get(a["paper"].get("type") or "journal-article",
                                                     a["paper"].get("type") or "Journal article"),
                            "text used": a["paper"].get("text_source") or text_source(a["paper"], a["text"]),
                            "venue": a["venue"], "citations": a["citations"],
                            "folder": fname.get(a["folder_id"], ""), "status": a["status"],
                            "tags": a.get("tags") or "", "notes": a.get("notes") or "", "id": a["id"]} for a in arts])
        ed = st.data_editor(
            df, hide_index=True, width="stretch", key=f"lib_ed_{fid}",
            column_config={"select": st.column_config.CheckboxColumn("Select"),
                           "★": st.column_config.CheckboxColumn("★", help="Star important papers"),
                           "status": st.column_config.SelectboxColumn("Status", options=["to read", "reading", "read",
                                                                                          "cited", "excluded"]),
                           "tags": st.column_config.TextColumn("Tags", help="Comma-separated; exported as keywords"),
                           "notes": st.column_config.TextColumn("Notes", help="Your notes; exported to Zotero/RIS/BibTeX"),
                           "text used": st.column_config.TextColumn("Text used",
                                                                    help="Whether summaries come from the full text, "
                                                                         "the abstract only, or metadata only"),
                           "id": None},
            disabled=["title", "year", "type", "text used", "venue", "citations", "folder"])
        for _, row in ed.iterrows():
            a = next(x for x in arts if x["id"] == row["id"])
            if (bool(row["★"]) != bool(a["starred"]) or row["status"] != a["status"]
                    or (row["tags"] or "") != (a.get("tags") or "") or (row["notes"] or "") != (a.get("notes") or "")):
                ws.update_article(a["id"], starred=int(bool(row["★"])), status=row["status"],
                                  tags=row["tags"] or "", notes=row["notes"] or "")
        sel = [int(r["id"]) for _, r in ed.iterrows() if r["select"]]
        st.session_state.selected_ids = sel
        c1, c2, c3, c4 = st.columns([2, 1.4, 1.4, 1])
        c1.markdown(f"**{len(sel)} selected**")
        if c2.button("🧪 Open in Writing Studio", type="primary", disabled=not sel):
            st.switch_page(st.session_state.pages["studio"])
        with c3.popover("📁 Move to folder", disabled=not sel):
            dest = st.selectbox("Folder", [f["id"] for f in folders], format_func=lambda i: fname[i])
            if st.button("Move"):
                ws.move_articles(sel, dest)
                st.rerun()
        if c4.button("🗑 Delete", disabled=not sel):
            ws.delete_articles(sel)
            st.session_state.selected_ids = []
            st.rerun()


