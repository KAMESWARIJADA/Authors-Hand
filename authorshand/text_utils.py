"""Light-weight NLP helpers (no heavy downloads needed)."""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have
having he her here hers herself him himself his how i if in into is it its itself just me more most
my myself no nor not now of off on once only or other our ours ourselves out over own same she should
so some such than that the their theirs them themselves then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your
yours yourself yourselves also however using used use based study paper research results result show
shows shown within among across via et al may might must one two three new many much well thus hence
""".split())

_ABBREVS = ("e.g.", "i.e.", "et al.", "fig.", "eq.", "vs.", "dr.", "mr.", "ms.", "no.", "al.", "etc.")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"(\[])")


def clean_text(text: str) -> str:
    text = text.replace("­", "")
    text = re.sub(r"-\n(\w)", r"\1", text)          # de-hyphenate line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(text: str, min_words: int = 5) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts: list[str] = []
    for piece in _SENT_RE.split(text):
        last = parts[-1].split()[-1].lower() if parts and parts[-1].split() else ""
        if parts and (last in _ABBREVS or parts[-1].lower().endswith("et al.")):
            parts[-1] = parts[-1] + " " + piece   # re-join after an abbreviation
        else:
            parts.append(piece)
    return [p.strip() for p in parts if len(p.split()) >= min_words]


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]+", text.lower())
            if w not in STOPWORDS and len(w) > 2]


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def tfidf_matrix(docs: list[str]):
    """Return (vectorizer, matrix). Uses scikit-learn."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    vec = TfidfVectorizer(stop_words=list(STOPWORDS), ngram_range=(1, 2),
                          sublinear_tf=True, min_df=1)
    mat = vec.fit_transform(docs if docs else [""])
    return vec, mat


def cosine_sim(a, b) -> np.ndarray:
    from sklearn.metrics.pairwise import cosine_similarity
    return cosine_similarity(a, b)


def textrank(sentences: list[str], top_n: int = 5, bias: Iterable[str] | None = None) -> list[str]:
    """Graph-based extractive ranking (TextRank on TF-IDF cosine graph).
    `bias` is an optional list of cue words that boosts sentences containing them.
    Returned sentences keep their original order (better readability)."""
    if not sentences:
        return []
    if len(sentences) <= top_n:
        return sentences
    import networkx as nx
    _, m = tfidf_matrix(sentences)
    sim = cosine_sim(m, m)
    np.fill_diagonal(sim, 0)
    g = nx.from_numpy_array(sim)
    try:
        scores = nx.pagerank(g, max_iter=200)
    except Exception:
        scores = {i: float(sim[i].sum()) for i in range(len(sentences))}
    bias = [b.lower() for b in (bias or [])]
    ranked = []
    for i, s in enumerate(sentences):
        boost = 1.0 + 0.6 * sum(1 for b in bias if b in s.lower())
        ranked.append((scores[i] * boost, i))
    keep = sorted(i for _, i in sorted(ranked, reverse=True)[:top_n])
    return [sentences[i] for i in keep]


def top_keywords(texts: list[str], k: int = 10) -> list[str]:
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return []
    vec, m = tfidf_matrix(texts)
    scores = np.asarray(m.sum(axis=0)).ravel()
    terms = vec.get_feature_names_out()
    order = scores.argsort()[::-1]
    out: list[str] = []
    for idx in order:
        t = terms[idx]
        if any(t in o or o in t for o in out):
            continue
        out.append(t)
        if len(out) >= k:
            break
    return out


def normalize_title(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()
