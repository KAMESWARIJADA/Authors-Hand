"""Citation Map · Journal Quality · Tool Hub · Research Profile · Agent · Evaluation · Install."""
from __future__ import annotations

import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from authorshand import PaperIndex, PaperSummarizer, ResearchAgent, ResearcherProfile, demo, evaluation, exporters
from datetime import datetime

from authorshand import citations as C
from authorshand import connectors, gscholar
from authorshand import publications as pubs
from authorshand import tools_hub as hub
from authorshand.citation_map import build_map
from authorshand.journal_quality import JournalChecker, load_list

from .common import (profile_is_demo, empty_project_help, APP, avatar_html, chip, save_prefs, demo_banner, PALETTE, copy_box, current_settings, fig_style, hero, llm, need_project, project, stat_row,
                     workspace)


# ================================================================ CITATION MAP
def _map_figure(m: dict):
    nodes = pd.DataFrame(m["nodes"])
    nodes["year"] = nodes["year"].fillna(nodes["year"].median())
    nodes["y"] = nodes["citations"].fillna(0).clip(lower=0) + 1
    pos = {r["id"]: (r["year"], r["y"]) for _, r in nodes.iterrows()}
    fig = go.Figure()
    for e in m["edges"]:
        if e["source"] in pos and e["target"] in pos:
            (x0, y0), (x1, y1) = pos[e["source"]], pos[e["target"]]
            fig.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color="#CBD5E1", width=1),
                                     hoverinfo="skip", showlegend=False))
    colours = {"seed": PALETTE[1], "reference": PALETTE[2], "citing": PALETTE[0], "related": PALETTE[7]}
    for kind, grp in nodes.groupby("kind"):
        fig.add_trace(go.Scatter(x=grp["year"], y=grp["y"], mode="markers", name=kind,
                                 marker=dict(size=[22 if kind == "seed" else 12] * len(grp), color=colours.get(kind),
                                             line=dict(color="white", width=1.5)),
                                 text=grp["title"], hovertemplate="%{text}<br>%{x} · %{y} citations<extra></extra>"))
    fig.update_yaxes(type="log", title="citations (log)")
    fig.update_xaxes(title="publication year")
    return fig, nodes


def page_map():
    hero("Citation Map", "A Litmaps-style map: your seed papers, what they cite and who cites them — by year and impact.")
    p = need_project()
    if not p:
        return
    arts = workspace().articles(p["id"])
    if not arts:
        empty_project_help(p, "e0tools")
        return
    amap = {a["id"]: a for a in arts}
    default = [i for i in st.session_state.selected_ids if i in amap] or list(amap)[:3]
    seeds = st.multiselect("Seed articles", list(amap), default=default, format_func=lambda i: amap[i]["title"][:90])
    n = st.slider("Connections per seed", 3, 15, 6)
    if not seeds:
        return
    with st.spinner("Building the map…"):
        m = build_map([amap[i]["paper"] for i in seeds], current_settings(), st.session_state.demo_mode, n)
    fig, nodes = _map_figure(m)
    st.plotly_chart(fig_style(fig, 520).update_layout(title=f"Citation map — {m['mode']}"), width="stretch")
    st.dataframe(nodes[["kind", "title", "year", "citations", "doi"]].sort_values(["kind", "year"]),
                 hide_index=True, width="stretch")
    recs = [C.from_paper({"title": r.title, "year": r.year, "doi": r.doi, "authors": [r.authors] if r.authors else []})
            for r in nodes.itertuples()]
    c1, c2 = st.columns(2)
    c1.download_button("⬇ Map as BibTeX (import into Litmaps / ResearchRabbit / Zotero)", C.to_bibtex(recs), "citation_map.bib")
    c2.link_button("Open Litmaps ↗", "https://app.litmaps.com")


# ============================================================= JOURNAL QUALITY
def page_quality():
    hero("Rapid Journal Quality Check", "Is this journal safe to cite or submit to? Transparent signals from open "
         "indexes, your Scopus/ABDC/UGC-CARE lists and red-flag heuristics — each with its source and date.")
    demo_banner()
    with st.expander("📑 Load your indexing lists (Scopus source list, WoS, ABDC, UGC-CARE … as CSV/XLSX)",
                     expanded=not st.session_state.quality_lists):
        c1, c2 = st.columns([2, 1])
        f = c1.file_uploader("List file", type=["csv", "xlsx", "xls"])
        nm = c2.selectbox("This list is", ["Scopus", "Web of Science", "ABDC", "UGC-CARE", "ABS/AJG", "Other"])
        if f and st.button("Load list"):
            st.session_state.quality_lists.append(load_list(f, nm))
        if st.session_state.demo_mode and st.button("Load the sample list (fictional)"):
            st.session_state.quality_lists.append(load_list(str(demo.DEMO_DIR / "sample_quality_list.csv"), "ABDC (sample)"))
        for L in st.session_state.quality_lists:
            st.caption(f"✔ {L['name']}: {L['size']} journals")
    ex = "Journal of Demo Analytics" if st.session_state.demo_mode else ""
    q = st.text_input("Journal name or ISSN", value=ex,
                      help="Demo mode includes two fictional journals: 'Journal of Demo Analytics' and "
                           "'Rapid Multidisciplinary'.")
    if q and st.button("Check journal", type="primary"):
        try:
            st.session_state.jq = JournalChecker(current_settings(), st.session_state.demo_mode,
                                                 st.session_state.quality_lists).check(q)
        except Exception as e:
            st.error(f"Check failed: {e}")
    r = st.session_state.get("jq")
    if r and r.get("found"):
        g1, g2 = st.columns([1, 1.6])
        colour = {"green": "#0F766E", "amber": "#B45309", "red": "#B91C1C"}[r["colour"]]
        fig = go.Figure(go.Indicator(mode="gauge+number", value=r["score"], number={"suffix": "/100"},
                                     gauge={"axis": {"range": [0, 100]}, "bar": {"color": colour},
                                            "steps": [{"range": [0, 45], "color": "#FDECEC"},
                                                      {"range": [45, 70], "color": "#FFF6EC"},
                                                      {"range": [70, 100], "color": "#E6F2F1"}]}))
        g1.plotly_chart(fig_style(fig, 260, False).update_layout(title=r["verdict"]), width="stretch")
        with g2:
            st.markdown(f"### {r['name']}")
            st.markdown(f"ISSN {', '.join(r['issn'])} · {r['publisher'] or 'publisher unknown'} · "
                        f"{'Open access' if r['is_oa'] else 'Subscription'}"
                        + (f" · APC US${r['apc_usd']}" if r.get("apc_usd") else ""))
            stat_row([(r["h_index"], "journal h-index"), (f"{r['two_year_citedness']:.2f}", "2-yr citedness"),
                      (r["works_count"], "articles"), (r["active_years"], "active years")])
            if r["demo"]:
                st.caption("Demo data — fictional journal.")
        st.markdown(f"<div class='infobox'>{html.escape(r.get('explanation', ''))} Checked {r.get('checked', '')}.</div>",
                    unsafe_allow_html=True)
        for fl in r["red_flags"]:
            st.error("🚩 " + fl)
        st.dataframe(pd.DataFrame(r["checks"]), hide_index=True, width="stretch")
        oby = pd.DataFrame(r["output_by_year"].items(), columns=["year", "articles"])
        st.plotly_chart(fig_style(px.bar(oby, x="year", y="articles", title="Articles published per year",
                                         color_discrete_sequence=[colour]), 260, False), width="stretch")
        cols = st.columns(len(r["links"]))
        for c, (k, v) in zip(cols, r["links"].items()):
            c.link_button(k + " ↗", v, width="stretch")
    elif r:
        st.warning(r.get("message"))
    p = project()
    if p:
        venues = sorted({a["venue"] for a in workspace().articles(p["id"]) if a["venue"]})
        if venues and st.button(f"Check all {len(venues)} journals in this project"):
            rows = []
            chk = JournalChecker(current_settings(), st.session_state.demo_mode, st.session_state.quality_lists)
            for v in venues:
                try:
                    x = chk.check(v)
                    rows.append({"journal": v, "score": x.get("score"), "verdict": x.get("verdict", x.get("message")),
                                 "red flags": len(x.get("red_flags", []))})
                except Exception as e:
                    rows.append({"journal": v, "score": None, "verdict": f"error: {e}", "red flags": None})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ===================================================================== TOOL HUB
