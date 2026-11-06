"""Settings: profile & identities, privacy, accessibility, data (backup / restore / delete), sign-in providers."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pandas as pd
import streamlit as st

from authorshand import auth, demo, verify
from authorshand.citations import STYLES
from authorshand.connectors import HTTP, OrcidClient, extract_orcid, valid_orcid

from .common import APP, account, avatar_html, current_settings, hero, make_photo, save_prefs, user, workspace
from .login import DISCIPLINES, GOALS, STUDY_TYPES, logout

PRIVACY_ROWS = [
    ("Your account (name, e-mail / ORCID iD, password hash, recovery-code hash)", "Local database file", "Never sent"),
    ("Projects, folders, papers, PDFs' text, notes, tags, summaries, review records", "Local database file",
     "Never sent, except text you send to an AI engine you choose"),
    ("AI engine API keys (Claude, OpenAI, Groq, Gemini), SerpApi key, Zotero key", "This session's memory only",
     "Sent only to that provider; cleared when you close the app"),
    ("Search words and DOIs", "—", "OpenAlex, Semantic Scholar, arXiv, Crossref, Unpaywall, doi.org"),
    ("Your ORCID iD", "Local database", "ORCID public API and OpenAlex (to read your public record)"),
    ("Your e-mail — only if you press “Find my ORCID from my e-mail”", "—", "ORCID public search API"),
    ("Contact e-mail (Live mode)", "—", "Sent as the ‘polite pool’ address to OpenAlex / Crossref / Unpaywall"),
    ("Official e-mail + one-time code (hashed)", "Local database / session", "Code sent only to that address via "
     "the e-mail account you set up"),
    ("E-mail sending account and app password", "Private file on this computer (smtp.json)", "Only to your mail server"),
    ("LinkedIn profile link", "Local database", "Never sent (LinkedIn sign-in, if enabled, happens on linkedin.com)"),
    ("Google Scholar profile ID", "Local database", "SerpApi — only if you use the automatic route"),
    ("Journal names / ISSNs you check", "—", "OpenAlex, DOAJ, Crossref"),
    ("Paper text for summaries", "—", "Only to the AI engine you select; the free local engine sends nothing"),
]


def _db_path() -> str:
    return workspace().path


def page_settings():
    hero("Settings & privacy", "Your identities, what is stored and shared, accessibility, backups and sign-in options.")
    ws = workspace()
    u = user()
    t1, t2, t3, t4, t5, t6 = st.tabs(["Profile & identities", "Privacy", "Accessibility", "Your data",
                                      "Password", "Sign-in providers"])

    with t1:
        st.markdown("**Profile photo**")
        c0, c1, c2 = st.columns([0.6, 2.4, 1.4])
        c0.markdown(f"<div class='pcard' style='border:none;padding:0;margin:0'>{avatar_html(u, 'ph')}</div>",
                    unsafe_allow_html=True)
        up = c1.file_uploader("Upload a photo (JPG / PNG, square works best)", type=["jpg", "jpeg", "png", "webp"],
                              key="photo_up")
        if up and c1.button("Save photo", type="primary"):
            try:
                save_prefs(photo=make_photo(up.getvalue()))
                st.success("Photo saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not read that image: {e}")
        gthumb = (u.get("gscholar") or {}).get("thumbnail", "")
        if gthumb and c2.button("Use my Google Scholar photo", width="stretch"):
            save_prefs(photo=gthumb)
            st.rerun()
        if (u.get("prefs") or {}).get("photo") and c2.button("Remove photo", width="stretch"):
            save_prefs(photo="")
            st.rerun()
        c2.caption("Shown in the sidebar and on My Research Profile. Stored only in your local database.")
        with st.form("profile_form"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Display name", u.get("name", ""))
            contact = c2.text_input("Contact e-mail", u.get("contact_email", ""))
            c1, c2 = st.columns(2)
            orcid = c1.text_input("ORCID iD", u.get("orcid", ""),
                                  help="Checked with the ORCID checksum; ✔ verified only after “Continue with ORCID”.")
            rg = c2.text_input("ResearchGate profile URL", u.get("researchgate", ""))
            c1, c2, c3 = st.columns(3)
            gs = c1.text_input("Google Scholar profile URL", u.get("gscholar_url", ""))
            li = c2.text_input("LinkedIn profile URL", u.get("linkedin", ""),
                               placeholder="https://www.linkedin.com/in/your-name")
            zot = c3.text_input("Zotero user ID", u.get("zotero_user", ""))
            pr = u.get("prefs") or {}
            c1, c2, c3, c4 = st.columns(4)
            disc = c1.selectbox("Discipline", DISCIPLINES, index=DISCIPLINES.index(pr["discipline"])
                                if pr.get("discipline") in DISCIPLINES else 0)
            stype = c2.selectbox("Study type", STUDY_TYPES, index=STUDY_TYPES.index(pr["study_type"])
                                 if pr.get("study_type") in STUDY_TYPES else 0)
            goal = c3.selectbox("Current goal", GOALS, index=GOALS.index(pr["review_goal"])
                                if pr.get("review_goal") in GOALS else 0)
            style = c4.selectbox("Default citation style", list(STYLES), format_func=lambda k: STYLES[k],
                                 index=list(STYLES).index(pr.get("style", "apa")) if pr.get("style", "apa") in STYLES else 0)
            if st.form_submit_button("Save profile", type="primary"):
                oid = extract_orcid(orcid)
                if orcid and not valid_orcid(oid):
                    st.error("That ORCID iD fails the checksum.")
                else:
                    ws.update_user(account(), name=name, contact_email=contact,
                                   orcid=oid, orcid_verified=u.get("orcid_verified") if oid == u.get("orcid") else 0,
                                   researchgate=rg, gscholar_url=gs, zotero_user=zot, linkedin=li,
                                   prefs={**pr, "discipline": disc, "study_type": stype, "review_goal": goal, "style": style})
                    st.success("Saved")
                    st.rerun()
        # ---------------- official e-mail verification
        st.markdown("**Official (institutional) e-mail — verify it**")
        if u.get("official_verified"):
            from datetime import datetime as _dt
            st.success(f"✔ {u.get('official_email')} verified on "
                       f"{_dt.fromtimestamp(u['official_verified']).strftime('%d %b %Y')}. You can also sign in with it.")
        c1, c2 = st.columns([3, 1])
        off = c1.text_input("Official e-mail", u.get("official_email", ""), placeholder="name@university.ac.in",
                            key="off_email")
        smtp_ok = bool(verify.load_smtp().get("host"))
        send = c2.button("Send code", width="stretch", disabled=not smtp_ok,
                         help=None if smtp_ok else "Set up e-mail sending first: Settings → Sign-in providers → "
                                                   "E-mail for verification codes.")
        if off and not verify.is_institutional(off):
            st.warning("This looks like a personal address (Gmail, Yahoo, Outlook …). Use your institution's e-mail.")
        if not smtp_ok:
            st.caption("To send codes, set up e-mail sending once in **Sign-in providers → E-mail for verification "
                       "codes**. If your institution uses Google Workspace, **Continue with Google** with your "
                       "official address also verifies it.")
        if send:
            other = ws.find_user(off) if verify.EMAIL_RE.match(off or "") else None
            if not verify.EMAIL_RE.match(off or ""):
                st.error("Enter a valid e-mail address.")
            elif other and other["email"] != account():
                st.error("That e-mail already belongs to another account.")
            else:
                code, pending = verify.new_code()
                try:
                    verify.send_code(off, code, u.get("name", ""))
                    ws.update_user(account(), official_email=off.lower(), official_verified=0)
                    st.session_state.off_pending = pending
                    st.success(f"Code sent to {off}. It is valid for {verify.CODE_MINUTES} minutes — check spam too.")
                except Exception as e:
                    st.error(f"Could not send the e-mail: {e}")
        if st.session_state.get("off_pending"):
            c1, c2 = st.columns([3, 1])
            code_in = c1.text_input("6-digit code from the e-mail", max_chars=6, key="off_code")
            if c2.button("Verify", type="primary", width="stretch"):
                ok, msg = verify.check_code(st.session_state.off_pending, code_in)
                if ok:
                    import time as _t
                    ws.update_user(account(), official_verified=_t.time())
                    st.session_state.pop("off_pending", None)
                    st.success("✔ Official e-mail verified.")
                    st.rerun()
                else:
                    st.error(msg)

        st.markdown("**Find my ORCID iD (optional)**")
        consent = st.checkbox("I agree to send my e-mail address to the ORCID public search API for this lookup. "
                              "(It only finds records where you made your e-mail public.)")
        if st.button("Find my ORCID iD", disabled=not consent):
            if st.session_state.get("demo_mode"):
                st.info(f"Demo: matched {demo.DEMO_ORCID} (A. Demo).")
            else:
                try:
                    hits = OrcidClient(HTTP(current_settings())).search(email=u.get("contact_email") or account())
                    st.write(hits or "No public ORCID record shows this e-mail — enter your iD manually.")
                except Exception as e:
                    st.warning(f"ORCID search unavailable: {e}")
        st.markdown("**Unlink accounts**")
        cols = st.columns(6)
        for col, (label, fields) in zip(cols, [("ORCID", {"orcid": "", "orcid_verified": 0}),
                                               ("ResearchGate", {"researchgate": ""}),
                                               ("Google Scholar", {"gscholar_url": "", "gscholar": {}}),
                                               ("LinkedIn", {"linkedin": ""}),
                                               ("Official e-mail", {"official_email": "", "official_verified": 0}),
                                               ("Zotero", {"zotero_user": ""})]):
            if col.button(f"Unlink {label}", width="stretch"):
                ws.update_user(account(), **fields)
                st.session_state.profile = None
                st.rerun()

    with t2:
        st.markdown(f"**What {APP} stores and sends**")
        st.dataframe(pd.DataFrame(PRIVACY_ROWS, columns=["Data", "Stored where", "Sent to"]), hide_index=True,
                     width="stretch")
        st.markdown(f"- Database file: `{_db_path()}`\n"
                    "- Passwords are stored only as salted PBKDF2-SHA256 hashes; nobody (including you) can read them.\n"
                    "- “Keep me signed in” stores a random token (hashed) for 30 days; Sign out deletes it.\n"
                    "- Identity discovery (finding your ORCID from your e-mail) runs only when you press the button.\n"
                    "- With the free local engine, no paper text leaves your computer.")

    with t3:
        pr = u.get("prefs") or {}
        fs = st.slider("Text size", 0.85, 1.5, float(pr.get("font_scale", 1.0)), 0.05)
        hc = st.toggle("High-contrast mode", value=bool(pr.get("high_contrast")))
        if st.button("Apply", type="primary"):
            save_prefs(font_scale=fs, high_contrast=hc)
            st.rerun()
        st.caption("All pages work with the keyboard: Tab / Shift+Tab to move, Enter or Space to press, arrow keys "
                   "inside tabs and tables. Icons always come with a text label.")

    with t4:
        st.markdown("**Backup** — everything in your account (projects, folders, papers, notes, review records)")
        data = json.dumps(ws.export_user(account()), default=str).encode()
        st.download_button("⬇ Download backup (.json)", data, f"authorshand_backup_{account().replace(':', '_')}.json",
                           type="primary")
        st.markdown("**Restore** — adds the projects from a backup file to this account")
        up = st.file_uploader("Backup file", type=["json"])
        if up and st.button("Restore projects"):
            try:
                n = ws.import_user(account(), json.loads(up.read()))
                st.success(f"Restored {n} project(s).")
            except Exception as e:
                st.error(f"Could not restore: {e}")
        st.markdown("**Delete my account and all my data** — permanent")
        conf = st.text_input("Type DELETE to confirm")
        if st.button("Delete everything", disabled=conf != "DELETE"):
            ws.delete_user(account())
            logout()

    with t5:
        if account() == demo.DEMO_EMAIL:
            st.info("The demo workspace has no password.")
        else:
            with st.form("pw"):
                old = st.text_input("Current password (leave empty if you only used Google/ORCID)", type="password")
                new = st.text_input("New password", type="password")
                new2 = st.text_input("Repeat new password", type="password")
                if st.form_submit_button("Change password", type="primary"):
                    try:
                        auth.change_password(ws, account(), old, new, new2)
                        st.success("Password changed.")
                    except auth.AuthError as e:
                        st.error(str(e))

    with t6:
        desktop = bool(os.getenv("AUTHORSHAND_DATA_DIR"))
        port = 8765 if desktop else (st.get_option("server.port") or 8501)
        redirect = f"http://localhost:{port}/oauth2callback"
        st.markdown(f"""Enable **Continue with Google** and **Continue with ORCID** on the login page (free).

