"""Writing Studio (all paper sections, evidence-traceable) and Paper Reader."""
from __future__ import annotations

import html
import io
import json
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from authorshand import PaperIndex
from authorshand import citations as C
from authorshand.cheatsheet import cheatsheet_pdf
from authorshand.evidence import (is_full_text, LABELS as KLABELS, contrasting_sentences, disagreements, mark_edited, parse_report,
                                  support_label, text_source, trace_statements, BIB_FIELDS)
from authorshand.exporters import LABELS
from authorshand.summarizer import FIELDS
from authorshand.writing import CONTEXTS, DESIGNS, METHODS, SOURCE_TYPES, WritingStudio

from .common import (empty_project_help, PALETTE, account, chip, copy_box, current_settings, demo_banner, evidence_explorer, fig_style, hero,
                     integrity_note, legend, llm, need_project, prefs, source_chip, stat_row, summary_for,
                     tool_buttons, workspace)

REVIEW_GOALS_NO_MODEL = ("Scoping review", "Qualitative / thematic synthesis", "Exploratory reading",
                         "Teaching material / course design")


def _paper_with_notes(a: dict) -> dict:
    return dict(a["paper"], notes=a.get("notes") or "", tags=a.get("tags") or "",
                id=a["paper"].get("id") or str(a["id"]))


def _lexicon(p: dict) -> dict:
    lx = {"methods": {}, "designs": {}, "contexts": {}}
    for src in ((prefs().get("lexicon") or {}), (p.get("settings") or {}).get("lexicon") or {}):
        for cat in lx:
            for k, v in (src.get(cat) or {}).items():
                lx[cat].setdefault(k, [])
                lx[cat][k] += v
    return lx


def _studio_data(p, ids, topic, style):
    ws = workspace()
    arts = [ws.article(i) for i in ids]
    fp = json.dumps([[a["id"], a["paper"].get("extraction"), a.get("notes"), a.get("tags")] for a in arts]
                    + [_lexicon(p)], default=str, sort_keys=True)
    key = (tuple(sorted(ids)), topic, style, llm().label, hash(fp))
    if st.session_state.get("studio_key") != key:
        items = []
        with st.spinner(f"Reading and analysing {len(ids)} articles…"):
            for a in arts:
                items.append({"paper": _paper_with_notes(a), "text": a["text"], "summary": summary_for(a)})
            st.session_state.studio = WritingStudio(llm(), style, _lexicon(p)).build(items, topic)
            st.session_state.studio_key = key
            st.session_state.traces = {}
    return st.session_state.studio


def _trace(name: str, draft: str, A: list[dict], kind: str = "generated") -> list[dict]:
    tr = st.session_state.setdefault("traces", {})
    if name not in tr:
        tr[name] = trace_statements(draft, A, kind)
    return tr[name]


def _summary_statements(a: dict) -> list[dict]:
    gen = llm().available
    out = []
    for e in a["summary"].get("evidence") or []:
        strength = e.get("strength") or support_label(e.get("support", 0))
        out.append({"statement": e["claim"], "kind": "generated" if gen and e["support"] < 0.95 else "extracted",
                    "support": e["support"], "strength": strength, "paper": a["paper"].get("title", ""),
                    "cite": a["cite"], "section": e.get("section", ""), "page": e.get("page"),
                    "doi": a["paper"].get("doi", ""), "passage": e.get("evidence", ""),
                    "context": e.get("context") or e.get("evidence", ""), "text_source": a.get("text_source", ""),
                    "field": LABELS.get(e["field"], e["field"])})
    return out


def _cards(fields: dict, keys: list[str], kind: str | None = None):
    """Two columns of summary cards (ScholarPilot layout). The label is shown once above the cards, not per card."""
    left, right = st.columns(2)
    for i, k in enumerate(keys):
        v = fields.get(k) or []
        items = "".join(f"<li>{html.escape(str(x))}</li>" for x in (v if isinstance(v, list) else [v])) or \
            "<li><i>Not reported in this text.</i></li>"
        (left if i % 2 == 0 else right).markdown(
            f"<div class='card'><h4>{LABELS[k]}</h4><ul>{items}</ul></div>", unsafe_allow_html=True)