def page_hub():
    hero("Tool Hub", "Attach the research tools you use — discovery, mapping, reading, writing, reference management, "
         "journal selection and quality checks — and switch them on per project.")
    p = need_project()
    if not p:
        return
    ws = workspace()
    enabled = set(p["addins"] or hub.DEFAULT_ADDINS)
    st.markdown("<span class='badge b-builtin'>Built in</span> works inside Author's Hand · "
                "<span class='badge b-api'>Live API</span> connected with your key · "
                "<span class='badge b-deeplink'>Opens pre-filled</span> launches the tool with your paper/query · "
                "<span class='badge b-exchange'>File exchange</span> send/receive BibTeX-RIS",
                unsafe_allow_html=True)
    q = st.text_input("Query or title used when launching tools", value=p["topic_query"])
    changed = False
    for cat in hub.CATEGORIES:
        tools = [t for t in hub.REGISTRY if t["category"] == cat]
        st.markdown(f"#### {cat}")
        cols = st.columns(3)
        for i, t in enumerate(tools):
            with cols[i % 3].container(border=True):
                on = st.toggle(f"**{t['name']}**", value=t["id"] in enabled, key=f"tg_{t['id']}")
                if on != (t["id"] in enabled):
                    (enabled.add if on else enabled.discard)(t["id"])
                    changed = True
                st.markdown(f"<span class='badge b-{t['connection']}'>{hub.label(t)}</span>"
                            f"<span class='small'>{t['pricing']} · {', '.join(t.get('stages', [])[:3])}</span>",
                            unsafe_allow_html=True)
                st.caption(t["what"])
                if t.get("url"):
                    st.link_button("Open ↗", hub.launch_url(t, q), width="stretch")
    if changed:
        ws.update_project(p["id"], addins=sorted(enabled))
        st.toast("Add-ins saved for this project")

    st.divider()
    st.markdown("### 🔄 Exchange this project with other tools")
    arts = ws.articles(p["id"])
    recs = [C.from_paper(a["paper"]) for a in arts]
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇ BibTeX (Litmaps, ResearchRabbit, Inciteful, Overleaf, JabRef)", C.to_bibtex(recs), "project.bib")
    c2.download_button("⬇ RIS (Mendeley, Zotero, EndNote, Litmaps)", C.to_ris(recs), "project.ris")
    c3.download_button("⬇ EndNote (.enw)", C.to_endnote(recs), "project.enw")
    st.markdown("### 📚 Zotero (live API)")
    user = ws.user(st.session_state.account)
    z1, z2, z3 = st.columns([1, 1.4, 1])
    zid = z1.text_input("Zotero user ID", value=user.get("zotero_user", ""))
    zkey = z2.text_input("Zotero API key (zotero.org → Settings → Security → Create new private key)", type="password")
    sel = [a for a in arts if a["id"] in st.session_state.selected_ids] or arts
    if z3.button(f"Send {len(sel)} article(s) to Zotero", disabled=not (zid and zkey)):
        try:
            res = hub.zotero_push(zid, zkey, [C.from_paper(a["paper"]) for a in sel])
            ws.update_user(st.session_state.account, zotero_user=zid)
            st.success(f"Zotero: {res['created']} created, {res['failed']} failed.")
        except Exception as e:
            st.error(f"Zotero API error: {e}")


# ============================================================ RESEARCH PROFILE
def _gs_card(gs: dict, url: str):
    m = gs.get("metrics") or {}
    since = next((v.get("since_year") for v in m.values() if v.get("since_year")), None)
    st.markdown(f"#### Google Scholar {'· ' + html.escape(gs.get('name', '')) if gs.get('name') else ''}")
    rows = [{"": lab, "All": (m.get(k) or {}).get("all"), f"Since {since}" if since else "Recent": (m.get(k) or {}).get("since")}
            for k, lab in (("citations", "Citations"), ("h_index", "h-index"), ("i10_index", "i10-index"))]
    c1, c2 = st.columns([1, 1.6])
    with c1:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"Source: {gs.get('source', '—')} · updated "
                   f"{datetime.fromtimestamp(gs['updated']).strftime('%d %b %Y %H:%M') if gs.get('updated') else '—'}")
        if url:
            st.link_button("Open my Google Scholar profile ↗", url)
    with c2:
        g = gs.get("graph") or {}
        if g:
            fig = px.bar(x=[str(k) for k in sorted(g)], y=[g[k] for k in sorted(g)], title="Citations per year (Google Scholar)",
                         labels={"x": "", "y": "citations"}, color_discrete_sequence=["#4285F4"], text_auto=True)
            fig.update_xaxes(type="category", categoryorder="category ascending")
            st.plotly_chart(fig_style(fig, 260, False), width="stretch")


