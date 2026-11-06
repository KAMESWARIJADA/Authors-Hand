"""Chat-with-paper: Retrieval-Augmented Generation over one or many papers.

Retrieval is hybrid: TF-IDF (lexical, always available) optionally fused with
dense sentence-transformer embeddings when that package is installed
(Reciprocal Rank Fusion). Answers cite the chunks they used: [S1], [S2] …
"""
from __future__ import annotations

import numpy as np

from .llm import LLM
from .pdf_reader import split_sections
from .text_utils import cosine_sim, split_sentences, tfidf_matrix


class PaperIndex:
    def __init__(self, llm: LLM | None = None, chunk_size: int = 900, overlap: int = 150,
                 use_embeddings: bool = True):
        self.llm = llm or LLM("local")
        self.chunk_size, self.overlap = chunk_size, overlap
        self.chunks: list[dict] = []
        self._vec = self._mat = None
        self._emb_model = self._emb = None
        self.use_embeddings = use_embeddings

    # --------------------------------------------------------------- indexing
    def add_paper(self, text: str, title: str = "paper", paper_id: str | None = None):
        pid = paper_id or title
        for section, body in split_sections(text).items():
            if section == "front_matter":      # title/author block carries no answers
                continue
            for chunk in self._chunk(body):
                self.chunks.append({"paper": title, "paper_id": pid, "section": section, "text": chunk})
        self._build()
        return self

    def _chunk(self, body: str) -> list[str]:
        sents, chunks, cur = split_sentences(body, min_words=3), [], ""
        for s in sents:
            if len(cur) + len(s) > self.chunk_size and cur:
                chunks.append(cur.strip())
                cur = cur[-self.overlap:] + " " + s       # sliding overlap keeps context
            else:
                cur += " " + s
        if cur.strip():
            chunks.append(cur.strip())
        return chunks or ([body] if body.strip() else [])

    def _build(self):
        # title + section are indexed with each chunk so questions that name a study
        # ("the credit scoring study") or a section ("limitations") route correctly
        docs = [f"{c['paper']} {c['section']} {c['section']} {c['text']}" for c in self.chunks]
        self._vec, self._mat = tfidf_matrix(docs)
        if self.use_embeddings:
            try:
                from sentence_transformers import SentenceTransformer
                if self._emb_model is None:
                    self._emb_model = SentenceTransformer("all-MiniLM-L6-v2")
                self._emb = self._emb_model.encode(docs, normalize_embeddings=True)
            except Exception:
                self._emb = None

    # -------------------------------------------------------------- retrieval
    def retrieve(self, question: str, k: int = 4) -> list[dict]:
        if not self.chunks:
            return []
        lex = cosine_sim(self._vec.transform([question]), self._mat).ravel()
        rankings = [lex.argsort()[::-1]]
        if self._emb is not None:
            q = self._emb_model.encode([question], normalize_embeddings=True)
            rankings.append((self._emb @ q.T).ravel().argsort()[::-1])
        rrf = np.zeros(len(self.chunks))                 # Reciprocal Rank Fusion
        for r in rankings:
            for rank, idx in enumerate(r):
                rrf[idx] += 1.0 / (60 + rank)
        top = rrf.argsort()[::-1][:k]
        return [dict(self.chunks[i], score=round(float(lex[i]), 3), rank=n + 1) for n, i in enumerate(top)]

    # ------------------------------------------------------------- answering
    def ask(self, question: str, k: int = 4) -> dict:
        hits = self.retrieve(question, k)
        if not hits:
            return {"answer": "No document indexed yet.", "sources": []}
        if self.llm.available:
            ctx = "\n\n".join(f"[S{h['rank']}] ({h['paper']} – {h['section']}) {h['text']}" for h in hits)
            try:
                ans = self.llm.generate(
                    "Answer the question using ONLY the sources. Cite sources inline like [S1]. "
                    "If the sources do not contain the answer, say 'The paper does not report this.'\n\n"
                    f"SOURCES:\n{ctx}\n\nQUESTION: {question}")
                return {"answer": ans, "sources": hits, "engine": self.llm.label}
            except Exception:
                pass
        # local extractive answer: best-matching sentences inside retrieved chunks
        ql = question.lower()
        cands = [(s, h["rank"], h["section"].replace("_", " ") in ql or
                  (h["section"] == "results" and any(w in ql for w in ("finding", "result", "how much", "what")))
                  ) for h in hits for s in split_sentences(h["text"], min_words=4)]
        if not cands:
            return {"answer": hits[0]["text"], "sources": hits, "engine": "local"}
        vec, m = tfidf_matrix([c for c, _, _ in cands] + [question])
        sims = cosine_sim(m[-1], m[:-1]).ravel()
        sims = sims + np.array([0.15 if sec else 0.0 for _, _, sec in cands])   # section-intent boost
        best = [i for i in sims.argsort()[::-1][:2] if sims[i] > 0.02]
        if not best:
            return {"answer": "The paper does not appear to report this.", "sources": hits, "engine": "local"}
        ans = " ".join(f"{cands[i][0]} [S{cands[i][1]}]" for i in sorted(best))
        return {"answer": ans, "sources": hits, "engine": "local"}