# ============================================================== WRITING STUDIO
def page_studio():
    hero("Writing Studio", "Select articles → material for every section of your paper — visual, copy-ready, and "
         "with every statement traceable to its source.")
    demo_banner()
    p = need_project()
    if not p:
        return
    ws = workspace()
    arts = ws.articles(p["id"])
    if not arts:
        empty_project_help(p, "e0tudio")
        return
    amap = {a["id"]: a["title"] for a in arts}
    default = [i for i in st.session_state.selected_ids if i in amap] or [a["id"] for a in arts[:5]]
    c1, c2, c3 = st.columns([3.2, 1.6, 1.2])
    ids = c1.multiselect("Articles to analyse", list(amap), default=default, format_func=lambda i: amap[i][:90])
    style = c2.selectbox("Citation style", list(C.STYLES), index=list(C.STYLES).index(p["citation_style"]),
                         format_func=lambda k: C.STYLES[k])
    visual = c3.toggle("Visual mode", value=True, help="Charts and diagrams on or off")
    topic = st.text_input("Your paper's topic (used in drafts)", value=p["description"] or p["topic_query"])
    if not ids:
        return
    if style != p["citation_style"]:
        ws.update_project(p["id"], citation_style=style)
    S = _studio_data(p, ids, topic, style)
    A = S["articles"]
    recs = [a["csl"] for a in A]
    goal = (p.get("settings") or {}).get("review_goal") or prefs().get("review_goal", "")
    show_all = True
    if goal in REVIEW_GOALS_NO_MODEL:
        show_all = st.toggle(f"Show model & hypothesis tabs (hidden for “{goal}”)", value=False)
    names = ["📝 Summaries", "📊 Comparison table", "🚪 Introduction", "📚 Literature review", "🕳 Research gap",
             "🧪 Methodology"] + (["🧩 Model development"] if show_all else []) + ["❓ Research questions"] + \
        (["🔬 Hypotheses"] if show_all else []) + ["🔭 Future study", "🔗 References"]
    tabs = dict(zip(names, st.tabs(names)))
    legend()
    abstract_only = [a["cite"] for a in A if not (a.get("text_source") or "").startswith("Full text")]
    if abstract_only:
        st.markdown(f"<div class='warnbox'>{len(abstract_only)} selected paper(s) are summarised from the "
                    f"<b>abstract or metadata only</b>: {', '.join(abstract_only)}. Add the PDF for full-text evidence."
                    "</div>", unsafe_allow_html=True)

    # ---------------------------------------------------------------- summaries
    with tabs["📝 Summaries"]:
        st.markdown("#### Overall summary of the selected articles " + chip("extracted", "Assembled from extracted findings"),
                    unsafe_allow_html=True)
        copy_box(S["overall"], "Overall summary")
        st.download_button("⬇ Cheatsheets for all selected papers (PDF, one page each)", cheatsheet_pdf(A, style),
                           "cheatsheets.pdf", "application/pdf")
        for a in A:
            f = a["summary"]["fields"]
            kind = "generated" if llm().available else "extracted"
            with st.expander(f"{a['cite']} — {a['paper']['title']}", expanded=len(A) == 1):
                st.markdown(source_chip(a.get("text_source", "")) + chip(kind) +
                            f"<span class='small'>{SOURCE_TYPES.get(a['source_type'], a['source_type'])}</span>",
                            unsafe_allow_html=True)
                st.markdown(f"<div class='tldr'><b>TL;DR</b> — {html.escape(f.get('tldr', ''))}</div>",
                            unsafe_allow_html=True)
                if visual:
                    stat_row([(a["sample"][0].split()[0] if a["sample"] else "—",
                               " ".join(a["sample"][0].split()[1:]) if a["sample"] else "sample"),
                              (a["designs"][0], "design"), (a["family"], "approach"),
                              (f"{a['summary']['faithfulness']:.2f}", "evidence support")])
                    st.write("")
                    _cards(f, [k for k in FIELDS if k != "tldr"], kind)
                copy_box(f"{a['paper']['title']} {a['cite']}\n\n" + a["exec"] + "\n\nKey findings:\n" +
                         "\n".join(f"- {x}" for x in f.get("key_findings") or []), "Article summary")
                evidence_explorer(_summary_statements(a), f"sum{a['cite']}{a['year']}",
                                  "Evidence for each summary point")
                st.download_button("⬇ Cheatsheet (PDF)", cheatsheet_pdf(a, style), "cheatsheet.pdf",
                                   "application/pdf", key=f"cs{a['cite']}{a['year']}")
        tool_buttons("Summaries", topic)

    # --------------------------------------------------------- comparison table
    with tabs["📊 Comparison table"]:
        st.markdown("Edit any cell to correct the extraction — your corrections are saved with the paper and "
                    "used everywhere (drafts, exports). " + chip("extracted") + chip("generated", "Your edits: shown as typed"),
                    unsafe_allow_html=True)
        df = pd.DataFrame([dict(a["table"], _id=ids[i]) for i, a in enumerate(A)])
        ed = st.data_editor(df, hide_index=True, width="stretch", key="cmp_ed", column_config={"_id": None},
                            disabled=["Study", "Text used"])
        if st.button("Save corrections", type="primary"):
            colmap = {"Sample": "table_sample", "Setting / context": "table_setting", "Data": "table_data",
                      "Method": "table_method", "Measures": "table_measures", "Key findings": "table_findings",
                      "Limitations": "table_limitations"}
            for i, row in ed.iterrows():
                orig = df.iloc[i]
                a = ws.article(int(row["_id"]))
                ex = dict(a["paper"].get("extraction") or {})
                changed = False
                for col, k in colmap.items():
                    if row[col] != orig[col]:
                        ex[k] = row[col]
                        changed = True
                if row["Source type"] != orig["Source type"]:
                    inv = {v: k for k, v in SOURCE_TYPES.items()}
                    a["paper"]["type"] = inv.get(row["Source type"], a["paper"].get("type"))
                    changed = True
                if changed:
                    ws.update_article(a["id"], data=dict(a["paper"], extraction=ex))
            st.session_state.studio_key = None
            st.success("Corrections saved.")
            st.rerun()
        buf = io.BytesIO()
        out = ed.drop(columns=["_id"])
        out.to_excel(buf, index=False)
        d1, d2 = st.columns(2)
        d1.download_button("⬇ Comparison table (Excel)", buf.getvalue(), "comparison_table.xlsx")
        d2.download_button("⬇ Comparison table (CSV)", out.to_csv(index=False), "comparison_table.csv")

    # ------------------------------------------------------------- introduction
    with tabs["🚪 Introduction"]:
        I = S["introduction"]
        if visual:
            g1, g2 = st.columns([1, 1.3])
            fig = go.Figure(go.Funnel(y=I["funnel"], x=[100, 75, 50, 30], textinfo="none",
                                      marker={"color": [PALETTE[2], PALETTE[0], PALETTE[1], PALETTE[3]]}))
            g1.plotly_chart(fig_style(fig, 300, False).update_layout(title="Introduction funnel"), width="stretch")
            with g2:
                st.markdown("**Evidence you can open with** " + chip("extracted"), unsafe_allow_html=True)
                for s_ in I["stats"][:4]:
                    st.markdown(f"<div class='card'><p>{html.escape(s_['text'])} <b>{s_['cite']}</b></p></div>",
                                unsafe_allow_html=True)
        integrity_note()
        copy_box(I["draft"], "Introduction draft")
        evidence_explorer(_trace("intro", I["draft"], A), "intro")
        tool_buttons("Introduction", topic)

    # --------------------------------------------------------- literature review
    with tabs["📚 Literature review"]:
        L = S["lit_review"]
        if visual:
            g1, g2 = st.columns([1.3, 1])
            tl = pd.DataFrame(L["timeline"])
            if len(tl):
                tl["approach"] = [next(a["family"] for a in A if a["cite"] == c) for c in tl["cite"]]
                fig = px.scatter(tl, x="year", y="approach", text="cite", color="approach", title="Timeline by approach")
                fig.update_traces(marker_size=16, textposition="top center")
                g1.plotly_chart(fig_style(fig, 320, False), width="stretch")
            th = pd.DataFrame([{"theme": t["theme"], "studies": t["n"]} for t in L["themes"]])
            g2.plotly_chart(fig_style(px.pie(th, names="theme", values="studies", hole=.55, title="Themes"), 320),
                            width="stretch")
        conflicts = disagreements(S["model"]["relations"])
        contrast = contrasting_sentences(A)
        if conflicts or contrast:
            with st.expander(f"⚖️ Where sources disagree or report contrasting evidence ({len(conflicts) + len(contrast)})",
                             expanded=bool(conflicts)):
                for c in conflicts:
                    st.markdown(f"<div class='warnbox'><b>Sources disagree on “{html.escape(c['outcome'])}”</b>: "
                                f"positive effect in {', '.join(c['positive'])}; negative in {', '.join(c['negative'])}."
                                "</div>", unsafe_allow_html=True)
                for c in contrast:
                    st.markdown(f"- {html.escape(c['sentence'])} **{c['cite']}** · {c['section']}"
                                + (f" · p. {c['page']}" if c["page"] else ""))
        integrity_note()
        copy_box(L["draft"], "Literature review draft")
        evidence_explorer(_trace("lr", L["draft"], A), "lr")
        tool_buttons("Literature review", topic)

    # --------------------------------------------------------------- research gap
    with tabs["🕳 Research gap"]:
        G = S["gaps"]
        st.markdown(f"<div class='warnbox'>{chip('candidate')} These gaps are <b>inferred from the {len(A)} selected "
                    "papers only</b> (their stated limitations and future-work notes). Treat them as candidates to "
                    "verify with a wider, documented search (see <b>Systematic review</b>) before claiming them in a "
                    "paper.</div>", unsafe_allow_html=True)
        if visual:
            g1, g2 = st.columns(2)
            types = sorted(G["types"], key=G["types"].get)
            if types:
                g1.plotly_chart(fig_style(px.bar(x=[G["types"][t] for t in types], y=types, orientation="h",
                                                 title="Candidate gap types across the selected studies",
                                                 labels={"x": "mentions", "y": ""},
                                                 color_discrete_sequence=[PALETTE[1]]), 320, False), width="stretch")
            cites = list(G["matrix"])
            all_t = list(G["types"])
            if cites:
                z = [[G["matrix"][c].get(t, 0) for t in all_t] for c in cites]
                fig = go.Figure(go.Heatmap(z=z, x=[t.replace(" gap", "") for t in all_t], y=cites,
                                           colorscale=[[0, "#F8FAFC"], [1, "#B45309"]], showscale=False))
                g2.plotly_chart(fig_style(fig, 320, False).update_layout(title="Who reports which limitation"),
                                width="stretch")
            cov = G["coverage"]
            if cov and next(iter(cov.values()), None):
                ms, cs_ = list(cov), list(next(iter(cov.values())))
                fig = go.Figure(go.Heatmap(z=[[cov[m][c] for c in cs_] for m in ms], x=cs_, y=ms, showscale=False,
                                           colorscale=[[0, "#FFFFFF"], [0.01, "#CCE7E4"], [1, "#0F766E"]],
                                           text=[[("" if cov[m][c] else "untested") for c in cs_] for m in ms],
                                           texttemplate="%{text}"))
                st.plotly_chart(fig_style(fig, 380, False).update_layout(
                    title="White-space map in the selected set: methods × contexts (empty = not combined here)"),
                    width="stretch")
            gi = pd.DataFrame(G["items"])
            if len(gi):
                gi["label"] = "Candidate — verify"
                gi["from"] = gi["source"].map({"limitations": "stated limitation", "future_work": "authors' future work"})
                st.dataframe(gi[["label", "type", "cite", "from", "text"]], hide_index=True, width="stretch")
        copy_box(G["draft"], "Candidate research-gap statement")
        evidence_explorer(_trace("gap", G["draft"], A, "candidate"), "gap")
        tool_buttons("Research gap", topic)

    # ---------------------------------------------------------------- methodology
    with tabs["🧪 Methodology"]:
        M = S["methodology"]
        if visual:
            g1, g2 = st.columns(2)
            mm = pd.DataFrame(sorted(M["methods"].items(), key=lambda x: x[1]), columns=["method", "studies"])
            g1.plotly_chart(fig_style(px.bar(mm, x="studies", y="method", orientation="h", title="Methods used",
                                             color_discrete_sequence=[PALETTE[0]]), 360, False), width="stretch")
            dd = pd.DataFrame(M["designs"].items(), columns=["design", "studies"])
            g2.plotly_chart(fig_style(px.pie(dd, names="design", values="studies", hole=.55, title="Research designs"),
                                      360), width="stretch")
        st.markdown("**Why each method was detected** — check the source text and correct it if needed")
        rows = []
        for a in A:
            for m in a["methods"]:
                src = a["method_sources"].get(m) or {}
                rows.append({"Study": a["cite"], "Detected method": m, "Matched term": src.get("term", "(your correction)"),
                             "Source text": src.get("sentence", "")})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        with st.expander("✏️ Correct the classification of a paper"):
            idx = st.selectbox("Paper", range(len(A)), format_func=lambda i: A[i]["cite"] + " " + A[i]["paper"]["title"][:60])
            a = A[idx]
            lx = _lexicon(need_project())
            all_m = list(dict.fromkeys(list(METHODS) + list(lx["methods"])))
            all_d = list(dict.fromkeys(list(DESIGNS) + list(lx["designs"])))
            all_c = list(dict.fromkeys(list(CONTEXTS) + list(lx["contexts"])))
            nm = st.multiselect("Methods", all_m, default=[m for m in a["methods"] if m in all_m])
            nd = st.multiselect("Designs", all_d, default=[d for d in a["designs"] if d in all_d])
            nc = st.multiselect("Contexts", all_c, default=[c for c in a["contexts"] if c in all_c])
            if st.button("Save classification", type="primary"):
                art = ws.article(ids[idx])
                ex = dict(art["paper"].get("extraction") or {})
                ex.update(methods=nm, designs=nd, contexts=nc)
                ws.update_article(art["id"], data=dict(art["paper"], extraction=ex))
                st.session_state.studio_key = None
                st.rerun()
        with st.expander("➕ Add field-specific terms (e.g. fsQCA, event study, grounded theory)"):
            c1, c2, c3 = st.columns([1, 1.2, 1.6])
            cat = c1.selectbox("Category", ["methods", "designs", "contexts"])
            name = c2.text_input("Label shown in the app", placeholder="e.g. Event study")
            terms = c3.text_input("Terms to look for (comma-separated)", placeholder="event study, abnormal returns")
            if st.button("Add term to this project") and name and terms:
                pr = need_project()
                sett = dict(pr.get("settings") or {})
                lx2 = sett.setdefault("lexicon", {"methods": {}, "designs": {}, "contexts": {}})
                lx2.setdefault(cat, {})[name] = [t.strip().lower() for t in terms.split(",") if t.strip()]
                ws.update_project(pr["id"], settings=sett)
                st.session_state.studio_key = None
                st.rerun()
            cur = _lexicon(need_project())
            st.caption("Your terms: " + "; ".join(f"{k} → {', '.join(v)}" for cat_ in cur.values() for k, v in cat_.items())
                       if any(cur.values()) else "Your terms: none yet")
        st.dataframe(pd.DataFrame(M["table"]), hide_index=True, width="stretch")
        st.markdown("**Methodology checklist**")
        cc = st.columns(3)
        for i, item in enumerate(M["checklist"]):
            cc[i % 3].checkbox(item, key=f"chk{i}")
        st.markdown(chip("generated", "Template + extracted counts — adapt to your study"), unsafe_allow_html=True)
        copy_box(M["draft"], "Methodology draft")
        tool_buttons("Methodology", topic)

    # ---------------------------------------------------------- model development
    if "🧩 Model development" in tabs:
        with tabs["🧩 Model development"]:
            Mo = S["model"]
            st.markdown(chip("generated", "Proposed model — built from relationships reported in the papers"),
                        unsafe_allow_html=True)
            for c in disagreements(Mo["relations"]):
                st.warning(f"Sources disagree on “{c['outcome']}”: positive in {', '.join(c['positive'])}, "
                           f"negative in {', '.join(c['negative'])}.")
            if visual and Mo["relations"]:
                st.markdown("**Conceptual model** <span class='small'>(green = positive, amber = negative, "
                            "dashed = moderator)</span>", unsafe_allow_html=True)
                st.graphviz_chart(Mo["dot"], width="stretch")
            st.dataframe(pd.DataFrame([{"Independent (X)": r["iv"], "Effect": r["sign"], "Dependent (Y)": r["dv"],
                                        "Source": r["cite"], "Evidence": r["evidence"]} for r in Mo["relations"]]),
                         hide_index=True, width="stretch")
            txt = ("Constructs: " + "; ".join(Mo["constructs"]) + "\n\nProposed relationships:\n" +
                   "\n".join(f"- {r['iv']} → {r['dv']} ({'+' if r['sign'] == '+' else '−'}) {r['cite']}"
                             for r in Mo["relations"])
                   + ("\n\nModerators:\n" + "\n".join(f"- {m['group']} {m['cite']}" for m in Mo["moderators"])
                      if Mo["moderators"] else ""))
            copy_box(txt, "Model specification")
            st.download_button("⬇ Model diagram (.dot — open in Graphviz / draw.io)", Mo["dot"], "model.dot")
            tool_buttons("Model development", topic)

    # --------------------------------------------------------- research questions
    with tabs["❓ Research questions"]:
        Q = S["questions"]
        for q in Q:
            st.markdown(f"<div class='card'><h4>{q['id']} · {html.escape(q['type'])}</h4>{chip('candidate')}"
                        f"<p><b>{html.escape(q['text'])}</b></p><p class='small'>Derived from: "
                        f"{html.escape(q['from_gap'])}</p></div>", unsafe_allow_html=True)
        copy_box("\n".join(f"{q['id']}: {q['text']}" for q in Q), "Research questions")
        tool_buttons("Research questions", Q[0]["text"] if Q else topic)

    # ---------------------------------------------------------------- hypotheses
    if "🔬 Hypotheses" in tabs:
        with tabs["🔬 Hypotheses"]:
            H = S["hypotheses"]
            st.markdown(chip("generated", "Proposed hypotheses — each backed by a reported finding"),
                        unsafe_allow_html=True)
            if visual and H:
                lines = ['digraph H { rankdir=LR; bgcolor="transparent";',
                         'node [shape=box, style="rounded,filled", fillcolor="#E6F2F1", color="#0F766E", fontname="Helvetica"];']
                for h in H:
                    if h["sign"] == "mod":
                        lines.append(f'"{h["moderator"]}" [shape=ellipse, fillcolor="#FDF1E3", color="#B45309"];')
                        lines.append(f'"{h["moderator"]}" -> "{h["dv"]}" [label="{h["id"]}", style=dashed, color="#B45309"];')
                    else:
                        col = "#0F766E" if h["sign"] == "+" else "#B45309"
                        lines.append(f'"{h["iv"]}" -> "{h["dv"]}" [label="{h["id"]} ({h["sign"]})", color="{col}", fontcolor="{col}"];')
                lines.append("}")
                st.graphviz_chart("\n".join(lines), width="stretch")
            st.dataframe(pd.DataFrame([{"ID": h["id"], "Hypothesis": h["text"], "Supporting study": h["support"],
                                        "Evidence": h["evidence"]} for h in H]), hide_index=True, width="stretch")
            copy_box("\n".join(f"{h['id']}: {h['text']} {h['support']}" for h in H), "Hypotheses")
            tool_buttons("Hypotheses", H[0]["text"] if H else topic)

    # -------------------------------------------------------------- future study
    with tabs["🔭 Future study"]:
        F = S["future"]
        st.markdown(chip("extracted", "Authors' own future-work statements"), unsafe_allow_html=True)
        if visual and F["grouped"]:
            fc = pd.DataFrame([{"type": t, "suggestions": len(v)} for t, v in F["grouped"].items()])
            st.plotly_chart(fig_style(px.bar(fc, x="suggestions", y="type", orientation="h",
                                             title="Future-research directions by type",
                                             color_discrete_sequence=[PALETTE[3]]), 280, False), width="stretch")
            for t, xs in F["grouped"].items():
                st.markdown(f"<div class='card'><h4>{html.escape(t)}</h4><ul>" +
                            "".join(f"<li>{html.escape(x['text'])} <b>{x['cite']}</b></li>" for x in xs) +
                            "</ul></div>", unsafe_allow_html=True)
        copy_box(F["draft"], "Future research section")
        evidence_explorer(_trace("future", F["draft"], A, "extracted"), "future")
        tool_buttons("Future study", topic)

    # ---------------------------------------------------------------- references
    with tabs["🔗 References"]:
        references_block(recs, style, key="studio")