def _scholar_link_ui(ws, user, gs, gs_url):
    """Google Scholar (SerpApi / manual / export) and ResearchGate export — the 'Link & import' tab."""
    st.markdown("<div class='infobox'>Google Scholar and ResearchGate have no official API and do not allow "
                "automated scraping. Use the honest routes below — the source and date are shown with your "
                "numbers.</div>", unsafe_allow_html=True)
    st.markdown("##### 🎓 Google Scholar")
    url = st.text_input("Your Google Scholar profile URL", value=gs_url,
                        placeholder="https://scholar.google.com/citations?user=XXXXXXXXXXXX")
    aid = gscholar.author_id(url)
    if url and not aid:
        st.warning("That does not look like a Scholar profile link (it should contain ‘citations?user=’).")
    r0, r1, r2, r3 = st.tabs(["Copy & paste my Scholar page (easiest)", "Automatic (SerpApi key)",
                              "Enter my numbers", "Import my Scholar articles"])
    with r0:
        st.markdown("1. Open **your Google Scholar profile** in your browser"
                    + (f" ([open it ↗]({url}))" if url.startswith("http") else "") + ".  \n"
                    "2. Click **SHOW MORE** at the bottom until all your articles are listed.  \n"
                    "3. Press **Ctrl + A** (select all), then **Ctrl + C** (copy).  \n"
                    "4. Click in the box below and press **Ctrl + V** (paste), then **Read my numbers**.")
        pasted = st.text_area("Paste your Google Scholar page here", height=160, key="gs_paste",
                              placeholder="Citations  …  h-index  …  i10-index  …")
        if st.button("Read my numbers", type="primary"):
            if pasted.strip():
                st.session_state.gs_parsed = gscholar.parse_pasted_profile(pasted)
            else:
                st.warning("Paste your Scholar page into the box first.")
        snap = st.session_state.get("gs_parsed")
        if snap:
            m = snap["metrics"]
            if not m:
                st.error("No ‘Citations / h-index / i10-index’ table was found in the pasted text — make sure you "
                         "copied the whole profile page (Ctrl + A).")
            else:
                sy = next((v.get("since_year") for v in m.values() if v.get("since_year")), None)
                st.markdown("**Check these numbers against your Scholar page, correct the yearly values if needed, "
                            "then press Save.**")
                st.dataframe(pd.DataFrame([{"": lab, "All": (m.get(k) or {}).get("all"),
                                            f"Since {sy}" if sy else "Since": (m.get(k) or {}).get("since")}
                                           for k, lab in (("citations", "Citations"), ("h_index", "h-index"),
                                                          ("i10_index", "i10-index"))]), hide_index=True)
                gdf = pd.DataFrame([{"year": y, "citations": v} for y, v in sorted(snap["graph"].items())]
                                   or [{"year": 2025, "citations": 0}])
                ged = st.data_editor(gdf, num_rows="dynamic", hide_index=True, key="gs_paste_graph")
                st.caption(f"Articles found in the pasted text: {len(snap['articles'])} (added to My publications "
                           "with their Scholar citation counts).")
                if st.button("Save my Google Scholar numbers", type="primary"):
                    snap = dict(snap, graph={int(r.year): int(r.citations) for r in ged.itertuples()
                                             if pd.notna(r.year) and pd.notna(r.citations)})
                    if not snap["articles"] and gs.get("articles"):
                        snap["articles"] = gs["articles"]
                    ws.update_user(user["email"], gscholar=snap,
                                   gscholar_url=gscholar.profile_url(aid) if aid else url)
                    st.session_state.pop("gs_parsed", None)
                    st.success("Saved — your Google Scholar numbers and graph are updated.")
                    st.rerun()
    with r1:
        st.caption("Create a free SerpApi account at serpapi.com → Dashboard → copy your API key. The key is "
                   "kept only for this session. Brings citations, h-index, i10, the yearly graph and your "
                   "article list with citation counts.")
        key = st.text_input("SerpApi key", type="password", value=st.session_state.get("serpapi_key", ""))
        if st.button("Fetch from Google Scholar", type="primary"):
          key = (key or "").strip()
          if not (aid and key):
            st.warning("Enter your Scholar profile URL and your SerpApi key first.")
          elif key.lower().startswith(("http", "www")) or "serpapi.com" in key.lower() or len(key) < 30:
            st.error("That is not an API key — it looks like the website address. On serpapi.com sign in → "
                     "**Dashboard** → **Api Key** (left menu) → copy the long code of letters and numbers "
                     "(64 characters) and paste it here.")
          else:
            try:
                snap = gscholar.fetch_serpapi(aid, key)
                st.session_state.serpapi_key = key
                ws.update_user(user["email"], gscholar=snap, gscholar_url=gscholar.profile_url(aid))
                st.success("Updated from Google Scholar.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not fetch from Google Scholar: {e}")
    with r2:
        st.caption("Open your Scholar profile and copy the ‘Cited by’ box and the yearly bar values.")
        with st.form("gsman"):
            m = (gs.get("metrics") or {})
            c1, c2, c3 = st.columns(3)
            sy = c1.number_input("“Since” year shown on Scholar", 2000, 2100,
                                 int((m.get("citations") or {}).get("since_year") or 2021))
            ca = c2.number_input("Citations — All", 0, 10**7, int((m.get("citations") or {}).get("all") or 0))
            cs = c3.number_input("Citations — Since", 0, 10**7, int((m.get("citations") or {}).get("since") or 0))
            c1, c2, c3, c4 = st.columns(4)
            ha = c1.number_input("h-index — All", 0, 10**4, int((m.get("h_index") or {}).get("all") or 0))
            hs = c2.number_input("h-index — Since", 0, 10**4, int((m.get("h_index") or {}).get("since") or 0))
            ia = c3.number_input("i10-index — All", 0, 10**5, int((m.get("i10_index") or {}).get("all") or 0))
            is_ = c4.number_input("i10-index — Since", 0, 10**5, int((m.get("i10_index") or {}).get("since") or 0))
            gdf = pd.DataFrame([{"year": y, "citations": v} for y, v in sorted((gs.get("graph") or {}).items())]
                               or [{"year": 2024, "citations": 0}, {"year": 2025, "citations": 0}])
            ged = st.data_editor(gdf, num_rows="dynamic", hide_index=True, key="gsgraph")
            if st.form_submit_button("Save my Scholar numbers", type="primary"):
                snap = gscholar.manual_snapshot(ca, cs, ha, hs, ia, is_, sy,
                                                {int(r.year): int(r.citations) for r in ged.itertuples() if r.year})
                ws.update_user(user["email"], gscholar=snap, gscholar_url=gscholar.profile_url(aid) if aid else url)
                st.rerun()
    with r3:
        st.caption("On Scholar: tick your articles → Export → BibTeX (or RefMan/RIS) → upload below under "
                   "“Add my papers from an export”.")
    st.markdown("##### 🔬 ResearchGate · Google Scholar · other exports → My publications")
    st.caption("ResearchGate: your profile → Research → select publications → Download citation → BibTeX or RIS. "
               "Google Scholar: tick articles → Export → BibTeX. Papers already in your list are not duplicated.")
    f = st.file_uploader("Add my papers from an export (.bib / .ris)", type=["bib", "ris", "txt"], key="pubimp")
    src = st.selectbox("This file came from", ["ResearchGate", "Google Scholar", "Scopus", "Web of Science", "Other"])
    if f and st.button("Add to My publications", type="primary"):
        recs = connectors.import_references(f.read().decode("utf-8", "ignore"), src)
        for r in recs:
            r["source"], r["sources"] = src, [src]
        old = (user.get("prefs") or {}).get("extra_works") or []
        merged = pubs.merge_extra(old, recs)
        save_prefs(extra_works=merged)
        st.success(f"Added {len(merged) - len(old)} new paper(s) from {src} ({len(recs)} in the file).")
        st.rerun()
    extra = (user.get("prefs") or {}).get("extra_works") or []
    if extra:
        st.caption(f"{len(extra)} paper(s) added from exports.")
        if st.button("Remove all papers added from exports"):
            save_prefs(extra_works=[])
            st.rerun()
    st.markdown("##### Unlink")
    if user.get("gscholar") and st.button("Unlink Google Scholar (delete stored numbers)"):
        ws.update_user(user["email"], gscholar={}, gscholar_url="")
        st.rerun()
    st.caption("ORCID and ResearchGate links are changed or removed in Settings & privacy → Profile & identities.")


def _coauthor_network(works, own_name):
    import networkx as nx
    g = nx.Graph()
    me = own_name or "Me"
    tab = pubs.coauthor_table(works, own_name).head(25)
    g.add_node(me)
    for r in tab.itertuples():
        g.add_edge(me, r[1], weight=r[2])
    keep = set(tab["Co-author"]) if len(tab) else set()
    for w in works:
        a = [x for x in (w.get("authors") or []) if x in keep]
        for i in range(len(a)):
            for j in range(i + 1, len(a)):
                g.add_edge(a[i], a[j], weight=1)
    pos = nx.spring_layout(g, seed=7, k=0.9)
    ex, ey = [], []
    for u, v in g.edges():
        ex += [pos[u][0], pos[v][0], None]
        ey += [pos[u][1], pos[v][1], None]
    size = {r[1]: r[2] for r in tab.itertuples()}
    fig = go.Figure([go.Scatter(x=ex, y=ey, mode="lines", line=dict(color="#CBD5E1", width=1), hoverinfo="skip"),
                     go.Scatter(x=[pos[n][0] for n in g.nodes()], y=[pos[n][1] for n in g.nodes()], mode="markers+text",
                                text=list(g.nodes()), textposition="top center", textfont=dict(size=10),
                                marker=dict(size=[28 if n == me else 10 + 4 * size.get(n, 1) for n in g.nodes()],
                                            color=[PALETTE[1] if n == me else PALETTE[0] for n in g.nodes()]),
                                hovertext=[f"{n}: {size.get(n, '')} joint paper(s)" if n != me else n for n in g.nodes()],
                                hoverinfo="text")])
    fig.update_layout(showlegend=False, title="Co-author network (size = joint papers)",
                      xaxis=dict(visible=False), yaxis=dict(visible=False))
    return fig



