"""Central configuration. Every value can be set through environment variables
(or a .env file) so that no secret is ever hard-coded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:  # optional: load a local .env file if python-dotenv is installed
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass


@dataclass
class Settings:
    # LLM: auto | anthropic | openai | groq | gemini | ollama | local
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "auto"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    temperature: float = 0.2
    # "Polite pool" e-mail for OpenAlex / Crossref / Unpaywall (recommended by them)
    contact_email: str = field(default_factory=lambda: os.getenv("CONTACT_EMAIL", ""))
    semantic_scholar_key: str = field(default_factory=lambda: os.getenv("S2_API_KEY", ""))
    http_timeout: int = 25
    # Demo mode runs fully offline on the bundled corpus in demo_data/
    demo_mode: bool = field(default_factory=lambda: os.getenv("AUTHORSHAND_DEMO", "0") == "1")
    # Summary quality gate used by the agent's self-reflection step
    min_faithfulness: float = 0.35
    max_agent_steps: int = 8
    chunk_size: int = 900
    chunk_overlap: int = 150

    @property
    def user_agent(self) -> str:
        mail = f" (mailto:{self.contact_email})" if self.contact_email else ""
        return f"AuthorsHand/1.0{mail}"
