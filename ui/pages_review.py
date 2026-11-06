"""Systematic / scoping review: protocol → logged searches → de-duplication → screening → PRISMA → exports."""
from __future__ import annotations

import io
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from authorshand import connectors
from authorshand import review as R

from .common import (copy_box, current_settings, demo_banner, hero, need_project, stat_row, workspace)


def page_review():
    hero("Systematic review", "A reproducible review: every search, duplicate and screening decision is recorded "
         "and exportable (PRISMA 2020 style).")
    demo_banner()
    p = need_project()
    if not p:
        return
    ws = workspace()
    sett = dict(p.get("settings") or {})
    proto = sett.get("protocol") or {"review_type": R.REVIEW_TYPES[0], "question": "", "inclusion": "",
                                     "exclusions": R.DEFAULT_EXCLUSIONS, "filters": {}, "databases": R.DATABASES[:3]}
    t1, t2, t3, t4, t5 = st.tabs(["1 · Protocol", "2 · Search & log", "3 · Screening", "4 · PRISMA flow", "5 · Export"])

    with t1:
        with st.form("protocol"):
            c1, c2 = st.columns([1, 2])
            rtype = c1.selectbox("Review type", R.REVIEW_TYPES, index=R.REVIEW_TYPES.index(proto["review_type"])
                                 if proto["review_type"] in R.REVIEW_TYPES else 0)
            q = c2.text_input("Review question", proto.get("question", ""),
                              placeholder="e.g. How do explainable ML models affect HR decisions?")
            inc = st.text_area("Inclusion criteria", proto.get("inclusion", ""), height=80,
                               placeholder="Empirical studies; organisational setting; published 2015–2026; English")
            exc = st.text_area("Exclusion reasons (one per line — used as the screening dropdown)",
                               "\n".join(proto.get("exclusions") or R.DEFAULT_EXCLUSIONS), height=150)
            c1, c2, c3 = st.columns(3)
            f = proto.get("filters") or {}
            yf = c1.number_input("From year", 0, 2100, int(f.get("year_from") or 0), help="0 = no limit")
            yt = c2.number_input("To year", 0, 2100, int(f.get("year_to") or 0), help="0 = no limit")
            oa = c3.checkbox("Open access only", value=bool(f.get("oa_only")))
            dbs = st.multiselect("Databases", R.DATABASES, default=proto.get("databases") or R.DATABASES[:3])
            if st.form_submit_button("Save protocol", type="primary"):
                proto = {"review_type": rtype, "question": q, "inclusion": inc,
                         "exclusions": [x.strip() for x in exc.splitlines() if x.strip()],
                         "exclusion_text": "; ".join(x.strip() for x in exc.splitlines() if x.strip()),
                         "filters": {"year_from": yf or None, "year_to": yt or None, "oa_only": oa},
                         "databases": dbs, "saved": datetime.now().isoformat(timespec="minutes")}
                sett["protocol"] = proto
                ws.update_project(p["id"], settings=sett)
                st.success("Protocol saved — it is part of the exported review record.")

    with t2:
        q = st.text_input("Search string", value=p.get("topic_query", ""),
                          help="Use the same string for every database so the search is reproducible.")
        n = st.slider("Results per database", 5, 100, 25)
        if st.button("Run and log search", type="primary") and q:
            with st.spinner("Searching and logging…"):
                logs = R.run_search(ws, p["id"], proto.get("databases") or R.DATABASES[:3], q,
                                    proto.get("filters") or {}, n, current_settings(), st.session_state.demo_mode)
            for l in logs:
                st.caption(f"{l['database']}: {l['results']} results {('— ' + l['note']) if l['note'] else ''}")
        with st.expander("Import records exported from Scopus, Web of Science, PubMed, Litmaps … (BibTeX / RIS)"):
            src = st.text_input("Database name", "Scopus")
            fu = st.file_uploader("Export file", type=["bib", "ris", "txt"], key="revimp")
            if fu and st.button("Import as a logged search"):
                recs = connectors.import_references(fu.read().decode("utf-8", "ignore"), src)
                R.import_records(ws, p["id"], recs, src)
                st.success(f"Logged {len(recs)} records from {src}.")
        runs = R.runs(ws, p["id"])
        if runs:
            st.markdown("**Search log**")
            st.dataframe(pd.DataFrame([{"date": datetime.fromtimestamp(r["run_at"]).strftime("%d %b %Y %H:%M"),
                                        "database": r["database"], "query": r["query"],
                                        "filters": r["filters"], "results": r["n_results"], "note": r["note"]}
                                       for r in runs]), hide_index=True, width="stretch")
            dl = R.duplicate_log(ws, p["id"])
            st.markdown(f"**Duplicate removal log** ({len(dl)} entries)")
            if len(dl):
                st.dataframe(dl, hide_index=True, width="stretch")

    with t3:
        df = R.screening_table(ws, p["id"])
        if not len(df):
            st.info("Run a search first.")
        else:
            c = R.prisma_counts(ws, p["id"])
            stat_row([(c["screened"], "records to screen"), (c["included"], "included"), (c["excluded"], "excluded"),
                      (c["maybe"], "maybe"), (c["unscreened"], "not yet screened")])
            show = st.radio("Show", ["Not yet screened", "All", "Included", "Excluded", "Maybe"], horizontal=True)
            view = df if show == "All" else df[df["decision"] == {"Not yet screened": "unscreened", "Included": "include",
                                                                  "Excluded": "exclude", "Maybe": "maybe"}[show]]
            ed = st.data_editor(view, hide_index=True, width="stretch", key=f"scr_{show}",
                                column_config={"id": None,
                                               "decision": st.column_config.SelectboxColumn(
                                                   "Decision", options=["unscreened", "include", "exclude", "maybe"]),
                                               "reason": st.column_config.SelectboxColumn(
                                                   "Exclusion reason", options=[""] + (proto.get("exclusions") or [])),
                                               "abstract": st.column_config.TextColumn("Abstract", width="large")},
                                disabled=["title", "year", "venue", "doi", "found in", "abstract"])
            if st.button("Save screening decisions", type="primary"):
                for _, row in ed.iterrows():
                    orig = view[view["id"] == row["id"]].iloc[0]
                    if (row["decision"], row["reason"], row["notes"], row["stage"]) != \
                            (orig["decision"], orig["reason"], orig["notes"], orig["stage"]):
                        if row["decision"] == "exclude" and not row["reason"]:
                            st.warning(f"Give a reason for excluding: {row['title'][:60]}")
                            continue
                        R.set_decision(ws, int(row["id"]), row["decision"], row["reason"] or "", row["notes"] or "",
                                       row["stage"] or "")
                st.success("Saved.")
                st.rerun()
            folders = {f["name"]: f["id"] for f in ws.folders(p["id"])}
            if st.button("➕ Add all INCLUDED studies to the project (folder “Included studies”)"):
                fid = ws.add_folder(p["id"], "Included studies")
                k = 0
                for r in R.records(ws, p["id"]):
                    if r["decision"] == "include":
                        k += bool(ws.add_article(p["id"], dict(r["paper"], source=r["paper"].get("found_in", "Review search")),
                                                 fid, r["paper"].get("text", "")))
                st.success(f"Added {k} included studies.")

    with t4:
        c = R.prisma_counts(ws, p["id"])
        st.graphviz_chart(R.prisma_dot(c), width="stretch")
        st.json(c, expanded=False)

    with t5:
        para = R.methods_paragraph(ws, p["id"], proto)
        st.markdown("**Search-strategy paragraph for your Methods section** (edit before use)")
        copy_box(para, "Methods paragraph")
        bundle = R.export_bundle(ws, p["id"], proto)
        scr = R.screening_table(ws, p["id"])
        buf = io.BytesIO()
        with pd.ExcelWriter(buf) as xw:
            scr.to_excel(xw, "Screening", index=False)
            pd.DataFrame(R.runs(ws, p["id"])).to_excel(xw, "Search log", index=False)
            R.duplicate_log(ws, p["id"]).to_excel(xw, "Duplicates", index=False)
            pd.DataFrame([{"field": k, "value": json.dumps(v) if isinstance(v, (dict, list)) else v}
                          for k, v in proto.items()]).to_excel(xw, "Protocol", index=False)
        c1, c2, c3 = st.columns(3)
        c1.download_button("⬇ Review workbook (Excel)", buf.getvalue(), "review_record.xlsx", type="primary")
        c2.download_button("⬇ Screening table (CSV)", scr.to_csv(index=False), "screening.csv")
        c3.download_button("⬇ Full review record (JSON)", json.dumps(bundle, indent=1, default=str), "review_record.json")