def references_block(recs, style, key=""):
    refs = C.bibliography(recs, style)
    st.markdown(f"**Reference list — {C.STYLES[style]}** <span class='small'>(select the formatted list and copy: "
                "italics and bold are kept when pasted into Word / Google Docs)</span>", unsafe_allow_html=True)
    st.markdown("".join(f"<p class='ref'>{C.md_to_html(r)}</p>" for r in refs), unsafe_allow_html=True)
    copy_box("\n".join(C.md_to_plain(r) for r in refs), "Plain-text reference list")
    st.markdown("**In-text citations**")
    st.dataframe(pd.DataFrame([{"Work": r.get("title", "")[:80], "Parenthetical": C.in_text(r, style, i + 1),
                                "Narrative": C.narrative_cite(r)} for i, r in enumerate(recs)]),
                 hide_index=True, width="stretch")
    d1, d2, d3, d4 = st.columns(4)
    buf = io.BytesIO()
    C.to_docx(refs, "References", buf)
    d1.download_button("⬇ Word (.docx)", buf.getvalue(), "references.docx", key=f"dx{key}")
    d2.download_button("⬇ BibTeX (with your notes)", C.to_bibtex(recs), "references.bib", key=f"bb{key}")
    d3.download_button("⬇ RIS (with notes & tags)", C.to_ris(recs), "references.ris", key=f"rr{key}")
    d4.download_button("⬇ EndNote", C.to_endnote(recs), "references.enw", key=f"en{key}")
    st.caption("Citation fields come from the source shown in Paper Reader → Citation & record, where you can "
               "correct them. Always check a reference against the publisher's page before submission.")
    with st.expander("🌐 Any journal's style (10,000+ CSL styles, live via DOI)"):
        live = st.selectbox("Style", list(C.LIVE_STYLES), format_func=lambda k: C.LIVE_STYLES[k], key=f"ls{key}")
        custom = st.text_input("…or any CSL style ID from citationstyles.org (e.g. 'emerald-harvard')", key=f"cs{key}")
        if st.button("Format live", key=f"fl{key}"):
            if st.session_state.demo_mode:
                st.info("Live formatting needs Live mode and real DOIs (demo DOIs are fictional).")
            else:
                for r in recs:
                    if r.get("DOI"):
                        try:
                            st.markdown(f"<p class='ref'>{C.format_live(r['DOI'], custom or live)}</p>",
                                        unsafe_allow_html=True)
                        except Exception as e:
                            st.caption(f"{r['DOI']}: {e}")
    tool_buttons("References", "")


