"""Shared state, styling, sidebar and helpers for the Author's Hand app."""
from __future__ import annotations

import html
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from authorshand import LLM, PaperSummarizer, Settings, demo
from authorshand import tools_hub as hub
from authorshand.citations import STYLES
from authorshand.evidence import LABELS, is_full_text
from authorshand.store import Workspace

APP = "Author's Hand"
TAGLINE = "Your AI research companion — from papers to your own manuscript"
PALETTE = ["#0F766E", "#B45309", "#1E3A8A", "#6D28D9", "#0E7490", "#BE185D", "#4D7C0F", "#64748B"]
LOGO_SVG = ("<svg viewBox='0 0 64 64' width='{s}' height='{s}' xmlns='http://www.w3.org/2000/svg' aria-hidden='true'>"
            "<circle cx='32' cy='32' r='31' fill='#0B1F33'/><circle cx='32' cy='32' r='26' fill='#0F766E'/>"
            "<path d='M20 44 L38 18 L46 24 L28 50 L19 52 Z' fill='#F3C48C'/><path d='M38 18 L46 24 L49 20 L41 14 Z' "
            "fill='#FFFFFF'/><path d='M19 52 L20 44 L28 50 Z' fill='#0B1F33'/></svg>")

CSS = """
<style>
:root { --ink:#13233a; --accent:#0f766e; --accent2:#b45309; --muted:#5b6b7f; --card:#f7f9fb; --line:#e3e8ee;
        --fs: 1; }
html { font-size: calc(16px * var(--fs)); }
.block-container { padding-top: 1.2rem; max-width: 1320px; }
h1, h2, h3 { color: var(--ink); letter-spacing: -0.01em; }
.hero { background: linear-gradient(120deg,#0b1f33 0%,#0f3d4a 60%,#0f766e 100%); color:#fff;
        padding: 16px 22px; border-radius: 14px; margin-bottom: 12px; }
.hero h1 { color:#fff; margin:0; font-size: 1.55rem; }
.hero p { color:#d6e6ea; margin:.25rem 0 0 0; font-size: .95rem; }
.pill { display:inline-block; padding:0; font-size:.78rem; margin:8px 16px 0 0; color:#e9f5f3; cursor:default; }
.pill b { color:#9ee6da; font-weight:600; }
.hero-hint { display:block; font-size:.72rem; color:#a9c7cc; margin-top:4px; }
.card { background: var(--card); border:1px solid var(--line); border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; }
.card h4 { margin: 0 0 6px 0; font-size: .78rem; text-transform: uppercase; letter-spacing:.06em; color: var(--accent); }
.card p, .card li { margin: 0 0 4px 0; color: var(--ink); font-size: .93rem; line-height: 1.45; }
.stat { background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px 14px; }
.stat b { font-size:1.6rem; color: var(--accent); display:block; line-height:1.1 }
.stat span { color: var(--muted); font-size:.8rem }
.tldr { border-left: 5px solid var(--accent2); background:#fff8ef; padding: 10px 14px; border-radius: 8px;
        font-size: 1.0rem; color: var(--ink); margin: 6px 0 12px 0; }
.badge { display:inline-block; padding:1px 8px; border-radius:999px; font-size:.72rem; font-weight:600; margin-right:4px }
.b-builtin{background:#E6F2F1;color:#0F766E}.b-api{background:#EDE9FE;color:#6D28D9}
.b-deeplink{background:#E0E7FF;color:#1E3A8A}.b-exchange{background:#FDF1E3;color:#B45309}
.chip { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:700; margin:0 6px 4px 0;
        border:1px solid transparent }
.k-extracted { background:#E6F2F1; color:#0B5C55; border-color:#9ED3CC }
.k-generated { background:#EDE9FE; color:#4C1D95; border-color:#C4B5FD }
.k-candidate { background:#FFF4E5; color:#7C3A06; border-color:#F3C48C }
.s-strong { background:#E6F2F1; color:#0B5C55 } .s-moderate { background:#FFF7D6; color:#6B4E00 }
.s-weak { background:#FDECEC; color:#8B1A1A }
.t-full { background:#E6F2F1; color:#0B5C55 } .t-abs { background:#FFF7D6; color:#6B4E00 } .t-meta { background:#FDECEC; color:#8B1A1A }
.small { color: var(--muted); font-size: .82rem; }
.warnbox { background:#fff8ef; border:1px solid #f3c48c; border-radius:10px; padding:8px 12px; font-size:.85rem; color:#7c3a06 }
.infobox { background:#F1F5F9; border:1px solid #CBD5E1; border-radius:10px; padding:8px 12px; font-size:.85rem; color:#13233a }
.ref { padding-left: 2.2em; text-indent: -2.2em; margin: 0 0 8px 0; font-size: .95rem; line-height: 1.45 }
.evid { background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px 16px; }
.evid .q { font-size:1rem; font-weight:600; color:var(--ink) }
.evid .p { border-left:4px solid var(--accent); padding:6px 10px; background:#F7FBFA; margin:8px 0; font-size:.93rem }
.acct { display:flex; gap:10px; align-items:center; background:#fff; border:1px solid var(--line); border-radius:12px;
        padding:10px 12px; margin-bottom:6px }
.avatar { width:38px; height:38px; border-radius:50%; background:#0F766E; color:#fff; display:flex; align-items:center;
          justify-content:center; font-weight:700 }
img.avatar { object-fit:cover; flex:0 0 auto }
.pcard { display:flex; gap:18px; align-items:center; background:#fff; border:1px solid var(--line); border-radius:14px;
         padding:14px 18px; margin:6px 0 12px 0 }
.pcard img, .pcard .ph { width:96px; height:96px; border-radius:50%; object-fit:cover; flex:0 0 auto;
         background:#0F766E; color:#fff; display:flex; align-items:center; justify-content:center; font-size:2rem; font-weight:700 }
.pcard h3 { margin:0 0 2px 0 } .pcard .aff { color:#475569; font-size:.92rem }
.pcard .ids a, .pcard .ids span { display:inline-block; margin:6px 8px 0 0; font-size:.82rem; padding:2px 10px;
         border-radius:999px; background:#EEF6F5; color:#0F766E; text-decoration:none; border:1px solid #CFE7E3 }
.brand { display:flex; align-items:center; gap:10px; margin-bottom:4px }
.brand b { font-size:1.15rem; color:#0b1f33 }
/* focus visibility for keyboard users */
button:focus-visible, a:focus-visible, input:focus-visible, [role="tab"]:focus-visible { outline: 3px solid #B45309 !important;
  outline-offset: 2px }
</style>
"""
HIGH_CONTRAST = """<style>:root{--ink:#000;--muted:#222;--line:#555;--card:#fff}
.small,.stat span{color:#222!important}.hero{background:#000!important}.card{border-width:2px}</style>"""


