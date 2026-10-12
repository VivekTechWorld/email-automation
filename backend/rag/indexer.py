"""
indexer.py — ChromaDB Knowledge Base Indexer (optional)
=========================================================
This module is optional. If ChromaDB or Ollama are not installed/available,
all functions return safe defaults so the rest of the backend can still run.
"""

import os
import hashlib
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}
KNOWN_LANGS = {"en", "fi"}

# ── Optional imports ──────────────────────────────────────────────────────────
try:
    import chromadb as _chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _chromadb = None
    _CHROMA_AVAILABLE = False
    log.warning("chromadb not installed — RAG ingestion disabled.")

try:
    import ollama as _ollama
    _OLLAMA_AVAILABLE = True
except ImportError:
    _ollama = None
    _OLLAMA_AVAILABLE = False
    log.warning("ollama not installed — embedding disabled.")


# ── Collection ────────────────────────────────────────────────────────────────

def get_collection():
    if not _CHROMA_AVAILABLE:
        raise RuntimeError("chromadb is not installed. RAG is disabled.")
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "../data/chroma_db")
    client = _chromadb.PersistentClient(path=persist_dir)
    return client.get_or_create_collection(
        name="knowledge_base",
        metadata={"hnsw:space": "cosine"},
    )


# ── Embeddings ────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    if not _OLLAMA_AVAILABLE:
        raise RuntimeError("ollama is not installed. Embeddings disabled.")
    model = os.getenv("EMBED_MODEL", "nomic-embed-text")
    response = _ollama.embeddings(model=model, prompt=text)
    return response["embedding"]


# ── Language detection from filename ─────────────────────────────────────────

def detect_lang_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    parts = stem.split("-")
    last = parts[-1].lower()
    if last in KNOWN_LANGS and len(parts) > 1:
        return last
    return os.getenv("DEFAULT_LANG", "en")


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 150, overlap: int = 30) -> list[str]:
    words = text.split()
    chunks = []
    step = chunk_size - overlap
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if len(chunk.strip()) > 30:
            chunks.append(chunk)
    return chunks


# ── File reader ───────────────────────────────────────────────────────────────

def read_file(file_path: Path) -> str:
    if file_path.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except ImportError:
            log.warning("pdfplumber not installed — skipping %s", file_path.name)
            return ""
    return file_path.read_text(encoding="utf-8", errors="ignore")


# ── Ingest ────────────────────────────────────────────────────────────────────

async def ingest_documents(directory: str) -> int:
    if not _CHROMA_AVAILABLE or not _OLLAMA_AVAILABLE:
        raise RuntimeError(
            "RAG ingestion requires chromadb + ollama. "
            "These are unavailable on this platform. "
            "Run ingestion from a Linux/WSL environment."
        )

    collection = get_collection()
    base_path = Path(directory)

    if not base_path.exists():
        raise FileNotFoundError(f"Knowledge base directory not found: {directory}")

    total_chunks = 0
    for file_path in base_path.rglob("*"):
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            lang = detect_lang_from_filename(file_path.name)
            text = read_file(file_path)
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                doc_id = hashlib.md5(f"{file_path.name}::{i}".encode()).hexdigest()
                embedding = embed_text(chunk)
                collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[chunk],
                    metadatas=[{"source": file_path.name, "chunk_index": i, "lang": lang}],
                )
                total_chunks += 1
            log.info("Ingested [%s]: %s (%d chunks)", lang, file_path.name, len(chunks))
        except Exception as e:
            log.error("Error ingesting %s: %s", file_path.name, e)

    return total_chunks