# ================================================================ PAPER READER
def _attach_fulltext(ws, a: dict, aid: int):
    """Abstract-only paper → attach the PDF (or fetch the open-access copy) so every summary field fills in."""
    from authorshand import connectors
    from authorshand.evidence import parse_report, read_pdf_pages
    with st.container(border=True):
        st.markdown("**Only the abstract is stored for this paper, so several boxes say “Not reported”.** "
                    "Add the full text and the summary, evidence (with page numbers), studio drafts and cheatsheet "
                    "fill in completely.")
        c1, c2 = st.columns([2, 1])
        up = c1.file_uploader("Attach the PDF of this paper", type=["pdf"], key=f"att{aid}")
        if up and c1.button("Use this PDF", type="primary", key=f"attb{aid}"):
            raw = up.read()
            pages = read_pdf_pages(raw)
            text = "\n".join(pages)
            if len(text.split()) < 200:
                st.warning("Very little text could be read — the PDF may be scanned. It was attached anyway; you "
                           "can correct the text in the 📄 Extracted text tab.")
            data = dict(a["paper"], pages_text=pages, pages_count=len(pages), parse=parse_report(text, pages),
                        text_source=f"Full text (PDF, {len(pages)} pages)")
            ws.update_article(aid, text=text, summary="", data=data)
            st.session_state.studio_key = None
            st.rerun()
        can_fetch = bool(a["paper"].get("doi") or a["paper"].get("oa_pdf")) and not st.session_state.demo_mode
        if c2.button("⬇ Fetch the open-access full text", disabled=not can_fetch, width="stretch", key=f"oa{aid}",
                     help=None if can_fetch else "Needs Live mode and a DOI or open-access link."):
            with st.spinner("Looking for a legal open-access copy (Unpaywall / OpenAlex)…"):
                text = connectors.fetch_fulltext(a["paper"], current_settings())
            if text and not text.startswith(a["paper"].get("title", "")[:30] + "\n\nAbstract:") and len(text.split()) > 300:
                ws.update_article(aid, text=text, summary="",
                                  data=dict(a["paper"], text_source="Full text (open-access download)"))
                st.session_state.studio_key = None
                st.rerun()
            else:
                st.info("No open-access copy was found. Attach the PDF you have (publisher site, ResearchGate, "
                        "your institution's library).")
        if a["paper"].get("doi"):
            c2.link_button("Open the paper (DOI) ↗", f"https://doi.org/{a['paper']['doi']}", width="stretch")


