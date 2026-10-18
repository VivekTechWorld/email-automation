"""
retriever.py — RAG Context Retriever
====================================
Knowledge comes from the dashboard-managed articles (knowledge.py).

Primary path : ChromaDB vector search (needs chromadb + Ollama embeddings),
               kept in sync with the articles by rag.indexer.
Fallback path: keyword (BM25-style) search over the same article chunks.

Results prefer chunks whose category matches the email's category, and the
total context is capped at RAG_CONTEXT_MAX_CHARS so prompts stay within the
model's limits no matter how large the knowledge base grows.
"""

import os
import re
import math
import logging
import threading
from collections import Counter

import knowledge

log = logging.getLogger(__name__)

try:
    from rag.indexer import vector_search, _CHROMA_AVAILABLE, _OLLAMA_AVAILABLE
    _VECTOR_AVAILABLE = _CHROMA_AVAILABLE and _OLLAMA_AVAILABLE
except Exception as e:
    log.warning("Vector search not available: %s. Using keyword retrieval.", e)
    _VECTOR_AVAILABLE = False

# Category match boosts; "general" articles are always relevant
_SAME_CATEGORY_BOOST = 1.6
_GENERAL_BOOST = 1.0
_OTHER_CATEGORY_BOOST = 0.75


def retrieve_context(query: str, lang: str = "en", n_results: int = 4, category: str | None = None) -> str:
    """
    Returns a formatted context string for the query, or "" when nothing relevant exists.
    """
    hits: list[dict] = []
    if _VECTOR_AVAILABLE:
        try:
            hits = vector_search(query, lang, n_results * 2)
        except Exception as e:
            log.warning("Vector RAG failed (%s). Falling back to keyword retrieval.", e)

    if not hits:
        hits = _keyword_search(query, lang, n_results * 2)

    hits = _rerank_by_category(hits, category)[:n_results]
    context = _format_within_budget(hits)
    log.info("RAG: %d chunk(s), %d chars for lang=%s category=%s", len(hits), len(context), lang, category)
    return context


def _rerank_by_category(hits: list[dict], category: str | None) -> list[dict]:
    def boost(h: dict) -> float:
        if category and h.get("category") == category:
            return _SAME_CATEGORY_BOOST
        if h.get("category") == "general":
            return _GENERAL_BOOST
        return _OTHER_CATEGORY_BOOST
    return sorted(hits, key=lambda h: h["score"] * boost(h), reverse=True)


def _format_within_budget(hits: list[dict]) -> str:
    budget = knowledge.limits()["context_max_chars"]
    parts, used = [], 0
    for h in hits:
        block = f"[Article: {h['title']} | {h['category']}]\n{h['text']}"
        if used + len(block) > budget:
            remaining = budget - used
            if remaining > 300:  # include a trimmed piece only if it is still useful
                parts.append(block[:remaining].rsplit("\n", 1)[0])
            break
        parts.append(block)
        used += len(block) + 7
    return "\n\n---\n\n".join(parts)


# ── Keyword search ────────────────────────────────────────────────────────────

_STOPWORDS = {
    # English
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "it", "this", "that", "i", "you", "we", "my", "your", "our",
    "me", "us", "can", "could", "would", "should", "do", "does", "did", "have", "has", "had",
    "not", "no", "yes", "please", "hi", "hello", "dear", "thanks", "thank", "regards", "from",
    "at", "by", "as", "if", "so", "what", "how", "when", "where", "why", "which", "who", "will",
    "there", "their", "they", "them", "about", "any", "all", "some", "get", "also", "just",
    "re", "fw", "fwd", "am", "pm", "best", "kind",
    # Finnish
    "ja", "on", "ei", "se", "että", "mutta", "tai", "kun", "jos", "niin", "kuin", "olen", "ole",
    "hei", "moi", "kiitos", "terveisin", "voi", "mitä", "miten", "miksi", "missä", "minä", "me",
}

_TOKEN_RE = re.compile(r"[a-zA-ZäöåÄÖÅ0-9]+")

_index_lock = threading.Lock()
_index: dict = {"version": -1, "chunks": [], "idf": {}}


def _tokenize(text: str) -> list[str]:
    tokens = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if len(tok) < 3 or tok in _STOPWORDS:
            continue
        # Cheap stemming so "domains"/"domain", "emails"/"email" match
        if len(tok) > 4 and tok.endswith("s"):
            tok = tok[:-1]
        tokens.append(tok)
    return tokens


def _get_index() -> tuple[list[dict], dict[str, float]]:
    """Chunk all articles once per knowledge-base version."""
    version = knowledge.get_version()
    with _index_lock:
        if _index["version"] == version:
            return _index["chunks"], _index["idf"]

        chunks = []
        for art in knowledge.all_articles_full():
            # Include the title in every chunk's terms so titles are searchable
            for text in knowledge.chunk_text(art["content"]):
                tokens = _tokenize(f"{art['title']} {text}")
                if tokens:
                    chunks.append({
                        "text": text,
                        "title": art["title"],
                        "category": art["category"],
                        "lang": art["lang"],
                        "tf": Counter(tokens),
                        "len": len(tokens),
                    })

        doc_freq: Counter = Counter()
        for ch in chunks:
            doc_freq.update(ch["tf"].keys())
        n = max(len(chunks), 1)
        idf = {term: math.log(1 + n / df) for term, df in doc_freq.items()}

        _index.update(version=version, chunks=chunks, idf=idf)
        log.info("Keyword index rebuilt: %d chunks (KB version %d)", len(chunks), version)
        return chunks, idf


def _keyword_search(query: str, lang: str, n_results: int) -> list[dict]:
    chunks, idf = _get_index()
    query_terms = set(_tokenize(query))
    if not chunks or not query_terms:
        return []

    min_score = float(os.getenv("KEYWORD_RAG_MIN_SCORE", "2.5"))

    def score(ch: dict) -> float:
        s = 0.0
        for term in query_terms:
            tf = ch["tf"].get(term)
            if tf:
                # BM25-style saturation so long chunks don't win just by size
                s += idf.get(term, 0.0) * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * ch["len"] / 80))
        return s

    def ranked(pool):
        scored = [(score(ch), ch) for ch in pool]
        return [
            {**{k: ch[k] for k in ("text", "title", "category", "lang")}, "score": s}
            for s, ch in sorted(scored, key=lambda p: p[0], reverse=True)
            if s >= min_score
        ][:n_results]

    hits = ranked([ch for ch in chunks if ch["lang"] == lang])
    # Nothing in the customer's language — try every language
    return hits or ranked(chunks)
