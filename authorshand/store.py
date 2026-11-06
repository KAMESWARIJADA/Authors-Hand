"""Persistent research workspace (SQLite): accounts → projects → folders → articles.

One researcher is identified by e-mail and can link ORCID, ResearchGate and
Zotero to the same account. Each project keeps its own folders, articles,
saved search (for auto-refresh), enabled add-ins and new-paper alerts.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

DEFAULT_DB = os.getenv("AUTHORSHAND_DB", str(Path.home() / ".authorshand" / "workspace.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  email TEXT PRIMARY KEY, name TEXT DEFAULT '', orcid TEXT DEFAULT '', researchgate TEXT DEFAULT '',
  zotero_user TEXT DEFAULT '', preferred_style TEXT DEFAULT 'apa', created REAL);
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, name TEXT, description TEXT DEFAULT '',
  topic_query TEXT DEFAULT '', citation_style TEXT DEFAULT 'apa', addins TEXT DEFAULT '[]',
  auto_refresh_hours REAL DEFAULT 24, last_refresh REAL DEFAULT 0, created REAL,
  UNIQUE(owner, name));
CREATE TABLE IF NOT EXISTS folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, name TEXT, created REAL,
  UNIQUE(project_id, name));
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, folder_id INTEGER, key TEXT,
  title TEXT, year INTEGER, venue TEXT, doi TEXT, data TEXT, text TEXT DEFAULT '', summary TEXT DEFAULT '',
  citations INTEGER DEFAULT 0, starred INTEGER DEFAULT 0, notes TEXT DEFAULT '', status TEXT DEFAULT 'to read',
  added REAL, checked REAL DEFAULT 0, UNIQUE(project_id, key));
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, account TEXT, created REAL, expires REAL);
CREATE TABLE IF NOT EXISTS review_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, database TEXT, query TEXT, filters TEXT,
  run_at REAL, n_results INTEGER, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS review_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, key TEXT, data TEXT, runs TEXT DEFAULT '[]',
  duplicate_of INTEGER, duplicate_reason TEXT DEFAULT '', decision TEXT DEFAULT 'unscreened',
  reason TEXT DEFAULT '', notes TEXT DEFAULT '', stage TEXT DEFAULT 'title/abstract', updated REAL,
  UNIQUE(project_id, key));
CREATE TABLE IF NOT EXISTS ratings (
  id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT, article_key TEXT, accuracy INTEGER, usefulness INTEGER,
  errors TEXT DEFAULT '', created REAL);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, key TEXT, data TEXT, reason TEXT,
  found REAL, seen INTEGER DEFAULT 0, UNIQUE(project_id, key));
"""


MIGRATIONS = [  # columns added after v1 (ALTER TABLE is skipped when the column exists)
    ("users", "password_hash", "TEXT DEFAULT ''"), ("users", "pw_salt", "TEXT DEFAULT ''"),
    ("users", "recovery_hash", "TEXT DEFAULT ''"), ("users", "providers", "TEXT DEFAULT '[]'"),
    ("users", "contact_email", "TEXT DEFAULT ''"), ("users", "gscholar_url", "TEXT DEFAULT ''"),
    ("users", "gscholar", "TEXT DEFAULT '{}'"), ("users", "prefs", "TEXT DEFAULT '{}'"),
    ("users", "last_login", "REAL DEFAULT 0"), ("users", "orcid_verified", "INTEGER DEFAULT 0"),
    ("articles", "tags", "TEXT DEFAULT ''"), ("projects", "settings", "TEXT DEFAULT '{}'"),
    ("users", "linkedin", "TEXT DEFAULT ''"), ("users", "official_email", "TEXT DEFAULT ''"),
    ("users", "official_verified", "REAL DEFAULT 0"),
]


def article_key(p: dict) -> str:
    from .text_utils import normalize_title
    return (p.get("doi") or "").lower() or "t:" + normalize_title(p.get("title", ""))[:120]


