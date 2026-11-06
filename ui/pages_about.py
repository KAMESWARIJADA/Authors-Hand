"""About & feature status — what works inside the app, what is a link, what still needs live testing."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .common import APP, hero

STATUS = [
    # feature, how it works, status
    ("Sign up / sign in with e-mail (Gmail) or ORCID iD + password", "Built in", "Tested (automated tests)"),
    ("Continue with Google / ORCID (OpenID Connect)", "Live sign-in via st.login", "Needs your client IDs; not tested here"),
    ("Projects, folders, notes, tags, reading status, backup / restore / delete", "Built in", "Tested"),
    ("Structured summaries with evidence (section, page, DOI, support strength)", "Built in", "Tested on demo corpus"),
    ("Full text vs abstract-only labelling, PDF page check, scanned-page warning", "Built in", "Tested"),
    ("OCR for scanned pages", "Optional package (rapidocr-onnxruntime)", "Not installed by default"),
    ("Writing Studio: intro, LR, gaps, method, model, RQs, hypotheses, future work", "Built in", "Tested on demo corpus"),
    ("Editable comparison table, method corrections, field-specific terms", "Built in", "Tested"),
    ("Systematic review: protocol, logged searches, duplicates, screening, PRISMA, exports", "Built in",
     "Tested offline; live databases need a network test"),
    ("Citations: 9 built-in styles, editors/edition/pages, notes & tags in exports", "Built in", "Tested"),
    ("Any journal style (10,000+ CSL styles)", "Live API (doi.org)", "Implemented; needs a network test"),
    ("ORCID, OpenAlex, Semantic Scholar, arXiv, Crossref, Unpaywall search & import", "Live API",
     "Implemented and unit-tested on recorded formats; needs a network test"),
    ("Google Scholar metrics & graph", "SerpApi (your key) or manual entry; article import by file",
     "Manual + file import tested; SerpApi needs your key"),
    ("ResearchGate", "Profile link + your BibTeX/RIS export", "Tested (file import)"),
    ("My publications: one list from ORCID + OpenAlex + Scholar + ResearchGate exports, type, field, indexing "
     "(your lists), citations, co-authors, citation in any style, refresh",
     "Built in (data from the live sources above)", "Tested on demo data (automated + browser)"),
    ("Year-wise papers & charts, add missing papers / conference papers / cases by hand, my citation map "
     "(rebuilt on Refresh all)", "Built in; citation map uses OpenAlex live", "Tested on demo data"),
    ("Google Scholar: all articles on the profile", "SerpApi, 100 per page", "Paging logic tested offline; needs your key"),
    ("Official e-mail verification (6-digit code)", "Built in; sends via the e-mail account you set up (SMTP)",
     "Code logic tested; sending needs your mail settings"),
    ("LinkedIn", "Profile link; Continue with LinkedIn (OpenID Connect)", "Needs your LinkedIn app keys — LinkedIn "
     "does not allow apps to read connections or publications"),
    ("Auto-refresh (new and citing papers, citation counts, retractions)", "Live API (OpenAlex)",
     "Demo tested; live needs a network test"),
    ("Journal quality check", "Live APIs (OpenAlex, DOAJ, Crossref) + your lists", "Demo tested; live needs a network test"),
    ("Zotero push", "Live API (your key)", "Implemented; needs your key"),
    ("Litmaps, ResearchRabbit, Inciteful, Mendeley, EndNote, Overleaf", "File exchange (BibTeX / RIS)", "Tested (files)"),
    ("SciSpace, Connected Papers, Google Scholar, Consensus, scite, SJR …", "Opens the tool pre-filled", "Link only"),
    ("JANE, Elicit, journal finders, Paperpal, Writefull …", "Opens the tool", "Link only"),
    ("Windows desktop app", "Portable app with private Python", "Built; tested on Linux equivalent — confirm on Windows"),
    ("Android / Play Store", "Capacitor shell around the hosted app", "Kit provided; needs hosting + Play account"),
]


def page_about():
    hero(f"About {APP}", "What each feature does, how it connects, and how far it has been tested.")
    st.markdown(f"""**{APP}** is the capstone project for the *IIT Guwahati E&ICT Academy — Generative AI* programme
(Final Capstone Option 5: *Autonomous AI Research Agent – AI that summarises research papers*). It combines an
autonomous agent (plan → act → reflect), retrieval-augmented question answering, evidence-grounded summarisation and a
writing studio, anchored to the researcher's ORCID / ResearchGate / Google Scholar identity.""")
    st.markdown("#### Feature status")
    st.dataframe(pd.DataFrame(STATUS, columns=["Feature", "How it works", "Test status"]), hide_index=True,
                 width="stretch")
    st.markdown("<div class='warnbox'>Evaluation numbers in the app and report come from a small <b>synthetic</b> "
                "demo corpus unless you run Evaluation → Your real papers. Generated drafts must be checked and "
                "paraphrased before use.</div>", unsafe_allow_html=True)
