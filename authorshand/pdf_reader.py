"""PDF / text ingestion and section segmentation for research papers."""
from __future__ import annotations

import io
import re
from collections import OrderedDict

from .text_utils import clean_text

# canonical section -> heading variants seen in research papers
SECTION_ALIASES = OrderedDict([
    ("abstract", ["abstract", "summary"]),
    ("introduction", ["introduction", "background", "motivation"]),
    ("literature", ["literature review", "related work", "related works", "prior work",
                    "theoretical background", "theoretical framework", "review of literature",
                    "hypotheses development", "conceptual framework"]),
    ("methodology", ["methodology", "methods", "method", "research design", "materials and methods",
                     "proposed method", "proposed approach", "approach", "model", "experimental setup",
                     "research methodology"]),
    ("data", ["data", "dataset", "datasets", "data collection", "sample", "data and sample"]),
    ("results", ["results", "findings", "experiments", "evaluation", "analysis",
                 "results and analysis", "empirical results", "experimental results"]),
    ("discussion", ["discussion", "implications", "managerial implications",
                    "practical implications", "theoretical implications", "results and discussion"]),
    ("limitations", ["limitations", "limitations and future research", "threats to validity"]),
    ("future_work", ["future work", "future research", "future directions"]),
    ("conclusion", ["conclusion", "conclusions", "concluding remarks", "conclusion and future work"]),
    ("references", ["references", "bibliography", "works cited", "acknowledgements", "acknowledgments"]),
])

_HEADING = re.compile(
    r"^\s*(?:(?:\d{1,2}|[IVX]{1,4})(?:\.\d{1,2})*\.?\s+)?([A-Za-z][A-Za-z &\-]{2,60}?)\s*:?\s*$")


def read_pdf(source) -> str:
    """Extract text from a PDF path, bytes or file-like object."""
    from pypdf import PdfReader
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    reader = PdfReader(source)
    pages = [(p.extract_text() or "") for p in reader.pages]
    return clean_text("\n".join(pages))


def _canonical(heading: str) -> str | None:
    h = heading.lower().strip(" .:")
    for canon, variants in SECTION_ALIASES.items():
        if h in variants:
            return canon
    return None


def split_sections(text: str) -> "OrderedDict[str, str]":
    """Split a paper into canonical sections. Text before the first heading is
    kept as `front_matter` (title/authors) and the abstract is detected even when
    written inline ("Abstract: ..."). References are dropped."""
    text = clean_text(text)
    sections: "OrderedDict[str, list[str]]" = OrderedDict()
    current = "front_matter"
    sections[current] = []
    for line in text.splitlines():
        inline = re.match(r"^\s*(abstract)\s*[:\-—]\s*(.+)$", line, flags=re.I)
        if inline:
            current = "abstract"
            sections.setdefault(current, []).append(inline.group(2))
            continue
        m = _HEADING.match(line)
        canon = _canonical(m.group(1)) if m and len(line.split()) <= 7 else None
        if canon:
            current = canon
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    out: "OrderedDict[str, str]" = OrderedDict()
    for k, lines in sections.items():
        body = re.sub(r"\s+", " ", " ".join(lines)).strip()
        if body and k != "references":
            out[k] = body
    if not [k for k in out if k != "front_matter"]:  # unstructured text → single body
        out = OrderedDict([("body", re.sub(r"\s+", " ", text))])
    return out


def guess_title(text: str) -> str:
    """Title = leading lines up to the author line / abstract (titles often wrap in PDFs)."""
    parts: list[str] = []
    for line in text.strip().splitlines()[:8]:
        line = line.strip()
        if not line:
            if parts:
                break
            continue
        if (re.search(r"\b[A-Z]\.\s?[A-Z]", line) or line.lower().startswith(("abstract", "http", "["))
                or "@" in line):
            break
        parts.append(line)
        if len(" ".join(parts).split()) > 30:
            break
    title = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return title if 3 <= len(title.split()) <= 35 else "Untitled paper"
