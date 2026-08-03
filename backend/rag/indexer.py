import chromadb
import ollama
import os
import hashlib
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf"}

# Languages recognised by the system.
# A filename ending in "-{code}" (e.g. artcloud-data-fi.txt) is tagged with
# that language; all other files fall back to DEFAULT_LANG.
KNOWN_LANGS = {"en", "fi"}


# ── Collection ────────────────────────────────────────────────────────────────

def get_collection():
    persist_dir = os.getenv("CHROMA_PERSIST_DIR", "../data/chroma_db")
    client = chromadb.PersistentClient(path=persist_dir)
    return client.get_or_create_collection(
        name="knowledge_base",
        metadata={"hnsw:space": "cosine"},
    )


# ── Embeddings ────────────────────────────────────────────────────────────────

def embed_text(text: str) -> list[float]:
    model = os.getenv("EMBED_MODEL", "nomic-embed-text")
    response = ollama.embeddings(model=model, prompt=text)
    return response["embedding"]


# ── Language detection from filename ─────────────────────────────────────────

def detect_lang_from_filename(filename: str) -> str:
    """
    Extract the language code from a filename using the naming convention:
        {basename}-{lang_code}.{ext}
    Examples:
        artcloud-data-fi.txt  →  "fi"
        artcloud-data-en.txt  →  "en"
        master-manual.txt     →  DEFAULT_LANG (fallback)
    """
    stem = Path(filename).stem          # e.g. "artcloud-data-fi"
    parts = stem.split("-")
    last = parts[-1].lower()
    if last in KNOWN_LANGS and len(parts) > 1:
        return last
    return os.getenv("DEFAULT_LANG", "en")


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 150, overlap: int = 30) -> list[str]:
    """Splits text into overlapping chunks by word count."""
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
        import pdfplumber
        with pdfplumber.open(file_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    return file_path.read_text(encoding="utf-8", errors="ignore")


# ── Ingest ────────────────────────────────────────────────────────────────────

async def ingest_documents(directory: str) -> int:
    """
    Ingest all supported documents from `directory` into ChromaDB.
    Each chunk is tagged with its language (detected from the filename).
    """
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
                    metadatas=[{
                        "source": file_path.name,
                        "chunk_index": i,
                        "lang": lang,
                    }],
                )
                total_chunks += 1

            print(f"  Ingested [{lang}]: {file_path.name} ({len(chunks)} chunks)")

        except Exception as e:
            print(f"  Error ingesting {file_path.name}: {e}")

    return total_chunks