def _manual_add_ui(pr: dict, key: str = "man"):
    """Form to add a missing paper / conference paper / case by hand, plus edit/delete of hand-added entries."""
    extra = pr.get("extra_works") or []
    st.caption("For anything ORCID, Google Scholar or ResearchGate missed — conference papers, cases, chapters, "
               "working papers, reports, articles in magazines. Saved in your account and included in every list, "
               "chart, export and the citation map.")
    doi_in = st.text_input("Have a DOI? Paste it and press “Fill from DOI” (needs Live mode)", key=f"{key}_doi")
    if st.button("Fill from DOI", key=f"{key}_fill", disabled=not doi_in):
        try:
            rec = C.fetch_csl(doi_in.strip())
            st.session_state[f"{key}_pref"] = {
                "title": rec.get("title", ""), "venue": rec.get("container-title", ""),
                "authors": "; ".join(f"{a.get('given', '')} {a.get('family', '')}".strip() for a in rec.get("author", [])),
                "year": str(((rec.get("issued") or {}).get("date-parts") or [[""]])[0][0]),
                "volume": rec.get("volume", ""), "issue": rec.get("issue", ""), "pages": rec.get("page", ""),
                "publisher": rec.get("publisher", ""), "doi": doi_in.strip()}
            st.success("Filled from doi.org — check the fields below, then press Add.")
        except Exception as e:
            st.warning(f"Could not read that DOI ({e}). Type the details instead.")
    pf = st.session_state.get(f"{key}_pref") or {}
    with st.form(f"{key}_form", clear_on_submit=True):
        c1, c2 = st.columns([1, 3])
        kind = c1.selectbox("Type", list(pubs.MANUAL_TYPES))
        title = c2.text_input("Title *", pf.get("title", ""))
        c1, c2 = st.columns([3, 1])
        authors = c1.text_input("Authors in order (separate with ;) *", pf.get("authors", ""),
                                placeholder="Jada, K.; Machani, P.")
        year = c2.text_input("Year *", pf.get("year", ""))
        venue = st.text_input("Journal / conference / book / publisher series", pf.get("venue", ""),
                              placeholder="e.g. Proceedings of the IIM Indore Conference, Ivey Case Collection")
        c1, c2, c3, c4 = st.columns(4)
        vol = c1.text_input("Volume", pf.get("volume", ""))
        iss = c2.text_input("Issue", pf.get("issue", ""))
        pages = c3.text_input("Pages", pf.get("pages", ""))
        cites = c4.text_input("Citations (optional)", "")
        c1, c2, c3 = st.columns(3)
        publisher = c1.text_input("Publisher / organiser", pf.get("publisher", ""))
        doi = c2.text_input("DOI", pf.get("doi", ""))
        url = c3.text_input("Link (URL)", "")
        c1, c2 = st.columns(2)
        editors = c1.text_input("Editors (chapters / proceedings, separate with ;)", "")
        indexing = c2.text_input("Indexing / category (e.g. Scopus Q2, ABDC B, UGC-CARE)", "")
        if st.form_submit_button("➕ Add to My publications", type="primary"):
            if not title.strip() or not authors.strip() or not year.strip().isdigit():
                st.error("Title, authors and a 4-digit year are needed.")
            else:
                w = pubs.manual_work(kind, title, authors, year, venue, vol, iss, pages, publisher, doi, url, cites,
                                     indexing, "", editors)
                save_prefs(extra_works=extra + [w])
                st.session_state.pop(f"{key}_pref", None)
                st.success(f"Added “{title[:60]}”.")
                st.rerun()
    mine = [w for w in extra if (w.get("source") == "Added by you")]
    if mine:
        st.markdown(f"**Papers you added by hand ({len(mine)})** — edit cells directly, tick *Delete* to remove, "
                    "then press Save.")
        ed = pd.DataFrame([{"Delete": False, "Type": pubs.type_label(w), "Title": w["title"],
                            "Authors": "; ".join(w.get("authors") or []), "Year": w.get("year"),
                            "Venue": w.get("venue", ""), "DOI": w.get("doi", ""),
                            "Indexing": w.get("manual_indexing", ""), "id": w["id"]} for w in mine])
        out = st.data_editor(ed, hide_index=True, width="stretch", key=f"{key}_edit",
                             column_config={"id": None, "Type": st.column_config.SelectboxColumn(
                                 options=list(pubs.MANUAL_TYPES))})
        if st.button("Save changes to hand-added papers", key=f"{key}_save"):
            byid = {r.id: r for r in out.itertuples()}
            new = []
            for w in extra:
                r = byid.get(w.get("id"))
                if r is None:
                    new.append(w)
                    continue
                if r.Delete:
                    continue
                w = dict(w, title=r.Title, authors=[a.strip() for a in str(r.Authors).split(";") if a.strip()],
                         year=int(r.Year) if pd.notna(r.Year) else None, venue=r.Venue, doi=r.DOI,
                         manual_indexing=r.Indexing, type=pubs.MANUAL_TYPES.get(r.Type, w.get("type")))
                new.append(w)
            save_prefs(extra_works=new)
            st.success("Saved.")
            st.rerun()


def _yearwise_ui(df: pd.DataFrame):
    ys = pubs.year_summary(df)
    if not len(ys):
        st.info("No dated papers yet.")
        return
    per = df.dropna(subset=["Year"]).groupby("Year").size()
    stat_row([(int(per.max()), f"most papers in a year ({int(per.idxmax())})"),
              (round(float(per.mean()), 1), "papers per active year"),
              (int(per.index.min()), "first paper"), (int(per.index.max()), "latest paper"),
              (len(per), "active years")])
    g1, g2 = st.columns([1.6, 1])
    fig = px.bar(ys, x="Year", y="Papers", color="Type", title="Papers published per year (by type)",
                 color_discrete_sequence=PALETTE)
    fig.update_xaxes(type="category", categoryorder="category ascending")
    g1.plotly_chart(fig_style(fig, 360), width="stretch")
    cum = per.sort_index().cumsum()
    g2.plotly_chart(fig_style(px.area(x=[str(int(i)) for i in cum.index], y=cum.values, title="Cumulative papers",
                                      labels={"x": "", "y": "papers"}, color_discrete_sequence=[PALETTE[2]]), 360,
                              False), width="stretch")
    cit = df.assign(c=df["Citations (OpenAlex)"].fillna(0).combine(df["Citations (Scholar)"].fillna(0), max)) \
            .dropna(subset=["Year"]).groupby("Year")["c"].sum()
    if cit.sum():
        st.plotly_chart(fig_style(px.bar(x=[str(int(i)) for i in cit.index], y=cit.values,
                                         title="Citations received by the papers of each publication year",
                                         labels={"x": "publication year", "y": "citations"},
                                         color_discrete_sequence=[PALETTE[1]]), 260, False), width="stretch")
    st.markdown("**Year-wise list of papers**")
    for y in sorted(df["Year"].dropna().unique(), reverse=True):
        g = df[df["Year"] == y]
        with st.expander(f"{int(y)} — {len(g)} paper(s): " + ", ".join(f"{n} {t.lower()}"
                         for t, n in g["Type"].value_counts().items())):
            for r in g.itertuples():
                ci = r[df.columns.get_loc("Citations (Scholar)") + 1]
                co = r[df.columns.get_loc("Citations (OpenAlex)") + 1]
                c = max([x for x in (ci, co) if pd.notna(x)] or [0])
                st.markdown(f"- **{html.escape(r.Title)}** — *{html.escape(r[df.columns.get_loc('Journal / venue') + 1] or '—')}* "
                            f"· {r.Type} · {int(c)} citations  \n  <span style='color:#64748B'>with: "
                            f"{html.escape(r[df.columns.get_loc('Co-authors') + 1] or 'sole author')}</span>",
                            unsafe_allow_html=True)
    undated = df[df["Year"].isna()]
    if len(undated):
        st.caption(f"{len(undated)} paper(s) have no year — add it in the ➕ form or your ORCID record.")
    st.download_button("⬇ Year-wise list (CSV)",
                       df.sort_values("Year", ascending=False)[["Year", "Type", "Title", "Journal / venue",
                                                                "Co-authors", "Citations (OpenAlex)",
                                                                "Citations (Scholar)", "DOI"]].to_csv(index=False),
                       "papers_by_year.csv")


