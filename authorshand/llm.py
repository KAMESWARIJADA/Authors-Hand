"""Provider-agnostic LLM wrapper built on LangChain chat models.

Author's Hand never *requires* a paid key: when no provider is configured it
falls back to `local` mode, where every component switches to its
extractive / statistical path. Supported providers (install the matching
langchain-* package):

    anthropic  -> langchain-anthropic    (ANTHROPIC_API_KEY)
    openai     -> langchain-openai       (OPENAI_API_KEY)
    groq       -> langchain-groq         (GROQ_API_KEY)  free tier available
    gemini     -> langchain-google-genai (GOOGLE_API_KEY) free tier available
    ollama     -> langchain-ollama       (local, free, no key)
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.0-flash",
    "ollama": "llama3.1",
}
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "gemini": "GOOGLE_API_KEY",
}


class LLM:
    def __init__(self, provider: str = "auto", model: str = "", temperature: float = 0.2,
                 api_key: str | None = None):
        self.provider = self._resolve(provider, api_key)
        self.model = model or DEFAULT_MODELS.get(self.provider, "")
        self.temperature = temperature
        self._api_key = api_key
        self._chat = None
        self.calls = 0
        self.total_latency = 0.0

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _resolve(provider: str, api_key: str | None) -> str:
        provider = (provider or "auto").lower()
        if provider != "auto":
            return provider
        for p, env in KEY_ENV.items():
            if os.getenv(env):
                return p
        if os.getenv("OLLAMA_HOST"):
            return "ollama"
        return "local"

    @property
    def available(self) -> bool:
        return self.provider != "local"

    @property
    def label(self) -> str:
        return "Local extractive engine (no LLM)" if not self.available else f"{self.provider}:{self.model}"

    def _get_chat(self):
        if self._chat is not None:
            return self._chat
        p, kw = self.provider, {"temperature": self.temperature}
        key = self._api_key
        if p == "anthropic":
            from langchain_anthropic import ChatAnthropic
            self._chat = ChatAnthropic(model=self.model, max_tokens=2048,
                                       **({"api_key": key} if key else {}), **kw)
        elif p == "openai":
            from langchain_openai import ChatOpenAI
            self._chat = ChatOpenAI(model=self.model, **({"api_key": key} if key else {}), **kw)
        elif p == "groq":
            from langchain_groq import ChatGroq
            self._chat = ChatGroq(model=self.model, **({"api_key": key} if key else {}), **kw)
        elif p == "gemini":
            from langchain_google_genai import ChatGoogleGenerativeAI
            self._chat = ChatGoogleGenerativeAI(model=self.model,
                                                **({"google_api_key": key} if key else {}), **kw)
        elif p == "ollama":
            from langchain_ollama import ChatOllama
            self._chat = ChatOllama(model=self.model, **kw)
        else:
            raise RuntimeError("No LLM provider configured (local mode).")
        return self._chat

    # --------------------------------------------------------------- calling
    def generate(self, prompt: str, system: str = "You are a meticulous research assistant.",
                 retries: int = 2) -> str:
        if not self.available:
            raise RuntimeError("LLM not available in local mode")
        from langchain_core.messages import HumanMessage, SystemMessage
        chat = self._get_chat()
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                t0 = time.time()
                resp = chat.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
                self.calls += 1
                self.total_latency += time.time() - t0
                content = resp.content
                if isinstance(content, list):  # some providers return content blocks
                    content = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
                return str(content)
            except Exception as e:  # network / rate-limit → back off and retry
                last_err = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"LLM call failed: {last_err}")

    def generate_json(self, prompt: str, system: str = "Return only valid JSON.") -> Any:
        raw = self.generate(prompt + "\n\nRespond with JSON only, no prose.", system=system)
        return parse_json(raw)


def parse_json(raw: str) -> Any:
    """Robustly pull the first JSON object/array out of a model response."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        s, e = raw.find(open_c), raw.rfind(close_c)
        if s != -1 and e > s:
            try:
                return json.loads(raw[s:e + 1])
            except Exception:
                continue
    raise ValueError("Model did not return valid JSON")
