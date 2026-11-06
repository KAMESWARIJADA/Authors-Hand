"""Welcome / sign-in / sign-up page and first-time guided setup."""
from __future__ import annotations

import html

import streamlit as st

from authorshand import auth, demo
from authorshand.citations import STYLES
from authorshand.connectors import HTTP, OrcidClient, extract_orcid, valid_orcid

from .common import APP, TAGLINE, logo, workspace

LOGIN_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], header [data-testid="stToolbar"] {display:none}
.block-container { max-width: 1180px; padding-top: 2.2rem; }
.welcome { background: linear-gradient(140deg,#0b1f33 0%,#0f3d4a 55%,#0f766e 100%); border-radius: 22px; color:#fff;
           padding: 38px 38px 30px; min-height: 600px; position: relative; overflow: hidden }
.welcome:after { content:""; position:absolute; right:-80px; bottom:-80px; width:260px; height:260px; border-radius:50%;
                 background: radial-gradient(circle, rgba(243,196,140,.35), rgba(243,196,140,0) 70%) }
.welcome h1 { color:#fff; font-size: 2.35rem; margin: 18px 0 6px; letter-spacing:-.02em }
.welcome .tag { color:#cfe3e8; font-size:1.05rem; margin-bottom: 26px }
.feat { display:flex; gap:12px; margin: 14px 0; align-items:flex-start }
.feat .ic { width:34px; height:34px; border-radius:10px; background:rgba(255,255,255,.12); display:flex;
            align-items:center; justify-content:center; font-size:17px; flex:none }
.feat b { display:block; color:#fff; font-size:.98rem } .feat span { color:#bcd3dc; font-size:.88rem }
.trust { margin-top: 26px; font-size:.8rem; color:#9fbfc8 }
.formcard h2 { margin: 6px 0 2px; font-size: 1.6rem; color:#0b1f33 }
.formcard .sub { color:#5b6b7f; margin-bottom: 8px }
.or { text-align:center; color:#5b6b7f; font-size:.82rem; margin: 6px 0 }
.code { font: 600 1.3rem Consolas, monospace; letter-spacing: .12em; background:#FFF7E8; border:2px dashed #B45309;
        border-radius:10px; padding:10px 14px; display:inline-block; color:#7c3a06 }
</style>
"""

FEATURES = [
    ("🔗", "One research identity", "Sign in with Gmail or ORCID; link ResearchGate and Google Scholar."),
    ("🗂️", "Projects & folders", "Every paper in its project, auto-refreshed with new and citing papers."),
    ("✍️", "From papers to your paper", "Introduction, review, gaps, methods, hypotheses — each claim traceable."),
    ("🔎", "Evidence you can check", "Every statement linked to the passage, page and DOI it came from."),
    ("🏅", "Cite & publish safely", "Any citation style, journal quality checks, 45 research add-ins."),
]


def _oidc_providers() -> list[str]:
    try:
        a = st.secrets.get("auth", {})
        return [p for p in ("google", "orcid", "linkedin") if p in a]
    except Exception:
        return []


def _finish_login(account: str, remember: bool = True):
    ws = workspace()
    st.session_state.account = account
    st.session_state.project_id = None
    if remember:
        tok = auth.new_session(ws, account)
        st.session_state.session_token = tok
        st.session_state.pending_cookie = tok      # written by write_session_cookie() on the next run
    st.rerun()


COOKIE = "ah_session"


def write_session_cookie():
    """Store / clear the remember-me token as a browser cookie (survives refresh and app restarts).

    The writer is rendered on every run until the browser reports the cookie back, so a quick rerun
    right after sign-in cannot swallow it."""
    want = st.session_state.get("pending_cookie")
    if want is None:
        return
    try:
        have = st.context.cookies.get(COOKIE, "")
    except Exception:
        have = None
    if have is not None and have == want:
        st.session_state.pop("pending_cookie", None)
        return
    js = (f"document.cookie='{COOKIE}={want}; path=/; max-age={30 * 86400}; SameSite=Lax';" if want else
          f"document.cookie='{COOKIE}=; path=/; max-age=0; SameSite=Lax';")
    st.html(f"<script>{js}</script>", unsafe_allow_javascript=True)


def try_restore_session() -> bool:
    """Remember-me token in the URL, or a completed Google / ORCID sign-in."""
    ws = workspace()
    try:
        tok = st.context.cookies.get(COOKIE, "")
    except Exception:
        tok = ""
    acc = auth.session_account(ws, tok)
    if acc:
        st.session_state.account = acc
        st.session_state.session_token = tok
        return True
    try:
        logged = bool(st.user.is_logged_in)
    except Exception:
        logged = False
    if logged:
        claims = st.user.to_dict()
        iss = str(claims.get("iss", ""))
        provider = "orcid" if "orcid.org" in iss else ("linkedin" if "linkedin.com" in iss else "google")
        try:
            u = auth.oidc_sign_in(ws, provider, claims)
        except auth.AuthError as e:
            st.error(str(e))
            return False
        st.session_state.account = u["email"]
        tok = auth.new_session(ws, u["email"])
        st.session_state.session_token = tok
        st.session_state.pending_cookie = tok
        return True
    return False


def logout():
    ws = workspace()
    auth.end_session(ws, st.session_state.get("session_token", ""))
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state.pending_cookie = ""            # clears the browser cookie on the login page
    try:
        if st.user.is_logged_in:
            st.logout()
    except Exception:
        pass
    st.rerun()


def page_login():
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    write_session_cookie()
    left, right = st.columns([1.08, 1], gap="large")
    with left:
        feats = "".join(f"<div class='feat'><div class='ic'>{i}</div><div><b>{html.escape(t)}</b>"
                        f"<span>{html.escape(d)}</span></div></div>" for i, t, d in FEATURES)
        st.markdown(f"<div class='welcome'>{logo(64)}<h1>{APP}</h1><div class='tag'>{TAGLINE}</div>{feats}"
                    "<div class='trust'>Your library stays in your own workspace. Passwords are stored only as "
                    "salted hashes. API keys are never saved.</div></div>", unsafe_allow_html=True)
    with right:
        st.markdown("<div class='formcard'><h2>Welcome</h2><div class='sub'>Sign in to your research workspace, "
                    "or create an account if you are new.</div></div>", unsafe_allow_html=True)
        providers = _oidc_providers()
        c1, c2 = st.columns(2)
        g = c1.button("Continue with Google", width="stretch", disabled="google" not in providers,
                      icon=":material/mail:", help=None if "google" in providers else
                      "Google sign-in is not set up on this installation yet — see Settings → Sign-in providers.")
        o = c2.button("Continue with ORCID", width="stretch", disabled="orcid" not in providers,
                      icon=":material/badge:", help=None if "orcid" in providers else
                      "ORCID sign-in is not set up on this installation yet — see Settings → Sign-in providers.")
        lk = st.button("Continue with LinkedIn", width="stretch", disabled="linkedin" not in providers,
                       icon=":material/work:", help=None if "linkedin" in providers else
                       "LinkedIn sign-in is not set up on this installation yet — see Settings → Sign-in providers.")
        if g:
            st.login("google")
        if o:
            st.login("orcid")
        if lk:
            st.login("linkedin")
        st.markdown("<div class='or'>— or use your Gmail / official e-mail or ORCID iD —</div>", unsafe_allow_html=True)
        t_in, t_up, t_forgot = st.tabs(["Sign in", "Create account", "Forgot password?"])
        ws = workspace()
        with t_in:
            with st.form("signin"):
                ident = st.text_input("Gmail / e-mail or ORCID iD", placeholder="you@gmail.com or 0000-0002-…")
                pw = st.text_input("Password", type="password")
                remember = st.checkbox("Keep me signed in on this device (30 days)", value=True)
                if st.form_submit_button("Sign in", type="primary", width="stretch"):
                    try:
                        u = auth.sign_in(ws, ident, pw)
                        _finish_login(u["email"], remember)
                    except auth.AuthError as e:
                        st.error(str(e))
        with t_up:
            if st.session_state.get("new_recovery"):
                code, acc = st.session_state.new_recovery
                st.success("Account created.")
                st.markdown("Save this **recovery code** — it is the only way to reset your password on this "
                            "installation (there is no e-mail server):")
                st.markdown(f"<div class='code'>{code}</div>", unsafe_allow_html=True)
                if st.button("I have saved it — continue to my dashboard", type="primary"):
                    del st.session_state["new_recovery"]
                    _finish_login(acc, True)
            else:
                with st.form("signup"):
                    name = st.text_input("Full name", placeholder="Dr. Firstname Lastname")
                    email = st.text_input("Gmail / e-mail", placeholder="you@gmail.com")
                    orcid = st.text_input("ORCID iD (optional if you give an e-mail)", placeholder="0000-0000-0000-0000")
                    a, b = st.columns(2)
                    pw = a.text_input("Password", type="password", help="At least 8 characters with letters and numbers")
                    pw2 = b.text_input("Repeat password", type="password")
                    ok = st.checkbox("I understand what is stored and sent to external services "
                                     "(see Settings → Privacy after signing in).")
                    if st.form_submit_button("Create account", type="primary", width="stretch"):
                        if not ok:
                            st.error("Please confirm the privacy note.")
                        else:
                            try:
                                u, code = auth.sign_up(ws, name, email, orcid, pw, pw2)
                                st.session_state.new_recovery = (code, u["email"])
                                st.rerun()
                            except auth.AuthError as e:
                                st.error(str(e))
                st.caption("A typed ORCID iD is checked for a valid checksum. Only “Continue with ORCID” "
                           "proves that the iD is yours (shown as ✔ verified).")
        with t_forgot:
            with st.form("forgot"):
                ident = st.text_input("Gmail / e-mail or ORCID iD", key="fg_id")
                code = st.text_input("Recovery code (shown when you created the account)")
                a, b = st.columns(2)
                pw = a.text_input("New password", type="password", key="fg_pw")
                if st.form_submit_button("Reset password", width="stretch"):
                    try:
                        newcode = auth.reset_password(ws, ident, code, pw)
                        st.success("Password changed. Your NEW recovery code (save it):")
                        st.markdown(f"<div class='code'>{newcode}</div>", unsafe_allow_html=True)
                    except auth.AuthError as e:
                        st.error(str(e))
        st.divider()
        if st.button("Explore the demo workspace (no sign-up)", width="stretch", icon=":material/play_circle:"):
            demo.seed_workspace(ws, demo.DEMO_EMAIL)
            u = ws.user(demo.DEMO_EMAIL)
            if not (u.get("prefs") or {}).get("onboarded"):
                ws.update_user(demo.DEMO_EMAIL, prefs={"onboarded": True, "discipline": "Management / HR analytics",
                                                       "review_goal": "Writing a research paper", "style": "apa"},
                               gscholar_url="https://scholar.google.com/citations?user=DEMO00000000")
            _finish_login(demo.DEMO_EMAIL, True)
        st.caption(f"{APP} · capstone project, IIT Guwahati E&ICT Academy — Generative AI programme")


DISCIPLINES = ["Management / Business", "HR / Organisational behaviour", "Finance / Banking", "Computer science / AI",
               "Education", "Health / Medicine", "Engineering", "Social sciences", "Humanities", "Other"]
GOALS = ["Writing a research paper", "Thesis / dissertation", "Systematic review", "Scoping review",
         "Qualitative / thematic synthesis", "Exploratory reading", "Teaching material / course design"]
STUDY_TYPES = ["Quantitative", "Qualitative", "Mixed methods", "Review / synthesis", "Design science / artefact",
               "Conceptual"]


def page_onboarding():
    ws = workspace()
    u = ws.user(st.session_state.account)
    st.markdown(f"<div class='hero'><h1>Welcome to {APP}, {html.escape((u.get('name') or 'researcher').split()[0])}</h1>"
                "<p>Two minutes of setup so the workspace fits your field and your kind of work. You can change all "
                "of this later in Settings.</p></div>", unsafe_allow_html=True)
    with st.form("onboard"):
        c1, c2 = st.columns(2)
        disc = c1.selectbox("Your discipline", DISCIPLINES)
        stype = c2.selectbox("Main study type", STUDY_TYPES)
        goal = c1.selectbox("What are you working on now?", GOALS)
        style = c2.selectbox("Preferred citation style", list(STYLES), format_func=lambda k: STYLES[k])
        terms = st.text_area("Field-specific methods or terms to recognise (optional, one per line, e.g. "
                             "'fsQCA', 'event study', 'grounded theory')", height=90)
        st.markdown("**Link your research identities** (optional — you can do this later)")
        c1, c2, c3 = st.columns(3)
        orcid = c1.text_input("ORCID iD", value=u.get("orcid", ""))
        rg = c2.text_input("ResearchGate profile URL", value=u.get("researchgate", ""))
        gs = c3.text_input("Google Scholar profile URL", value=u.get("gscholar_url", ""))
        proj = st.text_input("Name your first project", value="My first project")
        topic = st.text_input("Its topic (used to find new papers automatically)")
        if st.form_submit_button("Finish setup", type="primary"):
            oid = extract_orcid(orcid)
            if orcid and not valid_orcid(oid):
                st.error("That ORCID iD fails the checksum.")
                st.stop()
            custom = {t.strip(): [t.strip().lower()] for t in terms.splitlines() if t.strip()}
            ws.update_user(u["email"], orcid=oid or u.get("orcid", ""), researchgate=rg, gscholar_url=gs,
                           prefs={**(u.get("prefs") or {}), "onboarded": True, "discipline": disc,
                                  "study_type": stype, "review_goal": goal, "style": style,
                                  "lexicon": {"methods": custom}})
            if proj and not ws.projects(u["email"]):
                from authorshand import tools_hub as hub
                pid = ws.create_project(u["email"], proj, topic_query=topic, citation_style=style)
                ws.update_project(pid, addins=hub.DEFAULT_ADDINS, settings={"review_goal": goal,
                                                                         "lexicon": {"methods": custom}})
                st.session_state.project_id = pid
            st.rerun()
    if st.button("Skip for now"):
        ws.update_user(u["email"], prefs={**(u.get("prefs") or {}), "onboarded": True})
        st.rerun()


def orcid_lookup_name(oid: str, settings) -> str:
    try:
        return OrcidClient(HTTP(settings)).person(oid).get("name", "")
    except Exception:
        return ""