# ------------------------------------------------------------------ resources
@st.cache_resource
def workspace() -> Workspace:
    from authorshand.store import DEFAULT_DB
    return Workspace(DEFAULT_DB)


def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def init_state():
    for k, v in {"account": None, "project_id": None, "selected_ids": [], "studio": None, "studio_key": None,
                 "profile": None, "index": None, "indexed_titles": [], "chat": [], "last_summary": None,
                 "quality_lists": [], "refresh_log": [], "serpapi_key": "", "session_token": ""}.items():
        ss(k, v)


def account() -> str:
    return st.session_state.get("account") or ""


def user() -> dict:
    return workspace().user(account()) if account() else {}


def prefs() -> dict:
    return user().get("prefs") or {}


def save_prefs(**kw):
    p = prefs()
    p.update(kw)
    workspace().update_user(account(), prefs=p)


def apply_prefs_css():
    p = prefs()
    st.markdown(CSS.replace("--fs: 1;", f"--fs: {p.get('font_scale', 1.0)};"), unsafe_allow_html=True)
    if p.get("high_contrast"):
        st.markdown(HIGH_CONTRAST, unsafe_allow_html=True)


def logo(size: int = 40) -> str:
    return LOGO_SVG.format(s=size)


# -------------------------------------------------------------------- sidebar
def photo_uri(u: dict | None = None) -> str:
    """Profile photo as a data URI (uploaded) or URL (Google Scholar picture), or ''."""
    u = u or user()
    pr = u.get("prefs") or {}
    return pr.get("photo") or ""