def _my_map_ui(works: list[dict]):
    cand = [w for w in works if w.get("doi") or st.session_state.demo_mode]
    if not cand:
        st.info("The citation map needs papers with a DOI (add DOIs in ORCID or the ➕ form).")
        return
    cand = sorted(cand, key=lambda w: -(w.get("citations") or w.get("scholar_citations") or 0))
    c1, c2 = st.columns([3, 1])
    titles = {i: w["title"] for i, w in enumerate(cand)}
    pick = c1.multiselect("Your papers on the map (most cited first)", list(titles), default=list(titles)[:6],
                          format_func=lambda i: titles[i][:90], key="mymap_pick")
    n = c2.slider("Links per paper", 3, 12, 6, key="mymap_n")
    if not pick:
        return
    k = (tuple(cand[i].get("doi") or cand[i]["title"] for i in pick), n, st.session_state.demo_mode)
    cache = st.session_state.get("my_map") or {}
    if k not in cache:
        with st.spinner("Building your citation map from OpenAlex…"):
            cache[k] = {"map": build_map([cand[i] for i in pick], current_settings(), st.session_state.demo_mode, n),
                        "at": datetime.now()}
        st.session_state.my_map = cache
    m, at = cache[k]["map"], cache[k]["at"]
    fig, nodes = _map_figure(m)
    st.plotly_chart(fig_style(fig, 520).update_layout(title=f"My citation map — {m['mode']}"), width="stretch")
    st.caption(f"Built {at.strftime('%d %b %Y %H:%M')} · press 🔄 Refresh all to rebuild with the newest citations. "
               "Orange = your papers, green = papers citing them, blue = papers they cite.")
    citing = nodes[nodes["kind"] == "citing"].sort_values("citations", ascending=False)
    if len(citing):
        st.markdown(f"**Who cites my papers ({len(citing)})**")
        st.dataframe(citing[["title", "authors", "year", "citations", "doi"]].rename(
            columns={"title": "Citing paper", "authors": "First author"}), hide_index=True, width="stretch")
    recs = [C.from_paper({"title": r.title, "year": r.year, "doi": r.doi, "authors": [r.authors] if r.authors else []})
            for r in nodes.itertuples()]
    st.download_button("⬇ Map as BibTeX (Litmaps / ResearchRabbit / Zotero)", C.to_bibtex(recs), "my_citation_map.bib")


def _orcid_vs_scholar_ui(prof, gs: dict):
    """Check whether the ORCID record and the Google Scholar profile list the same papers and numbers."""
    st.markdown("Compares your **ORCID record** (with OpenAlex citation counts) and your **Google Scholar** "
                "profile paper by paper, so you can see exactly what does not match and fix it at the source.")
    ow = [w for w in (prof.works if prof else []) if "ORCID" in (w.get("sources") or [w.get("source", "")])] \
        or (list(prof.works) if prof else [])
    ga = (gs or {}).get("articles") or []
    if not prof:
        st.info("Link your ORCID iD (Settings & privacy → Profile & identities) and press 🔄 Refresh all.")
    if not ga:
        st.info("Your Google Scholar paper list is not loaded yet. Go to **🔗 Link & import → Google Scholar** and "
                "use **Copy & paste my Scholar page** (or the SerpApi key) — then come back here.")
    if not (ow and ga):
        if gs.get("metrics") or prof:
            st.dataframe(pubs.compare_metrics(prof.metrics() if prof else None, gs, len(ow), len(ga)),
                         hide_index=True)
        return
    rec = pubs.reconcile(ow, ga)
    both = int((rec["Status"] == "✅ In both").sum())
    only_o = int((rec["Status"] == "🟠 Only on ORCID").sum())
    only_g = int((rec["Status"] == "🔵 Only on Google Scholar").sum())
    yd = int((rec["Note"] == "year differs").sum())
    stat_row([(both, "papers in both"), (only_g, "only on Google Scholar"), (only_o, "only on ORCID"),
              (yd, "year differs")])
    st.markdown("**Numbers side by side**")
    st.dataframe(pubs.compare_metrics(prof.metrics(), gs, len(ow), len(ga)), hide_index=True)
    st.markdown("**Paper by paper**")
    show = st.multiselect("Show", ["✅ In both", "🔵 Only on Google Scholar", "🟠 Only on ORCID"],
                          default=["🔵 Only on Google Scholar", "🟠 Only on ORCID"], key="rec_show")
    view = rec[rec["Status"].isin(show)] if show else rec
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"Year (ORCID)": st.column_config.NumberColumn(format="%d"),
                                "Year (Scholar)": st.column_config.NumberColumn(format="%d")})
    with st.expander("Why ORCID / OpenAlex and Google Scholar numbers differ"):
        st.markdown("- **Google Scholar counts more citations**: it also counts theses, preprints, slides, "
                    "non-indexed journals and duplicates; OpenAlex counts only indexed scholarly works.  \n"
                    "- **Papers missing on one side**: ORCID shows only what you (or a publisher via Crossref) "
                    "added; Scholar adds papers automatically, sometimes including other authors with a similar "
                    "name.  \n- **h-index and i10-index** follow from those citation counts, so they differ too.  \n"
                    "- Both are correct for their own database — journals and appraisal forms usually ask which "
                    "source you used, so the app labels every number with its source.")
    st.markdown("**Fix the differences at the source**")
    c1, c2 = st.columns(2)
    sg = [g for g in ga if any(_t == g.get("title") for _t in rec.loc[rec["Status"] == "🔵 Only on Google Scholar",
                                                                       "Title"])]
    if sg:
        c1.download_button(f"⬇ {len(sg)} Scholar-only papers as BibTeX (for ORCID)",
                           C.to_bibtex([C.from_paper(dict(g, type=g.get("type") or "journal-article")) for g in sg]),
                           "scholar_only_for_orcid.bib", type="primary")
        c1.caption("ORCID: orcid.org → Sign in → **Works** → **+ Add** → **Import BibTeX** → choose this file → "
                   "tick the papers that are yours → **Import**. Check each one is really your paper first.")
    oo = rec[rec["Status"] == "🟠 Only on ORCID"]
    if len(oo):
        c2.download_button(f"⬇ {len(oo)} ORCID-only papers (CSV)", oo.to_csv(index=False), "orcid_only.csv")
        c2.caption("Google Scholar: open your profile → **+** (Add) → **Add article manually** (or search the "
                   "title with **Add articles**) → save. Scholar may take a few days to show citations.")


