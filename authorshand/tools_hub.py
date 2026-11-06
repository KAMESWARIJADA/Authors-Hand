"""Add-in hub: the registry of research tools an author can attach to a project,
with stage-aware recommendations, pre-filled launch links, file exchange and
the Zotero Web API connection."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

import requests

REGISTRY = json.loads((Path(__file__).with_name("tools.json")).read_text(encoding="utf-8"))["tools"]
CATEGORIES = list(dict.fromkeys(t["category"] for t in REGISTRY))
CONNECTION_LABEL = {"builtin": "Built in", "api": "Live API", "deeplink": "Opens pre-filled",
                    "exchange": "File exchange"}
DEFAULT_ADDINS = ["openalex", "semanticscholar", "googlescholar", "citationmap", "litmaps", "connectedpapers",
                  "reader", "scispace", "studio", "zotero", "jane", "venuefit", "jqc", "sjr", "doaj",
                  "retraction", "gpower"]


def label(tool: dict) -> str:
    if tool["connection"] == "deeplink" and not tool.get("search"):
        return "Opens tool"
    return CONNECTION_LABEL[tool["connection"]]


def get(tool_id: str) -> dict:
    return next(t for t in REGISTRY if t["id"] == tool_id)


def for_stage(stage: str, enabled: list[str] | None = None) -> list[dict]:
    tools = [t for t in REGISTRY if stage in t.get("stages", [])]
    if enabled is not None:
        tools = [t for t in tools if t["id"] in enabled]
    order = {"builtin": 0, "api": 1, "deeplink": 2, "exchange": 3}
    return sorted(tools, key=lambda t: order.get(t["connection"], 9))


def launch_url(tool: dict, query: str = "", doi: str = "") -> str:
    """Pre-filled URL when the tool supports it, else the tool's home page."""
    q = doi or query
    if tool.get("search") and q:
        return tool["search"].format(q=quote_plus(q))
    return tool.get("url", "")


# ----------------------------------------------------------------- Zotero API
def _zotero_item(r: dict) -> dict:
    typ = {"article-journal": "journalArticle", "chapter": "bookSection", "book": "book",
           "paper-conference": "conferencePaper", "report": "report", "thesis": "thesis"}.get(r.get("type"), "journalArticle")
    creators = [{"creatorType": "author", "firstName": a.get("given", ""), "lastName": a.get("family", "")}
                for a in r.get("author", [])]
    creators += [{"creatorType": "editor", "firstName": a.get("given", ""), "lastName": a.get("family", "")}
                 for a in r.get("editor", [])]
    dp = (r.get("issued") or {}).get("date-parts") or [[None]]
    item = {"itemType": typ, "title": r.get("title", ""), "creators": creators,
            "date": str(dp[0][0] or ""), "DOI": r.get("DOI", ""), "url": r.get("URL", ""),
            "volume": r.get("volume", ""), "pages": r.get("page", ""), "publisher": r.get("publisher", "")}
    if typ == "journalArticle":
        item.update({"publicationTitle": r.get("container-title", ""), "issue": r.get("issue", "")})
    elif typ == "bookSection":
        item.update({"bookTitle": r.get("container-title", ""), "place": r.get("publisher-place", ""),
                     "edition": r.get("edition", "")})
    elif typ == "conferencePaper":
        item.update({"proceedingsTitle": r.get("container-title", "")})
    if typ == "thesis":
        item.pop("volume", None)
    return {k: v for k, v in item.items() if v not in ("", None)}


def zotero_push(user_id: str, api_key: str, recs: list[dict], collection_key: str = "") -> dict:
    """Create items in a Zotero user library (Zotero Web API v3, 50 items per call)."""
    url = f"https://api.zotero.org/users/{user_id}/items"
    headers = {"Zotero-API-Key": api_key, "Zotero-API-Version": "3", "Content-Type": "application/json"}
    created, failed = 0, 0
    for i in range(0, len(recs), 50):
        items = [_zotero_item(r) for r in recs[i:i + 50]]
        if collection_key:
            for it in items:
                it["collections"] = [collection_key]
        r = requests.post(url, headers=headers, data=json.dumps(items), timeout=30)
        r.raise_for_status()
        res = r.json()
        created += len(res.get("successful", {}))
        failed += len(res.get("failed", {}))
    return {"created": created, "failed": failed}
