"""One-page, print-ready paper cheatsheets (PDF) in infographic layout."""
from __future__ import annotations

import io
import re
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Frame, KeepInFrame, Paragraph

from .citations import format_reference, md_to_html

NAVY = colors.HexColor("#0B1F33")
TEAL = colors.HexColor("#0F766E")
AMBER = colors.HexColor("#B45309")
INK = colors.HexColor("#13233A")
MUTED = colors.HexColor("#5B6B7F")
CARD = colors.HexColor("#F1F5F7")
TINT = colors.HexColor("#E6F2F1")
WARM = colors.HexColor("#FFF6EC")

BODY = ParagraphStyle("b", fontName="Helvetica", fontSize=8.6, leading=11, textColor=INK, alignment=TA_LEFT)
BUL = ParagraphStyle("u", parent=BODY, leftIndent=8, bulletIndent=0, spaceAfter=2)
HEAD = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=TEAL, spaceAfter=3)
TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=14.5, leading=17.5, textColor=colors.white)
SUB = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#CFE3E8"))
TLDR = ParagraphStyle("tl", parent=BODY, fontSize=9.6, leading=12.5)

LABELS = [("problem", "Research problem"), ("objectives", "Objectives"), ("methodology", "Methodology"),
          ("data", "Data & sample"), ("key_findings", "Key findings"), ("contributions", "Contributions"),
          ("limitations", "Limitations"), ("future_work", "Future research")]


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _headline(numbers: list[str]) -> tuple[str, str]:
    for s in numbers:
        m = re.search(r"(AUC|F1(?: score)?|Gini(?: coefficient)?|accuracy|recall)\D{0,20}?(\d?\.\d+)", s, re.I)
        if m:
            return m.group(2), m.group(1).split()[0].upper() if m.group(1).lower() in ("auc", "f1") else m.group(1).split()[0]
        m = re.search(r"(\d+(?:\.\d+)?)\s*(percent|%)", s)
        if m:
            words = re.sub(r"\s+", " ", s[:m.start()]).split()[-4:]
            return f"{m.group(1)}%", " ".join(words)[:38] or "headline effect"
    return "—", "headline result"


def _box(c, x, y, w, h, title, items, fill=CARD):
    c.setFillColor(fill)
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    story = [Paragraph(title.upper(), HEAD)]
    if isinstance(items, str):
        items = [items]
    items = [i for i in (items or []) if i] or ["Not reported in the paper."]
    story += [Paragraph(_esc(i), BUL, bulletText="•") for i in items]
    f = Frame(x + 6, y + 4, w - 12, h - 8, showBoundary=0, leftPadding=2, rightPadding=2, topPadding=4, bottomPadding=2)
    f.addFromList([KeepInFrame(w - 16, h - 12, story, mode="shrink")], c)