def page_profile():
    hero("My Research Profile", "All your papers from ORCID, Google Scholar and ResearchGate in one list — type, "
         "field, indexing, citations, co-authors and ready citations — plus metrics, graphs and profile health.")
    if profile_is_demo():
        demo_banner()
    ws = workspace()
    user = ws.user(st.session_state.account)
    pdemo = profile_is_demo()          # fictional data only for the demo account
    oid = user.get("orcid") or (demo.DEMO_ORCID if pdemo else "")
    gs = user.get("gscholar") or (gscholar.DEMO_SNAPSHOT if pdemo else {})
    gs_url = user.get("gscholar_url", "")
    rg_url = user.get("researchgate", "")
    pr = user.get("prefs") or {}

    # ---------------- profile card with photo and linked identities
    def _chip(label, url=""):
        return (f"<a href='{html.escape(url, quote=True)}' target='_blank'>{html.escape(label)} ↗</a>" if url
                else f"<span>{html.escape(label)}</span>")
    chips = []
    if oid:
        chips.append(_chip(f"ORCID {oid}" + (" ✔" if user.get("orcid_verified") else ""), f"https://orcid.org/{oid}"))
    if gs_url or gs:
        chips.append(_chip("Google Scholar", gs_url))
    if rg_url:
        chips.append(_chip("ResearchGate", rg_url if rg_url.startswith("http") else ""))
    if user.get("linkedin"):
        li = user["linkedin"]
        chips.append(_chip("LinkedIn", li if li.startswith("http") else ""))
    if user.get("official_verified"):
        chips.append(_chip(f"✔ {user.get('official_email')}"))
    aff = gs.get("affiliation") or (pr.get("discipline") or "")
    interests = ", ".join((gs.get("interests") or [])[:5])
    st.markdown(f"<div class='pcard'>{avatar_html(user, 'ph')}<div><h3>{html.escape(user.get('name') or 'Researcher')}</h3>"
                f"<div class='aff'>{html.escape(aff)}{(' · ' + html.escape(interests)) if interests else ''}</div>"
                f"<div class='ids'>{''.join(chips) or '<span>No identities linked yet — Settings & privacy</span>'}"
                f"</div></div></div>", unsafe_allow_html=True)
    if not pr.get("photo"):
        st.caption("Add your photo in **Settings & privacy → Profile & identities → Profile photo**.")

    # ---------------- refresh bar
    c1, c2 = st.columns([3, 1])
    refresh = c2.button("🔄 Refresh all", type="primary", width="stretch",
                        help="Re-reads ORCID and OpenAlex, and Google Scholar too if a SerpApi key was entered "
                             "in this session.")
    if refresh:
        st.session_state.profile = None
        st.session_state.my_map = None
        aid = gscholar.author_id(gs_url)
        if aid and st.session_state.get("serpapi_key") and not pdemo:
            try:
                gs = gscholar.fetch_serpapi(aid, st.session_state.serpapi_key)
                ws.update_user(user["email"], gscholar=gs)
            except Exception as e:
                st.warning(f"Google Scholar not refreshed: {e}")
    if oid and st.session_state.get("profile") is None:
        with st.spinner("Reading ORCID, OpenAlex and ResearchGate…"):
            agent = ResearchAgent(llm=llm(), settings=current_settings(), demo_mode=pdemo)
            try:
                st.session_state.profile = agent.tool_profile(oid, rg_url, pr.get("openalex_id", ""))
                oa_id = (st.session_state.profile.openalex or {}).get("openalex_id", "")
                if oa_id and not pdemo and oa_id != pr.get("openalex_id"):
                    save_prefs(openalex_id=oa_id)        # next time: direct, no paper-by-paper search
                st.session_state.profile_refreshed = datetime.now()
            except Exception as e:
                st.error(f"Could not read ORCID / OpenAlex: {e} — check Live mode and the internet connection.")
    prof = st.session_state.get("profile") if oid else None
    when = st.session_state.get("profile_refreshed")
    gs_when = datetime.fromtimestamp(gs["updated"]).strftime("%d %b %Y %H:%M") if gs.get("updated") else "—"
    c1.markdown(f"**Sources** — ORCID: {'`' + oid + '`' if oid else '*not linked*'} · Google Scholar: "
                f"{'linked' if gs_url or gs else '*not linked*'} (updated {gs_when}) · ResearchGate: "
                f"{'linked' if rg_url else '*not linked*'} · LinkedIn: "
                f"{'linked' if user.get('linkedin') else '*not linked*'} · Official e-mail: "
                f"{'✔ ' + user['official_email'] + ' (verified)' if user.get('official_verified') else '*not verified*'}  \n"
                f"<span style='color:#64748B;font-size:.85rem'>ORCID / OpenAlex last read: "
                f"{when.strftime('%d %b %Y %H:%M') if when else '—'}</span>", unsafe_allow_html=True)
    if not oid:
        st.info("Add your ORCID iD in **Settings & privacy → Profile & identities** to load all your papers "
                "automatically. You can also add papers from a Google Scholar or ResearchGate export in the "
                "**Link & import** tab.")

    # ---------------- one list of all papers
    works = list(prof.works) if prof else []
    works = pubs.merge_scholar(works, gs.get("articles") or [])
    works = pubs.merge_extra(works, pr.get("extra_works") or [])
    own = (prof.name if prof else "") or user.get("name", "")
    # First time your papers load: put them into your (empty) current project so every page has content.
    cur = project()
    if (works and not pr.get("auto_imported") and cur and user["email"] != demo.DEMO_EMAIL
            and not workspace().articles(cur["id"])):
        from .common import add_works_to_project
        n = add_works_to_project(cur["id"], works)
        save_prefs(auto_imported=True)
        st.toast(f"Added your {n} papers to the project “{cur['name']}” (folder “My publications”).")
    theme_of = {}
    if prof and prof.works:
        for t in prof.themes():
            for ti in t.get("titles") or []:
                theme_of[ti] = t["theme"]
    styles = list(C.STYLES)
    t3, t1, t5, t2, t6, t7, t4 = st.tabs(["📈 Overview & graphs", "📚 My publications", "📅 Year-wise",
                                          "🤝 Co-authors", "🗺️ Citation map", "🔍 ORCID vs Scholar check",
                                          "🔗 Link & import"])
    df_all = None

    with t1:
        with st.expander("➕ Add a missing paper, conference paper, case or chapter manually"):
            _manual_add_ui(pr, "man1")
        if not works:
            st.info("No papers yet. Link ORCID (Settings), fetch Google Scholar, or import a ResearchGate / Scholar "
                    "export in **Link & import**.")
        else:
            style = st.selectbox("Citation style", styles, format_func=lambda k: C.STYLES[k],
                                 index=styles.index(pr.get("style", "apa")) if pr.get("style", "apa") in styles else 0,
                                 key="pubstyle")
            df = pubs.publication_table(works, own, st.session_state.get("quality_lists") or [], theme_of, style)
            df_all = df
            s = pubs.summary_counts(df)
            bt = s["by_type"]
            stat_row([(s["total"], "total papers"), (bt.get("Journal article", 0), "journal articles"),
                      (bt.get("Conference paper", 0), "conference papers"),
                      (bt.get("Book chapter", 0) + bt.get("Book", 0) + bt.get("Edited book", 0), "books & chapters"),
                      (s["total"] - bt.get("Journal article", 0) - bt.get("Conference paper", 0)
                       - bt.get("Book chapter", 0) - bt.get("Book", 0) - bt.get("Edited book", 0), "other"),
                      (f"{s['first_year']}–{s['latest_year']}" if s["first_year"] else "—", "years")])
            stat_row([(int(df["Citations (OpenAlex)"].fillna(0).sum()), "citations (OpenAlex)"),
                      (int(df["Citations (Scholar)"].fillna(0).sum()) if df["Citations (Scholar)"].notna().any()
                       else "—", "citations of listed papers (Scholar)"),
                      ((gs.get("metrics") or {}).get("h_index", {}).get("all", "—"), "h-index (Scholar)"),
                      (prof.metrics()["h_index"] if prof else "—", "h-index (OpenAlex)"),
                      (s["open_access"], "open access"), (s["indexed"], "in your indexing lists")])
            f1, f2, f3, f4 = st.columns([2, 1.4, 1.4, 1.2])
            q = f1.text_input("Search title, journal or co-author", key="pubq")
            types = f2.multiselect("Type", sorted(df["Type"].unique()), key="pubtype")
            srcs = sorted({x.strip() for v in df["Found in"] for x in v.split(",") if x.strip()})
            fsrc = f3.multiselect("Found in", srcs, key="pubsrc")
            sort = f4.selectbox("Sort by", ["Newest", "Most cited", "Title"], key="pubsort")
            v = df
            if q:
                ql = q.lower()
                v = v[v.apply(lambda r: ql in f"{r['Title']} {r['Journal / venue']} {r['Co-authors']}".lower(), axis=1)]
            if types:
                v = v[v["Type"].isin(types)]
            if fsrc:
                v = v[v["Found in"].apply(lambda x: any(sx in x for sx in fsrc))]
            if sort == "Most cited":
                v = v.assign(_c=v["Citations (OpenAlex)"].fillna(0) + v["Citations (Scholar)"].fillna(0)) \
                     .sort_values("_c", ascending=False).drop(columns="_c")
            elif sort == "Title":
                v = v.sort_values("Title")
            v = v.reset_index(drop=True)
            if not (st.session_state.get("quality_lists")):
                st.caption("ℹ️ The **Indexing** column fills in when you load your Scopus / WoS / ABDC / UGC-CARE "
                           "lists in **Journal Quality Check → Load your indexing lists**.")
            st.caption(f"Showing {len(v)} of {len(df)} papers · tick papers to see and copy their citations")
            ev = st.dataframe(v.drop(columns=["#", "Citation"]), hide_index=True, width="stretch",
                              on_select="rerun", selection_mode="multi-row", key="pubtable",
                              column_config={"DOI": st.column_config.TextColumn(width="small"),
                                             "Title": st.column_config.TextColumn(width="large"),
                                             "Year": st.column_config.NumberColumn(format="%d")})
            rows = ev.selection.rows if ev and ev.selection else []
            chosen = v.iloc[rows] if rows else v.iloc[0:0]
            if len(chosen):
                st.markdown(f"**Citations of the {len(chosen)} selected paper(s) — {C.STYLES[style]}**")
                copy_box("\n\n".join(chosen["Citation"]), "Citations")
                if len(chosen) == 1:
                    w = works[int(chosen.iloc[0]["#"])]
                    rec = C.from_paper(w)
                    with st.expander("This paper in every style + in-text citation"):
                        copy_box("\n\n".join(f"{C.STYLES[k]}:\n{C.md_to_plain(C.format_reference(rec, k))}"
                                             for k in styles), "All styles")
                        copy_box(f"{C.in_text(rec, style)}   ·   narrative: {C.narrative_cite(rec)}", "In-text")
                        if w.get("doi"):
                            st.link_button("Open the paper (DOI) ↗", f"https://doi.org/{w['doi']}")
                p = project()
                if p and st.button(f"➕ Add selected to project “{p['name']}”"):
                    n = sum(bool(ws.add_article(p["id"], works[int(i)], None, "")) for i in chosen["#"])
                    st.success(f"Added {n} paper(s) to the project library.")
            else:
                st.info("Tick one or more papers in the first column to get their citations.")
            recs = [C.from_paper(works[int(i)]) for i in v["#"]]
            with st.expander(f"All {len(v)} citations shown above — {C.STYLES[style]}"):
                copy_box("\n\n".join(v["Citation"]), "All citations")
            import io
            buf = io.BytesIO()
            v.drop(columns=["#"]).to_excel(buf, index=False, sheet_name="My publications")
            d1, d2, d3, d4 = st.columns(4)
            d1.download_button("⬇ Publication list (Excel)", buf.getvalue(), "my_publications.xlsx", type="primary")
            d2.download_button("⬇ BibTeX", C.to_bibtex(recs), "my_publications.bib")
            d3.download_button("⬇ RIS", C.to_ris(recs), "my_publications.ris")
            wb = io.BytesIO()
            C.to_docx([C.format_reference(r, style) for r in recs], "My publications", wb)
            d4.download_button("⬇ Word (formatted)", wb.getvalue(), "my_publications.docx")

    with t5:
        if df_all is None or not len(df_all):
            st.info("Year-wise charts appear once your papers are loaded.")
        else:
            _yearwise_ui(df_all)

    with t6:
        _my_map_ui(works)

    with t7:
        _orcid_vs_scholar_ui(prof, gs)

    with t2:
        ct = pubs.coauthor_table(works, own)
        if not len(ct):
            st.info("Co-authors appear once your papers are loaded.")
        else:
            stat_row([(len(ct), "co-authors"), (int((ct["Joint papers"] >= 2).sum()), "repeat collaborators"),
                      (ct.iloc[0]["Co-author"], "most frequent co-author"),
                      (round(float(ct["Joint papers"].mean()), 1), "papers per co-author")])
            g1, g2 = st.columns([1.1, 1])
            top = ct.head(15)
            g1.plotly_chart(fig_style(px.bar(top.iloc[::-1], x="Joint papers", y="Co-author", orientation="h",
                                             title="Most frequent co-authors",
                                             color_discrete_sequence=[PALETTE[0]]), 420, False), width="stretch")
            g2.plotly_chart(fig_style(_coauthor_network(works, own), 420, False), width="stretch")
            st.dataframe(ct, hide_index=True, width="stretch")
            st.download_button("⬇ Co-authors (CSV)", ct.to_csv(index=False), "coauthors.csv")

    with t3:
        if gs:
            _gs_card(gs, gs_url)
        if not prof:
            st.info("ORCID / OpenAlex metrics appear once your ORCID iD is linked.")
        else:
            m = prof.metrics()
            st.markdown("#### ORCID · OpenAlex · ResearchGate")
            stat_row([(m["works"], "works (ORCID ∪ OpenAlex ∪ RG)"), (m["citations"], "citations (OpenAlex)"),
                      (m["h_index"], "h-index (OpenAlex)"), (m["i10_index"], "i10-index"),
                      (f"{m['open_access_share']:.0%}", "open access")])
            st.caption("Citation counts differ between Google Scholar and OpenAlex because they index different "
                       "sources; both are shown with their source.")
            for wmsg in prof.warnings:
                st.warning(wmsg)
            if prof.notes:
                with st.expander("ℹ️ How your OpenAlex citations were found"):
                    for n in prof.notes:
                        st.markdown(n)
                    st.markdown("This is not an error. To let OpenAlex link it to your ORCID iD: open "
                                "**openalex.org** → search your name → open your author page → **Request "
                                "changes** (or e-mail OpenAlex support) and give your ORCID iD.")
            g1, g2 = st.columns(2)
            oby = prof.output_by_year()
            if oby:
                g1.plotly_chart(fig_style(px.bar(x=[str(k) for k in oby], y=list(oby.values()),
                                                 title="Publications per year", labels={"x": "", "y": "works"},
                                                 color_discrete_sequence=[PALETTE[0]]).update_xaxes(type="category", categoryorder="category ascending"),
                                          280, False), width="stretch")
            else:
                g1.info("No publications found for this ORCID iD yet (check Live mode and the iD).")
            cby = prof.citations_by_year()
            gsg = gs.get("graph") or {}
            if cby or gsg:
                fig = go.Figure()
                if cby:
                    fig.add_trace(go.Scatter(x=[str(k) for k in cby], y=list(cby.values()), mode="lines+markers",
                                             name="OpenAlex", line=dict(color=PALETTE[1])))
                if gsg:
                    fig.add_trace(go.Bar(x=[str(k) for k in sorted(gsg)], y=[gsg[k] for k in sorted(gsg)],
                                         name="Google Scholar", marker_color="#93B5F5", opacity=.7))
                g2.plotly_chart(fig_style(fig.update_layout(title="Citations per year — OpenAlex vs Google Scholar")
                                          .update_xaxes(type="category", categoryorder="category ascending"), 280), width="stretch")
            g1, g2 = st.columns([1.3, 1])
            th = pd.DataFrame(prof.themes())
            if len(th):
                g1.plotly_chart(fig_style(px.bar(th, x="works", y="theme", color="momentum", orientation="h",
                                                 title="Research themes & momentum",
                                                 color_discrete_map={"rising": PALETTE[0], "steady": PALETTE[2],
                                                                     "fading": "#94A3B8"}), 300), width="stretch")
            h = prof.health_audit()
            with g2:
                st.markdown(f"**Profile health: {h['score']}/100**")
                st.progress(h["score"] / 100)
                for c in h["checks"]:
                    st.markdown(f"{'✅' if c['passed'] else '⚠️'} {c['check']}")
                if not gs_url:
                    st.markdown("⚠️ Google Scholar profile linked")
                if h["fixes"]:
                    with st.expander("How to fix (step by step)"):
                        for fx in h["fixes"]:
                            st.markdown(f"- {fx}")
            st.markdown("**Next-paper ideas from theme pairs you have not combined yet** " + chip("candidate"),
                        unsafe_allow_html=True)
            for idea in prof.next_paper_ideas(llm()):
                st.markdown(f"- {idea}")
            v1, v2 = st.columns(2)
            ven = prof.venues(8)
            if ven:
                vd = pd.DataFrame(ven, columns=["venue", "papers"]).iloc[::-1]
                v1.plotly_chart(fig_style(px.bar(vd, x="papers", y="venue", orientation="h", title="Top venues",
                                                 color_discrete_sequence=[PALETTE[1]]), 320, False), width="stretch")
            if works:
                v2.plotly_chart(fig_style(_coauthor_network(works, own), 320, False), width="stretch")
            st.download_button("⬇ Research Passport (Markdown)", exporters.research_passport(prof),
                               "research_passport.md")

    with t4:
        _scholar_link_ui(ws, user, gs, gs_url)


