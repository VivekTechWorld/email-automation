"""
retriever.py — RAG Context Retriever (ChromaDB optional)
=========================================================
When ChromaDB / Ollama embeddings are unavailable (e.g. Windows without
Visual C++ build tools), this module gracefully returns an empty string.
The generator will then use the NO_CONTEXT_NOTE prompt path, telling
Gemini to acknowledge the email and say the team will follow up.
"""

import os
import logging

log = logging.getLogger(__name__)

# Detect whether ChromaDB is available at import time
try:
    from rag.indexer import get_collection, embed_text
    _RAG_AVAILABLE = True
except Exception as e:
    log.warning("RAG/ChromaDB not available on this platform: %s. Continuing without RAG.", e)
    _RAG_AVAILABLE = False

_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "1.0"))


def retrieve_context(query: str, lang: str = "en", n_results: int = 4) -> str:
    """
    Returns a formatted context string from ChromaDB.

    If ChromaDB is unavailable (Windows build error) or the collection is empty,
    returns "" which triggers the graceful NO_CONTEXT_NOTE fallback in generator.py.
    Gemini will then write a polite acknowledgement reply without inventing facts.
    """
    if not _RAG_AVAILABLE:
        return ""

    try:
        collection = get_collection()
        if collection.count() == 0:
            return ""

        query_embedding = embed_text(query)
        available = min(n_results, collection.count())

        # Try language-filtered query first
        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=available,
                where={"lang": lang},
                include=["documents", "metadatas", "distances"],
            )
            filtered = _filter_by_distance(results)
            if filtered:
                return _format_results(filtered)
        except Exception:
            pass

        # Fallback: no language filter
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=available,
            include=["documents", "metadatas", "distances"],
        )
        filtered = _filter_by_distance(results)
        return _format_results(filtered)

    except Exception as e:
        log.warning("RAG retrieval failed: %s. Returning empty context.", e)
        return ""


def _filter_by_distance(results: dict) -> list[tuple[str, dict]]:
    docs      = results.get("documents", [[]])[0]
    metas     = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]
    return [
        (doc, meta)
        for doc, meta, dist in zip(docs, metas, distances)
        if dist <= _MAX_DISTANCE
    ]


def _format_results(pairs: list[tuple[str, dict]]) -> str:
    parts = []
    for doc, meta in pairs:
        source = meta.get("source", "unknown")
        parts.append(f"[Source: {source}]\n{doc}")
    return "\n\n---\n\n".join(parts)