def draw_cheatsheet(c: canvas.Canvas, art: dict, style: str = "apa"):
    """`art` is a WritingStudio article profile (paper, csl, summary, methods, designs, sample, key_numbers…)."""
    W, H = A4
    M = 14 * mm
    s, p = art["summary"], art["paper"]
    fields = s["fields"]
    # header band
    c.setFillColor(NAVY)
    c.rect(0, H - 46 * mm, W, 46 * mm, stroke=0, fill=1)
    c.setFillColor(TEAL)
    c.circle(W - M - 6 * mm, H - 12 * mm, 4.2 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawCentredString(W - M - 6 * mm, H - 13 * mm, "AH")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(colors.HexColor("#8FB3BF"))
    c.drawString(M, H - 9 * mm, "PAPER CHEATSHEET · AUTHOR'S HAND")
    hdr = [Paragraph(_esc(p.get("title", "")), TITLE),
           Paragraph(_esc(", ".join(p.get("authors") or [])) + f" · {p.get('year') or ''} · <i>{_esc(p.get('venue', ''))}</i>", SUB)]
    Frame(M - 2, H - 45 * mm, W - 2 * M - 12 * mm, 33 * mm, showBoundary=0).addFromList(
        [KeepInFrame(W - 2 * M - 14 * mm, 31 * mm, hdr, mode="shrink")], c)
    y = H - 46 * mm - 6 * mm
    # TL;DR
    th = 15 * mm
    c.setFillColor(WARM)
    c.setStrokeColor(colors.HexColor("#F3C48C"))
    c.roundRect(M, y - th, W - 2 * M, th, 6, stroke=1, fill=1)
    Frame(M + 6, y - th + 2, W - 2 * M - 12, th - 4, showBoundary=0).addFromList(
        [KeepInFrame(W - 2 * M - 16, th - 6, [Paragraph("<b>TL;DR</b> — " + _esc(fields.get("tldr", "")), TLDR)],
                     mode="shrink")], c)
    y -= th + 5 * mm
    # stat tiles
    val, lab = _headline(art.get("key_numbers", []))
    tiles = [(val, lab), ((art.get("sample") or ["—"])[0].split(" ")[0], " ".join((art.get("sample") or ["— sample"])[0].split(" ")[1:])[:30]),
             ((art.get("designs") or ["—"])[0], "research design"), (art.get("family", "—"), "approach")]
    tw = (W - 2 * M - 3 * 4 * mm) / 4
    for i, (v, l) in enumerate(tiles):
        x = M + i * (tw + 4 * mm)
        c.setFillColor(TINT if i else colors.HexColor("#FDF1E3"))
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.roundRect(x, y - 19 * mm, tw, 19 * mm, 6, stroke=1, fill=1)
        from reportlab.pdfbase.pdfmetrics import stringWidth
        big = len(str(v)) <= 8
        fs = 17 if big else 10
        while fs > 6.5 and stringWidth(str(v), "Helvetica-Bold", fs) > tw - 8 * mm:
            fs -= 0.5
        c.setFillColor(AMBER if i == 0 else TEAL)
        c.setFont("Helvetica-Bold", fs)
        c.drawString(x + 4 * mm, y - (10 if big else 8.5) * mm, str(v))
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.2)
        c.drawString(x + 4 * mm, y - 15.5 * mm, str(l)[:42])
    y -= 19 * mm + 5 * mm
    # 2 x 4 grid of boxes
    bottom = 40 * mm
    gh = (y - bottom - 3 * 3 * mm) / 4
    gw = (W - 2 * M - 4 * mm) / 2
    order = [LABELS[i] for i in (0, 4, 1, 5, 2, 6, 3, 7)]
    for i, (k, t) in enumerate(order):
        col, row = i % 2, i // 2
        x = M + col * (gw + 4 * mm)
        yy = y - (row + 1) * gh - row * 3 * mm
        _box(c, x, yy, gw, gh, t, fields.get(k), fill=(TINT if k == "key_findings" else CARD))
    # footer: citation + keywords
    c.setFillColor(colors.white)
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.roundRect(M, 12 * mm, W - 2 * M, 25 * mm, 6, stroke=1, fill=1)
    ref = md_to_html(_esc(format_reference(art["csl"], style, 1)).replace("&amp;", "&amp;"))
    foot = [Paragraph(f"CITE ({style.upper()})", HEAD), Paragraph(ref, BODY),
            Paragraph(f"<font color='#5B6B7F'>Keywords: {_esc(', '.join(s.get('keywords', [])[:8]))} · "
                      f"Methods: {_esc(', '.join(art.get('methods', [])[:4]))} · Evidence support "
                      f"{s.get('faithfulness', 0):.2f}</font>", BODY)]
    Frame(M + 6, 13 * mm, W - 2 * M - 12, 23 * mm, showBoundary=0).addFromList(
        [KeepInFrame(W - 2 * M - 16, 21 * mm, foot, mode="shrink")], c)
    c.setFont("Helvetica", 6.5)
    c.setFillColor(MUTED)
    c.drawString(M, 7 * mm, f"Generated {date.today():%d %b %Y} by Author's Hand · verify against the original paper before citing")
    c.showPage()


def cheatsheet_pdf(arts: list[dict] | dict, style: str = "apa") -> bytes:
    """One page per article → PDF bytes."""
    if isinstance(arts, dict):
        arts = [arts]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Author's Hand cheatsheet")
    for a in arts:
        draw_cheatsheet(c, a, style)
    c.save()
    return buf.getvalue()