class Workspace:
    def __init__(self, path: str = DEFAULT_DB):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for table, col, decl in MIGRATIONS:
            cols = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.db.commit()

    # ----------------------------------------------------------------- users
    # The users.email column holds the ACCOUNT ID: an e-mail address, or "orcid:<iD>"
    # for accounts created with an ORCID iD only.
    def user(self, email: str) -> dict:
        email = email.strip().lower()
        row = self.db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row:
            self.db.execute("INSERT INTO users(email, created) VALUES (?,?)", (email, time.time()))
            self.db.commit()
            row = self.db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        d = dict(row)
        for k, default in (("prefs", {}), ("gscholar", {}), ("providers", [])):
            try:
                d[k] = json.loads(d.get(k) or json.dumps(default))
            except Exception:
                d[k] = default
        return d

    def find_user(self, identifier: str) -> dict | None:
        """Look an account up by e-mail, ORCID iD or account id."""
        ident = identifier.strip().lower()
        row = self.db.execute("SELECT email FROM users WHERE email=? OR (orcid<>'' AND lower(orcid)=?)"
                              " OR email=? OR (official_verified>0 AND lower(official_email)=?)",
                              (ident, ident, "orcid:" + ident, ident)).fetchone()
        return self.user(row["email"]) if row else None

    def update_user(self, email: str, **fields) -> dict:
        allowed = {"name", "orcid", "researchgate", "zotero_user", "preferred_style", "password_hash", "pw_salt",
                   "recovery_hash", "providers", "contact_email", "gscholar_url", "gscholar", "prefs", "last_login",
                   "orcid_verified", "linkedin", "official_email", "official_verified"}
        for k, v in fields.items():
            if k in allowed:
                if k in ("prefs", "gscholar", "providers") and not isinstance(v, str):
                    v = json.dumps(v)
                self.db.execute(f"UPDATE users SET {k}=? WHERE email=?",
                                (v if v is not None else "", email.lower()))
        self.db.commit()
        return self.user(email)

    def delete_user(self, email: str):
        """Delete an account and every project, folder, article, alert and review record it owns."""
        email = email.lower()
        for p in self.projects(email):
            self.delete_project(p["id"])
        self.db.execute("DELETE FROM sessions WHERE account=?", (email,))
        self.db.execute("DELETE FROM ratings WHERE account=?", (email,))
        self.db.execute("DELETE FROM users WHERE email=?", (email,))
        self.db.commit()

    # ---------------------------------------------------------- backup/restore
    def export_user(self, email: str) -> dict:
        email = email.lower()
        u = self.user(email)
        for k in ("password_hash", "pw_salt", "recovery_hash"):
            u.pop(k, None)
        out = {"format": "authorshand-backup", "version": 2, "exported": time.time(), "account": u, "projects": []}
        for p in self.projects(email):
            pid = p["id"]
            folders = self.folders(pid)
            fname = {f["id"]: f["name"] for f in folders}
            arts = []
            for a in self.articles(pid):
                arts.append({"folder": fname.get(a["folder_id"], "Inbox"), "paper": a["paper"], "text": a["text"],
                             "summary": a["summary"], "notes": a["notes"], "tags": a.get("tags", ""),
                             "status": a["status"], "starred": a["starred"]})
            out["projects"].append({
                "project": {k: p[k] for k in ("name", "description", "topic_query", "citation_style", "addins",
                                              "auto_refresh_hours", "settings")},
                "folders": [f["name"] for f in folders], "articles": arts,
                "review_runs": [dict(r) for r in self.db.execute("SELECT * FROM review_runs WHERE project_id=?", (pid,))],
                "review_records": [dict(r) for r in self.db.execute("SELECT * FROM review_records WHERE project_id=?",
                                                                    (pid,))]})
        return out

    def import_user(self, email: str, backup: dict) -> int:
        """Restore projects from a backup into this account (names get ' (restored)' if they clash)."""
        if backup.get("format") != "authorshand-backup":
            raise ValueError("Not an Author's Hand backup file")
        n = 0
        existing = {p["name"] for p in self.projects(email)}
        for pr in backup.get("projects", []):
            meta = pr["project"]
            name = meta["name"] + (" (restored)" if meta["name"] in existing else "")
            pid = self.create_project(email, name, meta.get("description", ""), meta.get("topic_query", ""),
                                      meta.get("citation_style", "apa"), meta.get("auto_refresh_hours", 24))
            self.update_project(pid, addins=meta.get("addins") or [], settings=meta.get("settings") or {})
            fmap = {f: self.add_folder(pid, f) for f in pr.get("folders", [])}
            for a in pr.get("articles", []):
                aid = self.add_article(pid, a["paper"], fmap.get(a["folder"]) or self.add_folder(pid, a["folder"]),
                                       a.get("text", ""))
                if aid:
                    self.update_article(aid, summary=a.get("summary") or "", notes=a.get("notes", ""),
                                        tags=a.get("tags", ""), status=a.get("status", "to read"),
                                        starred=a.get("starred", 0))
            runmap = {}
            for r in pr.get("review_runs", []):
                cur = self.db.execute("INSERT INTO review_runs(project_id,database,query,filters,run_at,n_results,note)"
                                      " VALUES (?,?,?,?,?,?,?)", (pid, r["database"], r["query"], r["filters"],
                                                                  r["run_at"], r["n_results"], r.get("note", "")))
                runmap[r["id"]] = cur.lastrowid
            for r in pr.get("review_records", []):
                runs = [runmap.get(x, x) for x in json.loads(r.get("runs") or "[]")]
                self.db.execute("INSERT OR IGNORE INTO review_records(project_id,key,data,runs,duplicate_reason,decision,"
                                "reason,notes,stage,updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (pid, r["key"], r["data"], json.dumps(runs), r.get("duplicate_reason", ""),
                                 r.get("decision", "unscreened"), r.get("reason", ""), r.get("notes", ""),
                                 r.get("stage", "title/abstract"), r.get("updated") or time.time()))
            n += 1
        self.db.commit()
        return n

    # -------------------------------------------------------------- projects
    def create_project(self, owner: str, name: str, description: str = "", topic_query: str = "",
                       citation_style: str = "apa", auto_refresh_hours: float = 24) -> int:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO projects(owner,name,description,topic_query,citation_style,auto_refresh_hours,created)"
            " VALUES (?,?,?,?,?,?,?)", (owner.lower(), name, description, topic_query, citation_style,
                                         auto_refresh_hours, time.time()))
        self.db.commit()
        pid = cur.lastrowid or self.db.execute("SELECT id FROM projects WHERE owner=? AND name=?",
                                               (owner.lower(), name)).fetchone()["id"]
        self.add_folder(pid, "Inbox")
        return pid

    def projects(self, owner: str) -> list[dict]:
        rows = self.db.execute("SELECT p.*, (SELECT COUNT(*) FROM articles a WHERE a.project_id=p.id) n_articles,"
                               " (SELECT COUNT(*) FROM alerts l WHERE l.project_id=p.id AND l.seen=0) n_alerts"
                               " FROM projects p WHERE owner=? ORDER BY created", (owner.lower(),)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["addins"] = json.loads(d.get("addins") or "[]")
            d["settings"] = json.loads(d.get("settings") or "{}")
            out.append(d)
        return out

    def project(self, pid: int) -> dict:
        d = dict(self.db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        d["addins"] = json.loads(d.get("addins") or "[]")
        d["settings"] = json.loads(d.get("settings") or "{}")
        return d

    def update_project(self, pid: int, **fields):
        allowed = {"name", "description", "topic_query", "citation_style", "auto_refresh_hours", "last_refresh", "addins",
                   "settings"}
        for k, v in fields.items():
            if k in allowed:
                self.db.execute(f"UPDATE projects SET {k}=? WHERE id=?",
                                (json.dumps(v) if k in ("addins", "settings") else v, pid))
        self.db.commit()

    def delete_project(self, pid: int):
        for t in ("articles", "folders", "alerts", "review_runs", "review_records"):
            self.db.execute(f"DELETE FROM {t} WHERE project_id=?", (pid,))
        self.db.execute("DELETE FROM projects WHERE id=?", (pid,))
        self.db.commit()

    # --------------------------------------------------------------- folders
    def add_folder(self, pid: int, name: str) -> int:
        self.db.execute("INSERT OR IGNORE INTO folders(project_id,name,created) VALUES (?,?,?)", (pid, name, time.time()))
        self.db.commit()
        return self.db.execute("SELECT id FROM folders WHERE project_id=? AND name=?", (pid, name)).fetchone()["id"]

    def folders(self, pid: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM articles a WHERE a.folder_id=f.id) n FROM folders f "
            "WHERE project_id=? ORDER BY created", (pid,)).fetchall()]

    def rename_folder(self, fid: int, name: str):
        self.db.execute("UPDATE folders SET name=? WHERE id=?", (name, fid))
        self.db.commit()

    def delete_folder(self, fid: int):
        row = self.db.execute("SELECT project_id FROM folders WHERE id=?", (fid,)).fetchone()
        if row:
            inbox = self.add_folder(row["project_id"], "Inbox")
            if inbox != fid:
                self.db.execute("UPDATE articles SET folder_id=? WHERE folder_id=?", (inbox, fid))
                self.db.execute("DELETE FROM folders WHERE id=?", (fid,))
        self.db.commit()

    # -------------------------------------------------------------- articles
    def add_article(self, pid: int, paper: dict, folder_id: int | None = None, text: str = "") -> int | None:
        folder_id = folder_id or self.add_folder(pid, "Inbox")
        key = article_key(paper)
        data = {k: v for k, v in paper.items() if k != "text"}
        from .evidence import initial_provenance, text_source
        data.setdefault("provenance", initial_provenance(paper))
        data["text_source"] = text_source(data, text or paper.get("text", ""))
        cur = self.db.execute(
            "INSERT OR IGNORE INTO articles(project_id,folder_id,key,title,year,venue,doi,data,text,citations,added)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, folder_id, key, paper.get("title", ""), paper.get("year"), paper.get("venue", ""),
             paper.get("doi", ""), json.dumps(data), text or paper.get("text", ""), paper.get("citations") or 0,
             time.time()))
        self.db.commit()
        return cur.lastrowid if cur.rowcount else None

    def articles(self, pid: int, folder_id: int | None = None) -> list[dict]:
        q, args = "SELECT * FROM articles WHERE project_id=?", [pid]
        if folder_id:
            q += " AND folder_id=?"
            args.append(folder_id)
        rows = self.db.execute(q + " ORDER BY starred DESC, year DESC, added DESC", args).fetchall()
        return [self._hydrate(r) for r in rows]

    def article(self, aid: int) -> dict:
        return self._hydrate(self.db.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone())

    @staticmethod
    def _hydrate(r) -> dict:
        d = dict(r)
        paper = json.loads(d.pop("data") or "{}")
        for k in ("title", "year", "venue", "doi"):
            if not paper.get(k) and d.get(k) not in (None, ""):
                paper[k] = d[k]
        paper["citations"] = d.get("citations") or paper.get("citations") or 0
        d["paper"] = paper
        d["summary"] = json.loads(d["summary"]) if d.get("summary") else None
        return d

    def update_article(self, aid: int, **fields):
        allowed = {"folder_id", "text", "summary", "citations", "starred", "notes", "status", "checked", "data", "tags"}
        for k, v in fields.items():
            if k in allowed:
                if k in ("summary", "data") and not isinstance(v, str):
                    v = json.dumps(v)
                self.db.execute(f"UPDATE articles SET {k}=? WHERE id=?", (v, aid))
        self.db.commit()

    def move_articles(self, ids: list[int], folder_id: int):
        self.db.executemany("UPDATE articles SET folder_id=? WHERE id=?", [(folder_id, i) for i in ids])
        self.db.commit()

    def delete_articles(self, ids: list[int]):
        self.db.executemany("DELETE FROM articles WHERE id=?", [(i,) for i in ids])
        self.db.commit()

    def has_article(self, pid: int, paper: dict) -> bool:
        return bool(self.db.execute("SELECT 1 FROM articles WHERE project_id=? AND key=?",
                                    (pid, article_key(paper))).fetchone())

    # ---------------------------------------------------------------- alerts
    def add_alert(self, pid: int, paper: dict, reason: str) -> bool:
        cur = self.db.execute("INSERT OR IGNORE INTO alerts(project_id,key,data,reason,found) VALUES (?,?,?,?,?)",
                              (pid, article_key(paper), json.dumps({k: v for k, v in paper.items() if k != "text"}),
                               reason, time.time()))
        self.db.commit()
        return bool(cur.rowcount)

    def alerts(self, pid: int, unseen_only: bool = True) -> list[dict]:
        rows = self.db.execute("SELECT * FROM alerts WHERE project_id=?" + (" AND seen=0" if unseen_only else "")
                               + " ORDER BY found DESC", (pid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["paper"] = json.loads(d.pop("data"))
            out.append(d)
        return out

    def mark_alerts_seen(self, ids: list[int]):
        self.db.executemany("UPDATE alerts SET seen=1 WHERE id=?", [(i,) for i in ids])
        self.db.commit()