def make_photo(file_bytes: bytes) -> str:
    """Square-crop, resize to 256 px and return a JPEG data URI (kept small for the database)."""
    import base64
    import io
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(file_bytes))).convert("RGB")
    side = min(im.size)
    im = im.crop(((im.width - side) // 2, (im.height - side) // 2, (im.width + side) // 2, (im.height + side) // 2))
    im = im.resize((256, 256))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def avatar_html(u: dict, cls: str = "avatar") -> str:
    ph = photo_uri(u)
    initials = "".join(w[0] for w in (u.get("name") or account() or "?").replace("orcid:", "").split()[:2]).upper()
    if ph:
        return f"<img class='{cls}' src='{html.escape(ph, quote=True)}' alt='Profile photo'>"
    return f"<div class='{cls}'>{html.escape(initials[:2])}</div>"


def sidebar(on_logout):
    ws = workspace()
    u = user()
    with st.sidebar:
        st.markdown(f"<div class='brand'>{logo(34)}<b>{APP}</b></div>", unsafe_allow_html=True)
        st.caption(TAGLINE)
        initials = "".join(w[0] for w in (u.get("name") or account() or "?").replace("orcid:", "").split()[:2]).upper()
        ids = []
        if u.get("orcid"):
            ids.append("ORCID " + ("✔ verified" if u.get("orcid_verified") else "linked"))
        if u.get("researchgate"):
            ids.append("ResearchGate")
        if u.get("gscholar_url"):
            ids.append("Google Scholar")
        if u.get("linkedin"):
            ids.append("LinkedIn")
        if u.get("official_verified"):
            ids.append("✔ official e-mail")
        st.markdown(f"<div class='acct'>{avatar_html(u)}<div>"
                    f"<b>{html.escape(u.get('name') or 'Researcher')}</b><br><span class='small'>"
                    f"{html.escape(u.get('contact_email') or account())}</span><br><span class='small'>"
                    f"{' · '.join(ids) or 'No identities linked yet'}</span></div></div>", unsafe_allow_html=True)
        is_demo_acct = account() == demo.DEMO_EMAIL
        saved = prefs().get("data_mode")
        mode = st.radio("Data mode", ["Demo (offline)", "Live (internet)"], horizontal=True,
                        index=0 if (is_demo_acct and saved != "live") or saved == "demo" else 1,
                        help="Demo uses a bundled SYNTHETIC corpus (no internet). Live uses ORCID, OpenAlex, "
                             "Semantic Scholar, arXiv, Crossref, Unpaywall and DOAJ.")
        st.session_state.demo_mode = mode.startswith("Demo")
        if not is_demo_acct and saved != ("demo" if st.session_state.demo_mode else "live"):
            save_prefs(data_mode="demo" if st.session_state.demo_mode else "live")
            st.session_state.profile = None          # rebuild the profile from the chosen source
        if is_demo_acct:
            demo.seed_workspace(ws, account())

        projects = ws.projects(account())
        names = {p["id"]: f"{p['name']}  ({p['n_articles']})" + (f" · {p['n_alerts']} new" if p["n_alerts"] else "")
                 for p in projects}
        if projects:
            pids = list(names)
            last = prefs().get("last_project")
            cur = (st.session_state.project_id if st.session_state.project_id in pids
                   else last if last in pids else pids[0])
            sel = st.selectbox("📁 Project", pids, index=pids.index(cur), format_func=lambda i: names[i],
                               key=f"projsel_{st.session_state.get('proj_ver', 0)}")
            st.session_state.project_id = sel
            if sel != last:
                save_prefs(last_project=sel)        # reopen the same project next time
        else:
            st.session_state.project_id = None
        with st.expander("➕ New project", expanded=not projects):
            with st.form("newproj", clear_on_submit=True):
                n = st.text_input("Project name")
                tq = st.text_input("Saved topic search (for auto-refresh)")
                stl = st.selectbox("Citation style", list(STYLES), format_func=lambda k: STYLES[k],
                                   index=list(STYLES).index(prefs().get("style", "apa")) if prefs().get("style", "apa") in STYLES else 0)
                hrs = st.number_input("Auto-refresh every (hours, 0 = off)", 0, 720, 24)
                if st.form_submit_button("Create project") and n:
                    pid = ws.create_project(account(), n, topic_query=tq, citation_style=stl, auto_refresh_hours=hrs)
                    ws.update_project(pid, addins=hub.DEFAULT_ADDINS,
                                      settings={"review_goal": prefs().get("review_goal", "")})
                    set_project(pid)
                    st.rerun()

        st.divider()
        provider = st.selectbox("AI engine", ["Local extractive (free, no key)", "Anthropic Claude", "OpenAI",
                                              "Groq (free tier)", "Google Gemini (free tier)", "Ollama (local LLM)"],
                                help="Keys are kept only in this session's memory and are never saved to disk.")
        pmap = {"Local": "local", "Anthropic": "anthropic", "OpenAI": "openai", "Groq": "groq", "Google": "gemini",
                "Ollama": "ollama"}
        prov = next(v for k, v in pmap.items() if provider.startswith(k))
        key = st.text_input("API key (session only, not stored)", type="password") if prov not in ("local", "ollama") else None
        st.session_state.llm = LLM(prov, "", api_key=key or None)
        st.session_state.contact = u.get("contact_email") if not st.session_state.demo_mode else ""
        st.caption(f"Engine: {st.session_state.llm.label}")
        st.divider()
        if st.button("Sign out", width="stretch", icon=":material/logout:"):
            on_logout()
        if os.getenv("AUTHORSHAND_LAUNCHER_URL"):
            st.caption("Desktop app · your library: Documents\\AuthorsHand")
            st.link_button(f"Close {APP}", os.getenv("AUTHORSHAND_LAUNCHER_URL") + "quit", width="stretch",
                           icon=":material/power_settings_new:")


def current_settings() -> Settings:
    return Settings(contact_email=st.session_state.get("contact", "") or "",
                    demo_mode=st.session_state.get("demo_mode", True))


def llm() -> LLM:
    return st.session_state.get("llm") or LLM("local")


def project() -> dict | None:
    pid = st.session_state.get("project_id")
    return workspace().project(pid) if pid else None


def hero(title: str, subtitle: str):
    p = project()
    # Status line (not buttons): what this page is using right now. Changed in the sidebar.
    pills = [("Data", "Demo (offline, synthetic)" if st.session_state.get("demo_mode") else "Live (internet)"),
             ("AI engine", llm().label)]
    if p:
        pills.insert(0, ("Project", p["name"]))
    st.markdown(f"<div class='hero'><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p>"
                + "".join(f"<span class='pill'>● <b>{html.escape(k)}:</b> {html.escape(v)}</span>" for k, v in pills)
                + "<span class='hero-hint'>Status only — change Project, Data mode and AI engine in the left sidebar "
                  "(click » at the top-left if the sidebar is hidden).</span></div>",
                unsafe_allow_html=True)


def profile_is_demo() -> bool:
    """Fictional profile data is used ONLY for the demo account — never for a real researcher's account,
    whatever the Data mode (otherwise your page would show A. Demo's numbers)."""
    return account() == demo.DEMO_EMAIL


def set_project(pid: int):
    """Switch the current project from code (also moves the sidebar selector)."""
    st.session_state.project_id = pid
    st.session_state.proj_ver = st.session_state.get("proj_ver", 0) + 1
    save_prefs(last_project=pid)


def my_works() -> list[dict]:
    """The researcher's own papers: ORCID/OpenAlex profile (this session) + Google Scholar + exports + hand-added."""
    from authorshand import gscholar
    from authorshand import publications as pubs
    u = workspace().user(st.session_state.account)
    prof = st.session_state.get("profile")
    gs = u.get("gscholar") or (gscholar.DEMO_SNAPSHOT if profile_is_demo() else {})
    works = list(prof.works) if prof else []
    works = pubs.merge_scholar(works, gs.get("articles") or [])
    return pubs.merge_extra(works, (u.get("prefs") or {}).get("extra_works") or [])


def add_works_to_project(pid: int, works: list[dict], folder_name: str = "My publications") -> int:
    ws = workspace()
    fid = next((f["id"] for f in ws.folders(pid) if f["name"] == folder_name), None) or ws.add_folder(pid, folder_name)
    return sum(bool(ws.add_article(pid, w, fid, "")) for w in works)


def empty_project_help(p: dict, key: str):
    """Shown on any page that needs articles when the current project is empty."""
    mine = my_works()
    st.markdown(f"<div class='infobox'>The project <b>{html.escape(p['name'])}</b> has no articles yet. "
                "Add some in one click:</div>", unsafe_allow_html=True)
    b1, b2, b3 = st.columns(3)
    if b1.button(f"📥 Add my {len(mine)} publications", disabled=not mine, width="stretch", key=f"{key}_mine",
                 help=None if mine else "Open My Research Profile first so your papers are loaded."):
        n = add_works_to_project(p["id"], mine)
        st.success(f"Added {n} of your papers to “{p['name']}”.")
        st.rerun()
    if b2.button("➕ Search / DOI / PDF / import", width="stretch", key=f"{key}_lib"):
        st.switch_page(st.session_state.pages["library"])
    if b3.button("🧪 Load the example papers (synthetic)", width="stretch", key=f"{key}_ex",
                 help="Creates a separate, clearly labelled example project so you can try every feature."):
        set_project(demo.seed_example_project(workspace(), account()))
        st.rerun()


def need_project() -> dict | None:
    p = project()
    if not p:
        st.info("Create a project in the sidebar (➕ New project) to start.")
    return p


# ------------------------------------------------------------------- helpers
def copy_box(text: str, label: str = "Copy-ready text", height: int | None = None):
    """Code block with a built-in copy button (top-right)."""
    st.caption(f"{label} — copy with the icon at the top-right of the box")
    kw = {"height": height} if height else {}
    st.code(text, language=None, wrap_lines=True, **kw)


def chip(kind: str, text: str | None = None) -> str:
    return f"<span class='chip k-{kind}'>{html.escape(text or LABELS.get(kind, kind))}</span>"


def strength_chip(strength: str) -> str:
    return f"<span class='chip s-{strength}'>Support: {strength}</span>"


def source_chip(src: str) -> str:
    cls = "t-full" if is_full_text(src) else ("t-abs" if (src or "").startswith("Abstract") else "t-meta")
    return f"<span class='chip {cls}'>{html.escape(src or 'Unknown text source')}</span>"


def legend():
    st.markdown("<span class='small'>Labels:</span> " + chip("extracted") + chip("generated") + chip("candidate"),
                unsafe_allow_html=True)


def evidence_explorer(statements: list[dict], key: str, title: str = "Check the evidence behind each statement"):
    """Click a statement → see the supporting passage, paper, section, page and DOI."""
    if not statements:
        return
    st.markdown(f"**🔎 {title}** <span class='small'>(select a row)</span>", unsafe_allow_html=True)
    df = pd.DataFrame([{"Statement": s["statement"], "Label": LABELS.get(s["kind"], s["kind"]),
                        "Support": s["strength"], "Source": s.get("cite", ""),
                        "Section": s.get("section", ""), "Page": str(s.get("page") or "—")} for s in statements])
    weak = sum(1 for s in statements if s["strength"] == "weak")
    if weak:
        st.markdown(f"<div class='warnbox'>{weak} statement(s) have <b>weak</b> support in the selected papers — "
                    "check or rewrite them before use.</div>", unsafe_allow_html=True)
    ev = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key=f"ev_{key}", column_config={"Statement": st.column_config.TextColumn(width="large")})
    rows = ev.selection.rows if ev and getattr(ev, "selection", None) else []
    if rows:
        s = statements[rows[0]]
        doi = s.get("doi") or ""
        st.markdown(
            f"<div class='evid'><div class='q'>{html.escape(s['statement'])}</div>"
            f"<div style='margin-top:6px'>{chip(s['kind'])}{strength_chip(s['strength'])}"
            f"{source_chip(s.get('text_source', ''))}</div>"
            f"<div class='p'>{html.escape(s.get('context') or s.get('passage') or 'No supporting passage found.')}</div>"
            f"<div class='small'><b>{html.escape(s.get('paper', ''))}</b> {html.escape(s.get('cite', ''))} · section: "
            f"{html.escape(s.get('section') or '—')} · page: {s.get('page') or 'not available'} · "
            + (f"DOI: <a href='https://doi.org/{html.escape(doi)}' target='_blank'>{html.escape(doi)}</a>" if doi else "no DOI")
            + f" · support score {s.get('support', 0):.2f}</div></div>", unsafe_allow_html=True)


def tool_buttons(stage: str, query: str = "", doi: str = "", key: str = ""):
    p = project()
    enabled = (p or {}).get("addins") or hub.DEFAULT_ADDINS
    tools = [t for t in hub.for_stage(stage, enabled) if t["connection"] != "builtin"]
    if not tools:
        return
    st.markdown("**🧩 Add-ins for this stage** <span class='small'>(these open the external tool; enable more in "
                "Tool Hub)</span>", unsafe_allow_html=True)
    cols = st.columns(min(5, len(tools)))
    for i, t in enumerate(tools[:10]):
        cols[i % len(cols)].link_button(f"{t['name']} ↗", hub.launch_url(t, query, doi), width="stretch",
                                        help=f"{hub.label(t)} · {t['what']}")


def summary_for(article: dict) -> dict:
    """Summarise once, store in the workspace, reuse afterwards."""
    if article.get("summary") and article["summary"].get("evidence") and "strength" in (article["summary"]["evidence"] or [{}])[0]:
        return article["summary"]
    p = article["paper"]
    text = article.get("text") or f"{p.get('title', '')}\n\nAbstract: {p.get('abstract', '')}"
    s = PaperSummarizer(llm()).summarize(text, title=p.get("title"), pages=p.get("pages_text"))
    workspace().update_article(article["id"], summary=s)
    article["summary"] = s
    return s


def fig_style(fig: go.Figure, h: int = 320, legend: bool = True) -> go.Figure:
    fig.update_layout(height=h, margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Source Sans Pro, Arial", size=13, color="#13233a"),
                      colorway=PALETTE, showlegend=legend, title_font=dict(size=15))
    fig.update_xaxes(gridcolor="#E2E8F0", zeroline=False)
    fig.update_yaxes(gridcolor="#E2E8F0", zeroline=False)
    return fig


def stat_row(items: list[tuple[str, str]]):
    cols = st.columns(len(items))
    for c, (v, l) in zip(cols, items):
        c.markdown(f"<div class='stat'><b>{html.escape(str(v))}</b><span>{html.escape(str(l))}</span></div>",
                   unsafe_allow_html=True)


def integrity_note():
    st.markdown("<div class='warnbox'>✍️ Drafts are <b>scaffolds</b> built from the selected papers and always cited. "
                "In local mode they reuse source sentences — paraphrase in your own words before submission "
                "(with an AI engine the drafts are paraphrased). Check every statement in the evidence table.</div>",
                unsafe_allow_html=True)


def demo_banner():
    if st.session_state.get("demo_mode"):
        st.markdown("<div class='infobox'>ℹ️ <b>Demo mode:</b> papers, journals and profile numbers shown here are "
                    "<b>synthetic</b> examples created for testing — not real publications.</div>",
                    unsafe_allow_html=True)
