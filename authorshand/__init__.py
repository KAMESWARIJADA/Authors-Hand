"""
Author's Hand — an Autonomous AI Research Agent.

Identity-anchored research copilot: it links a researcher's ORCID iD (and
ResearchGate profile), builds a unified publication profile from open
scholarly sources, and autonomously finds, reads, summarises, cross-examines
and reviews research papers — with every summary sentence traced back to
evidence in the source paper.
"""

__version__ = "1.0.0"

from .config import Settings
from .llm import LLM
from .pdf_reader import read_pdf, split_sections
from .summarizer import PaperSummarizer
from .rag import PaperIndex
from .profile import ResearcherProfile
from .agent import ResearchAgent
from .litreview import LiteratureReviewer
from . import evaluation, exporters, connectors, demo

__all__ = [
    "Settings", "LLM", "read_pdf", "split_sections", "PaperSummarizer",
    "PaperIndex", "ResearcherProfile", "ResearchAgent", "LiteratureReviewer",
    "evaluation", "exporters", "connectors", "demo",
]
