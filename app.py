"""
Author's Hand — AI research companion: autonomous research agent, evidence-traceable
summaries and a writing studio, linked to ORCID, ResearchGate and Google Scholar.

Run:   streamlit run app.py
Final Capstone Project (Option 5: Autonomous AI Research Agent) — IIT Guwahati E&ICT Academy, Generative AI.
"""
import streamlit as st

try:  # use the Windows / macOS certificate store (university and corporate proxies)
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

st.set_page_config(page_title="Author's Hand", page_icon="✍️", layout="wide")

from ui.common import apply_prefs_css, init_state, prefs, sidebar  # noqa: E402
from ui.login import logout, page_login, page_onboarding, try_restore_session, write_session_cookie  # noqa: E402

init_state()
apply_prefs_css()

# Every address the signed-in app knows. Before sign-in / onboarding they all show the gate page,
# so a bookmarked link (e.g. /studio) never triggers Streamlit's "Page not found" dialog.
PATHS = ["dashboard", "library", "studio", "reader", "review", "map", "quality", "tools", "profile", "agent",
         "evaluation", "settings", "about", "install"]


def gate(fn, title, icon):
    return [st.Page(fn, title=title, icon=icon, default=True)] + [
        st.Page(fn, title=title, icon=icon, url_path=p) for p in PATHS]


if not st.session_state.get("account") and not try_restore_session():
    write_session_cookie()                      # clears the cookie after Sign out
    st.navigation(gate(page_login, "Sign in", "🔐"), position="hidden").run()
    st.stop()

write_session_cookie()

if not prefs().get("onboarded"):
    st.navigation(gate(page_onboarding, "Welcome", "👋"), position="hidden").run()
    st.stop()

from ui.pages_about import page_about  # noqa: E402
from ui.pages_core import page_dashboard, page_library  # noqa: E402
from ui.pages_review import page_review  # noqa: E402
from ui.pages_settings import page_settings  # noqa: E402
from ui.pages_studio import page_reader, page_studio  # noqa: E402
from ui.pages_tools import (page_agent, page_eval, page_hub, page_install, page_map, page_profile,  # noqa: E402
                            page_quality)

pages = {
    # My Research Profile is the first page after sign-in (address "/"); the dashboard is one click away.
    "profile": st.Page(page_profile, title="My Research Profile", icon="👤", default=True),
    "dashboard": st.Page(page_dashboard, title="Project dashboard", icon="🏠", url_path="dashboard"),
    "library": st.Page(page_library, title="Library & folders", icon="📁", url_path="library"),
    "studio": st.Page(page_studio, title="Writing Studio", icon="✍️", url_path="studio"),
    "reader": st.Page(page_reader, title="Paper Reader", icon="📄", url_path="reader"),
    "review": st.Page(page_review, title="Systematic review", icon="🧾", url_path="review"),
    "map": st.Page(page_map, title="Citation Map", icon="🗺️", url_path="map"),
    "quality": st.Page(page_quality, title="Journal Quality Check", icon="🏅", url_path="quality"),
    "hub": st.Page(page_hub, title="Tool Hub (add-ins)", icon="🧩", url_path="tools"),
    "agent": st.Page(page_agent, title="Research Agent", icon="🤖", url_path="agent"),
    "eval": st.Page(page_eval, title="Evaluation", icon="📊", url_path="evaluation"),
    "settings": st.Page(page_settings, title="Settings & privacy", icon="⚙️", url_path="settings"),
    "about": st.Page(page_about, title="About & feature status", icon="ℹ️", url_path="about"),
    "install": st.Page(page_install, title="Install app", icon="📱", url_path="install"),
}
st.session_state.pages = pages
nav = st.navigation({
    "Workspace": [pages["profile"], pages["dashboard"], pages["library"], pages["studio"], pages["reader"],
                  pages["review"]],
    "Research tools": [pages["map"], pages["quality"], pages["hub"], pages["agent"]],
    "Account & more": [pages["settings"], pages["eval"], pages["about"], pages["install"]],
})
sidebar(logout)
nav.run()
