import os
from rag.indexer import get_collection, embed_text


# Chunks with L2 distance above this value are considered off-topic and dropped.
# Lower = stricter. 1.0 works well for nomic-embed-text embeddings.
# Override via RAG_MAX_DISTANCE in .env if you need to tune.
_MAX_DISTANCE = float(os.getenv("RAG_MAX_DISTANCE", "1.0"))


def retrieve_context(query: str, lang: str = "en", n_results: int = 4) -> str:
    """
    Returns formatted context string from ChromaDB for a given query.

    - Filters by language so Finnish queries only get Finnish chunks.
    - Drops any chunk whose L2 distance exceeds RAG_MAX_DISTANCE.
    - Returns an empty string if no relevant chunk survives, which causes
      the NO_CONTEXT_NOTE to be injected in the generator prompt.
    """
    collection = get_collection()

    if collection.count() == 0:
        return ""

    query_embedding = embed_text(query)
    available = min(n_results, collection.count())

    # ── Try language-filtered query first ────────────────────────────────────
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
        pass  # ChromaDB where-filter can fail on empty collections — fall through

    # ── Fallback: no language filter (last resort) ────────────────────────────
    try:
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=available,
            include=["documents", "metadatas", "distances"],
        )
        filtered = _filter_by_distance(results)
        return _format_results(filtered)
    except Exception:
        return ""


def _filter_by_distance(results: dict) -> list[tuple[str, dict]]:
    """
    Zip docs, metas, and distances together and drop anything too far from
    the query. Returns a list of (doc, meta) tuples that passed the threshold.
    """
    docs      = results.get("documents", [[]])[0]
    metas     = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    kept = []
    for doc, meta, dist in zip(docs, metas, distances):
        if dist <= _MAX_DISTANCE:
            kept.append((doc, meta))

    return kept


def _format_results(pairs: list[tuple[str, dict]]) -> str:
    parts = []
    for doc, meta in pairs:
        source = meta.get("source", "unknown")
        parts.append(f"[Source: {source}]\n{doc}")
    return "\n\n---\n\n".join(parts)