**Google** — console.cloud.google.com → create a project → *APIs & Services → OAuth consent screen* (External,
add your e-mail as test user) → *Credentials → Create credentials → OAuth client ID → Web application* →
Authorised redirect URI: `{redirect}` → copy the Client ID and Client secret.

**ORCID** — orcid.org → sign in → your name (top right) → *Developer tools* → register for the free Public API →
redirect URI: `{redirect}` (ORCID may require an https address — then use it on the hosted version) → copy
Client ID and Client secret.

**LinkedIn** — linkedin.com/developers → *Create app* (needs a LinkedIn company page; your institution's page
works) → *Products* → add **Sign In with LinkedIn using OpenID Connect** → *Auth* → add the redirect URL
`{redirect}` → copy Client ID and Primary Client Secret. LinkedIn sign-in gives your name and verified e-mail;
LinkedIn does not let apps read your connections or posts.

On a hosted (online) version use `https://YOUR-APP/oauth2callback` instead.""")
        with st.form("oidc"):
            c1, c2 = st.columns(2)
            gid = c1.text_input("Google Client ID")
            gsec = c2.text_input("Google Client secret", type="password")
            oid_ = c1.text_input("ORCID Client ID (APP-…)")
            osec = c2.text_input("ORCID Client secret", type="password")
            lid = c1.text_input("LinkedIn Client ID")
            lsec = c2.text_input("LinkedIn Client secret", type="password")
            red = st.text_input("Redirect URI", redirect)
            if st.form_submit_button("Save sign-in settings", type="primary"):
                toml = auth.oidc_secrets_toml(red.replace(str(port), "{PORT}") if desktop else red,
                                              (gid, gsec) if gid else None, (oid_, osec) if oid_ else None,
                                              secrets.token_urlsafe(32), (lid, lsec) if lid else None)
                if desktop:
                    Path(os.environ["AUTHORSHAND_DATA_DIR"], "auth.toml").write_text(toml, encoding="utf-8")
                path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
                path.parent.mkdir(exist_ok=True)
                path.write_text(toml.replace("{PORT}", str(port)), encoding="utf-8")
                st.success("Saved. Close and reopen the app to activate the sign-in buttons.")
        st.caption("Client secrets are written to .streamlit/secrets.toml on this computer only. Sign-in also "
                   "needs the package Authlib (included in the desktop app).")

        st.markdown("#### E-mail for verification codes (official e-mail check)")
        st.markdown("""Author's Hand sends a 6-digit code to your official e-mail through an e-mail account you choose.