def page_reader():
    hero("Paper Reader", "One paper in depth: summary with evidence, extracted text check, chat, citation record, "
         "notes and cheatsheet.")
    demo_banner()
    p = need_project()
    if not p:
        return
    ws = workspace()
    arts = ws.articles(p["id"])
    if not arts:
        empty_project_help(p, "e1tudio")
        return
    amap = {a["id"]: a for a in arts}
    sel = st.session_state.selected_ids
    pre = sel[0] if sel and sel[0] in amap else arts[0]["id"]
    aid = st.selectbox("Article", list(amap), index=list(amap).index(pre), format_func=lambda i: amap[i]["title"][:110])
    a = amap[aid]
    s = summary_for(a)
    studio = WritingStudio(llm(), p["citation_style"], _lexicon(p))
    prof = studio.profile_article(_paper_with_notes(a), a["text"], s)
    rec = prof["csl"]
    src = a["paper"].get("text_source") or text_source(a["paper"], a["text"])
    t1, t2, t3, t4, t5, t6 = st.tabs(["📝 Summary", "🔎 Evidence", "📄 Extracted text", "💬 Chat",
                                      "🔗 Citation & record", "🗒 Notes & rating"])
    with t1:
        st.markdown(f"#### {html.escape(a['title'])}")
        st.markdown(source_chip(src) + chip("generated" if llm().available else "extracted"), unsafe_allow_html=True)
        if not is_full_text(src):
            _attach_fulltext(ws, a, aid)
        st.markdown(f"<div class='tldr'><b>TL;DR</b> — {html.escape(s['fields'].get('tldr', ''))}</div>",
                    unsafe_allow_html=True)
        stat_row([(f"{s['faithfulness']:.2f}", "evidence support"), (f"{s['compression']:.0%}", "compression"),
                  (len(s["sections_found"]), "sections found"), (prof["family"], "approach")])
        st.write("")
        _cards(s["fields"], [k for k in FIELDS if k != "tldr"], "generated" if llm().available else "extracted")
        copy_box(s.get("executive_summary", ""), "Executive summary")
        st.markdown("**Open this paper in other tools**")
        cols = st.columns(5)
        from authorshand import tools_hub as hub
        for i, tid in enumerate(["scispace", "connectedpapers", "googlescholar", "scite", "semanticscholar"]):
            t = hub.get(tid)
            cols[i].link_button(f"{t['name']} ↗", hub.launch_url(t, a["title"]), width="stretch")
    with t2:
        ev = pd.DataFrame(s["evidence"])
        if len(ev):
            st.markdown("**All evidence at a glance** — green = strongly supported, red = weak (check it)")
            cols = [c for c in ["field", "strength", "support", "section", "page", "claim", "evidence"] if c in ev]
            st.dataframe(ev[cols].style.background_gradient(subset=["support"], cmap="RdYlGn", vmin=0, vmax=1),
                         hide_index=True, width="stretch")
        evidence_explorer(_summary_statements(prof), f"rd{aid}", "Click a summary point to see its source passage")
    with t3:
        pages = a["paper"].get("pages_text") or []
        rep = a["paper"].get("parse") or parse_report(a["text"], pages)
        st.markdown(source_chip(src), unsafe_allow_html=True)
        stat_row([(rep["pages"] or "—", "PDF pages"), (len(rep["empty_pages"]), "pages without text"),
                  (len(rep["tables"]), "tables mentioned"), (len(rep["figures"]), "figures mentioned"),
                  (len(rep["sections"]), "sections recognised")])
        for issue in rep["issues"]:
            st.warning(issue)
        if not a["text"]:
            st.info("Only metadata/abstract is stored. Upload the PDF in the Library (📄 Upload PDF) for full-text "
                    "evidence with page numbers.")
        if pages:
            pg = st.number_input("Page", 1, len(pages), 1)
            st.text_area(f"Extracted text — page {pg}", pages[pg - 1], height=260, disabled=True)
        with st.expander("✏️ Correct the extracted text (e.g. paste text from a scanned page)"):
            new = st.text_area("Full text used for summaries and evidence", a["text"], height=300, key=f"txt{aid}")
            if st.button("Save text and re-summarise", type="primary"):
                ws.update_article(aid, text=new, summary="",
                                  data=dict(a["paper"], text_source=text_source(a["paper"], new) + " (edited by you)",
                                            pages_text=None if new != a["text"] else a["paper"].get("pages_text")))
                st.session_state.studio_key = None
                st.rerun()
    with t4:
        if not a["text"]:
            st.info("Only the abstract is stored for this article — add the PDF for full-text chat.")
        idx_key = f"idx_{aid}"
        if idx_key not in st.session_state:
            st.session_state[idx_key] = PaperIndex(llm(), use_embeddings=False).add_paper(
                a["text"] or f"{a['title']}\n\nAbstract: {a['paper'].get('abstract', '')}", a["title"])
        hist = st.session_state.setdefault(f"chat_{aid}", [])
        for role, msg in hist:
            st.chat_message(role).markdown(msg)
        q = st.chat_input("Ask this paper…")
        if q:
            ans = st.session_state[idx_key].ask(q)
            srcs = "; ".join(f"[S{h['rank']}] {h['section']}" for h in ans["sources"][:3])
            hist += [("user", q), ("assistant", ans["answer"] + f"\n\n*Sources: {srcs}*")]
            st.rerun()
    with t5:
        st.markdown("**Full reference in every built-in style**")
        st.markdown("".join(f"<p class='ref'><b>{name}</b><br>{C.md_to_html(C.format_reference(rec, k, 1))}</p>"
                            for k, name in C.STYLES.items()), unsafe_allow_html=True)
        st.markdown("**Where each field came from**")
        prov = a["paper"].get("provenance") or {}
        st.dataframe(pd.DataFrame([{"Field": f, "Value": ", ".join(a["paper"][f]) if isinstance(a["paper"].get(f), list)
                                    else str(a["paper"].get(f) or ""), "Source": (prov.get(f) or {}).get("source", "—"),
                                    "Date": (prov.get(f) or {}).get("at", "")} for f in BIB_FIELDS
                                   if a["paper"].get(f) not in (None, "", [])]), hide_index=True, width="stretch")
        with st.expander("✏️ Complete or correct the record (editors, volume, pages …)"):
            with st.form(f"bib{aid}"):
                pa = dict(a["paper"])
                types = ["journal-article", "book-chapter", "book", "proceedings-article", "report", "thesis",
                         "preprint", "dataset", "grey", "webpage"]
                c1, c2, c3 = st.columns(3)
                typ = c1.selectbox("Type", types, index=types.index(pa.get("type")) if pa.get("type") in types else 0,
                                   format_func=lambda t: SOURCE_TYPES.get(t, t))
                authors = c2.text_input("Authors (; separated)", "; ".join(pa.get("authors") or []))
                editors = c3.text_input("Editors (; separated)", "; ".join(pa.get("editors") or []))
                c1, c2, c3, c4 = st.columns(4)
                venue = c1.text_input("Journal / book / proceedings", pa.get("venue", ""))
                vol = c2.text_input("Volume", pa.get("volume", ""))
                iss = c3.text_input("Issue", pa.get("issue", ""))
                pages_ = c4.text_input("Pages / article no.", pa.get("pages", ""))
                c1, c2, c3, c4 = st.columns(4)
                pub = c1.text_input("Publisher / institution", pa.get("publisher", ""))
                place = c2.text_input("Place", pa.get("place", ""))
                edn = c3.text_input("Edition", pa.get("edition", ""))
                doi = c4.text_input("DOI", pa.get("doi", ""))
                yr = st.number_input("Year", 1800, 2100, int(pa.get("year") or 2024))
                if st.form_submit_button("Save record", type="primary"):
                    new = dict(pa, type=typ, authors=[x.strip() for x in authors.split(";") if x.strip()],
                               editors=[x.strip() for x in editors.split(";") if x.strip()], venue=venue, volume=vol,
                               issue=iss, pages=pages_, publisher=pub, place=place, edition=edn, doi=doi, year=int(yr))
                    new["provenance"] = mark_edited(pa, new)
                    new["csl_stale"] = True
                    ws.update_article(aid, data=new)
                    st.session_state.studio_key = None
                    st.rerun()
            if not st.session_state.demo_mode and a["paper"].get("doi") and st.button("Fill everything from the DOI"):
                try:
                    csl = C.fetch_csl(a["paper"]["doi"])
                    pa = dict(a["paper"], csl=csl, csl_stale=False)
                    pa["provenance"] = {f: {"source": "doi.org (CSL record)", "at": time.strftime("%Y-%m-%d")}
                                        for f in BIB_FIELDS}
                    ws.update_article(aid, data=pa)
                    st.rerun()
                except Exception as e:
                    st.error(f"DOI lookup failed: {e}")
        st.download_button("⬇ Cheatsheet (PDF)", cheatsheet_pdf(prof, p["citation_style"]), "cheatsheet.pdf",
                           "application/pdf", type="primary")
    with t6:
        with st.form(f"notes{aid}"):
            notes = st.text_area("Your notes (exported to Zotero / RIS / BibTeX)", a.get("notes") or "", height=140)
            tags = st.text_input("Tags (comma-separated)", a.get("tags") or "")
            status = st.selectbox("Reading status", ["to read", "reading", "read", "cited", "excluded"],
                                  index=["to read", "reading", "read", "cited", "excluded"].index(a["status"])
                                  if a["status"] in ["to read", "reading", "read", "cited", "excluded"] else 0)
            if st.form_submit_button("Save notes", type="primary"):
                ws.update_article(aid, notes=notes, tags=tags, status=status)
                st.success("Saved")
        st.markdown("**Rate this summary** — your ratings feed the human evaluation in the Evaluation page")
        with st.form(f"rate{aid}"):
            c1, c2 = st.columns(2)
            acc = c1.slider("Factual accuracy (1 = many errors, 5 = fully correct)", 1, 5, 4)
            use = c2.slider("Usefulness for my work (1–5)", 1, 5, 4)
            errs = st.text_area("Errors you found (optional)")
            if st.form_submit_button("Submit rating"):
                ws.db.execute("INSERT INTO ratings(account,article_key,accuracy,usefulness,errors,created) "
                              "VALUES (?,?,?,?,?,?)", (account(), a["key"], acc, use, errs, time.time()))
                ws.db.commit()
                st.success("Thank you — rating saved.")
