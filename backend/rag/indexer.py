"""
indexer.py — ChromaDB vector index for the knowledge base (optional)
=====================================================================
Indexes the dashboard-managed articles (knowledge.py) into ChromaDB when
chromadb + Ollama embeddings are installed. Without them every function is a
no-op and the retriever uses keyword search instead.
"""

import os
import hashlib
import logging
import threading

log = logging.getLogger(__name__)

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import chromadb as _chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _chromadb = None
    _CHROMA_AVAILABLE = False
    log.info("chromadb not installed — vector search disabled (keyword search is used).")

try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    _ollama = None
    _OLLAMA_AVAILABLE = False
    log.info("ollama not installed — embeddings disabled.")

_COLLECTION = "knowledge_base"
_reindex_lock = threading.Lock()


def _client():
    return _chromadb.PersistentClient(path=os.getenv("CHROMA_PERSIST_DIR", "../data/chroma_db"))


def get_collection():
    if not _CHROMA_AVAILABLE:
        raise RuntimeError("chromadb is not installed. Vector search is disabled.")
    return _client().get_or_create_collection(name=_COLLECTION, metadata={"hnsw:space": "cosine"})


def embed_text(text: str) -> list[float]:
    if not _OLLAMA_AVAILABLE:
        raise RuntimeError("ollama is not installed. Embeddings disabled.")
    response = _ollama.embeddings(model=os.getenv("EMBED_MODEL", "nomic-embed-text"), prompt=text)
    return response["embedding"]


def reindex_all() -> int:
    """Rebuild the vector index from all knowledge-base articles. Returns chunk count."""
    if not (_CHROMA_AVAILABLE and _OLLAMA_AVAILABLE):
        return 0
    import knowledge

    with _reindex_lock:
        client = _client()
        try:
            client.delete_collection(_COLLECTION)
        except Exception:
            pass
        collection = get_collection()

        total = 0
        for art in knowledge.all_articles_full():
            for i, chunk in enumerate(knowledge.chunk_text(art["content"])):
                collection.upsert(
                    ids=[hashlib.md5(f"{art['id']}::{i}".encode()).hexdigest()],
                    embeddings=[embed_text(f"{art['title']}\n{chunk}")],
                    documents=[chunk],
                    metadatas=[{
                        "article_id": art["id"],
                        "title": art["title"],
                        "category": art["category"],
                        "lang": art["lang"],
                    }],
                )
                total += 1
        log.info("Vector index rebuilt with %d chunks.", total)
        return total


def reindex_in_background():
    """Called after every knowledge-base change; never blocks the request."""
    if not (_CHROMA_AVAILABLE and _OLLAMA_AVAILABLE):
        return

    def run():
        try:
            reindex_all()
        except Exception as e:
            log.warning("Background vector reindex failed: %s", e)

    threading.Thread(target=run, daemon=True).start()


def vector_search(query: str, lang: str, n_results: int) -> list[dict]:
    """Returns hits as dicts with text/title/category/lang/score (higher is better)."""
    collection = get_collection()
    count = collection.count()
    if count == 0:
        return []

    max_distance = float(os.getenv("RAG_MAX_DISTANCE", "1.0"))
    embedding = embed_text(query)

    def run(where):
        kwargs = dict(
            query_embeddings=[embedding],
            n_results=min(n_results, count),
            include=["documents", "metadatas", "distances"],
        )
        if where:
            kwargs["where"] = where
        res = collection.query(**kwargs)
        return [
            {
                "text": doc,
                "title": meta.get("title", ""),
                "category": meta.get("category", "general"),
                "lang": meta.get("lang", "en"),
                # Convert distance to a score so it ranks like keyword results
                "score": 10 * (1 - dist),
            }
            for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
            if dist <= max_distance
        ]

    try:
        hits = run({"lang": lang})
    except Exception:
        hits = []
    return hits or run(None)