**Easiest — a Gmail account:** myaccount.google.com → *Security* → turn on *2-Step Verification* → search
*App passwords* → create one called “Author's Hand” → copy the 16-letter password. Then use server
`smtp.gmail.com`, port `587`, your Gmail address and that app password.
**Institution mail (Outlook / Office 365):** server `smtp.office365.com`, port `587` (ask IT if SMTP is allowed).""")
        cur = verify.load_smtp()
        with st.form("smtp"):
            c1, c2 = st.columns([3, 1])
            host = c1.text_input("SMTP server", cur.get("host", "smtp.gmail.com"))
            port = c2.number_input("Port", 1, 65535, int(cur.get("port") or 587))
            c1, c2 = st.columns(2)
            suser = c1.text_input("E-mail account (login)", cur.get("user", ""))
            spw = c2.text_input("App password", type="password", help="Kept in a private file on this computer.")
            if st.form_submit_button("Save e-mail settings", type="primary"):
                verify.save_smtp(host, port, suser, spw or cur.get("password", ""))
                st.success("Saved.")
        if cur.get("host"):
            test_to = st.text_input("Send a test e-mail to", value=user().get("contact_email") or "", key="smtp_test")
            if st.button("Send test e-mail") and test_to:
                try:
                    verify.send_code(test_to, "123456", "", cur)
                    st.success("Test e-mail sent (code 123456 is only a test).")
                except Exception as e:
                    st.error(f"Could not send: {e}")
        st.caption(f"Stored in {verify.smtp_path()} (readable only by your Windows user).")