# ======================================================================= AGENT
def page_agent():
    hero("Research Agent", "Give a goal in plain English — the agent plans, uses tools, checks its own output and "
         "shows every step.")
    examples = ["Summarise the paper on generative AI copilots in banking",
                "Literature review on explainable machine learning in HR and finance with 3 papers",
                "Which journal should I target for a manuscript on AI over-reliance in credit decisions?",
                "Analyse my research profile"]
    goal = st.text_input("Your research goal", value=st.selectbox("Examples", examples))
    if st.button("▶ Run agent", type="primary"):
        agent = ResearchAgent(llm=llm(), settings=current_settings(), profile=st.session_state.get("profile"),
                              demo_mode=st.session_state.demo_mode)
        with st.spinner("Agent working…"):
            res = agent.run(goal)
        st.markdown(f"**Intent:** `{res.intent}` · {res.seconds} s")
        c1, c2 = st.columns([1, 2])
        c1.markdown("**Plan**\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(res.plan, 1)))
        c2.dataframe(pd.DataFrame([{"#": s.n, "thought": s.thought, "tool": s.tool, "result": s.output, "sec": s.seconds}
                                   for s in res.trace]), hide_index=True, width="stretch")
        out = res.output
        if out.get("error"):
            st.error(out["error"])
        elif res.intent == "summarize":
            st.markdown(f"<div class='tldr'><b>TL;DR</b> — {out['summary']['fields']['tldr']}</div>", unsafe_allow_html=True)
            copy_box(exporters.summary_markdown(out["summary"]), "Summary (Markdown)")
        elif res.intent == "review":
            st.dataframe(out["review"]["matrix"], hide_index=True, width="stretch")
            copy_box(out["review"]["narrative"], "Review")
        elif res.intent == "venue":
            st.dataframe(pd.DataFrame(out["venues"]), hide_index=True, width="stretch")
        elif res.intent == "profile":
            st.session_state.profile = out["profile"]
            st.success("Profile built — open My Research Profile.")
        elif res.intent == "question":
            st.markdown(out["answer"])


# ================================================================== EVALUATION
def page_eval():
    hero("Evaluation", "How good are the summaries? A synthetic benchmark, your own real papers, and people's ratings.")
    t1, t2, t3 = st.tabs(["Your real papers", "Human ratings", "Synthetic demo benchmark"])
    with t1:
        st.markdown("Uses the standard *abstract-as-reference* protocol on full-text papers in the current project: "
                    "the abstract is hidden, the body is summarised, and the result is compared with the authors' "
                    "abstract and with the LEAD-3 baseline. Failure cases are listed, not just averages.")
        p = project()
        arts = [a for a in workspace().articles(p["id"])] if p else []
        full = [a for a in arts if len((a["text"] or "").split()) > 400]
        st.caption(f"{len(full)} of {len(arts)} articles in this project have full text.")
        if st.button("Evaluate on my full-text papers", type="primary", disabled=not full):
            with st.spinner("Evaluating…"):
                r = evaluation.evaluate_own_papers(PaperSummarizer(llm()), [{"title": a["title"], "text": a["text"]}
                                                                            for a in full])
            if r["n"]:
                sm = r["summary"]
                stat_row([(r["n"], "papers evaluated"), (f"{sm.get('rouge1', 0):.3f}", "ROUGE-1"),
                          (f"{sm.get('lead3_rouge1', 0):.3f}", "LEAD-3 ROUGE-1"),
                          (f"{sm.get('beats_lead3', 0):.0%}", "papers beating LEAD-3"),
                          (f"{sm.get('weak_claims', 0):.1f}", "weak claims / paper")])
                st.dataframe(r["table"], hide_index=True, width="stretch")
            st.markdown("**Failure cases**")
            st.dataframe(r["failures"], hide_index=True, width="stretch") if len(r["failures"]) else st.caption("None found.")
            if st.session_state.demo_mode:
                st.caption("Demo project: these are synthetic papers, so treat the numbers as a smoke test only.")
    with t2:
        rs = evaluation.rating_summary(workspace())
        if rs["n"]:
            stat_row([(rs["n"], "ratings"), (rs["accuracy"], "mean accuracy (1–5)"), (rs["usefulness"], "mean usefulness (1–5)"),
                      (rs["with_errors"], "ratings reporting errors")])
            rows = workspace().db.execute("SELECT article_key, accuracy, usefulness, errors, created FROM ratings "
                                          "ORDER BY created DESC").fetchall()
            st.dataframe(pd.DataFrame([dict(r) for r in rows]), hide_index=True, width="stretch")
        else:
            st.info("No ratings yet. Ask colleagues to open Paper Reader → Notes & rating and score summaries.")
    with t3:
        st.markdown("<div class='warnbox'><b>Limitation:</b> this benchmark uses 5 <b>synthetic</b> papers written for "
                    "the project with hand-written reference summaries and 10 questions. It is a smoke test, not "
                    "evidence of real-world accuracy.</div>", unsafe_allow_html=True)
        if st.button("Run synthetic benchmark"):
            c = demo.load_corpus()
            summ = PaperSummarizer(llm())
            with st.spinner("Evaluating…"):
                df = evaluation.evaluate_summaries(summ, c["papers"])
                base = evaluation.evaluate_baseline_lead3(c["papers"])
                idx = PaperIndex(llm(), use_embeddings=False)
                for p_ in c["papers"]:
                    idx.add_paper(p_["text"], p_["title"])
                ret = evaluation.evaluate_retrieval(idx, c["qa"], k=3)
                probe = evaluation.hallucination_probe(summ, c["papers"][1]["text"], c["papers"][1]["title"],
                                                       "The copilot doubled revenue in European branches.")
            m, b = df.iloc[-1], base.iloc[-1]
            stat_row([(f"{m.rouge1:.3f}", f"ROUGE-1 (LEAD-3 {b.rouge1:.3f})"), (f"{m.rougeL:.3f}", f"ROUGE-L (LEAD-3 {b.rougeL:.3f})"),
                      (f"{m.field_coverage:.0%}", "field coverage"), (f"{ret['hit@3']:.0%}", "retrieval Hit@3"),
                      (f"{ret['answer_accuracy']:.0%}", "QA accuracy")])
            st.dataframe(df, hide_index=True, width="stretch")
            st.markdown("**Questions answered wrongly (failure cases)**")
            st.dataframe(ret["details"][~ret["details"]["answer_correct"]], hide_index=True, width="stretch")
            st.markdown(f"**Hallucination probe:** invented claim support {probe['injected_support']:.2f} vs "
                        f"{probe['genuine_mean_support']:.2f} → {'flagged ✔' if probe['flagged'] else 'missed ✖'}")


# ===================================================================== INSTALL
def page_install():
    hero("Install on phone & desktop", f"Use {APP} like any app — Windows desktop, Android (Play Store), iPhone.")
    st.markdown("""
**Windows desktop (ready now).** Download `AuthorsHand-Windows.zip` → right-click → **Extract All** → double-click
**AuthorsHand.exe**. First start installs a private Python (2–6 min); afterwards it starts in seconds from the
Desktop / Start-menu shortcut.

**Phone — why hosting comes first.** Phones cannot run this Python engine, so the mobile app is a small Android
shell that opens your *hosted* Author's Hand. Steps:
1. **Host it online (once).** Streamlit Community Cloud (free; data resets when the app restarts — fine for
   demos) or a Docker host with a persistent disk such as Render (≈ US$7/month) for real multi-user accounts.
2. **Quick install, no store:** open the hosted URL on the phone → browser menu → **Add to Home screen**.
3. **Play Store:** follow `mobile/PLAY_STORE_GUIDE.md` — Android Studio builds the signed `.aab` from the
   included Capacitor project → Google Play Console (US$25 one-time) → closed test with 12 testers for 14 days
   (rule for new personal accounts) → production.
4. **Sign-in on the hosted app:** add the Google and ORCID client IDs in Settings → Sign-in providers (or the host's
   secrets), with the redirect URL `https://YOUR-APP/oauth2callback`.

**Background refresh.** Schedule `python -m authorshand.refresh you@uni.edu` (Windows Task Scheduler / cron).
""")


