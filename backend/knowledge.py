"""
knowledge.py — Dashboard-managed Knowledge Base (text only)
============================================================
Articles live in the same SQLite database as the email logs, so the team can
add / edit / delete knowledge from the dashboard without touching files.

Each article has a category (matching the email categories plus "general") and
a language. Articles are split into chunks for retrieval. Limits keep the
knowledge base — and the context sent to the model per email — bounded:

  KB_MAX_ARTICLE_CHARS  max characters in one article        (default 15000)
  KB_CHUNK_CHARS        target size of one chunk             (default 900)
  KB_MAX_TOTAL_CHUNKS   max chunks across the whole KB       (default 500)
  RAG_CONTEXT_MAX_CHARS max KB characters put in one prompt  (default 6000, see retriever)

On first start the existing files in KNOWLEDGE_BASE_DIR are imported once.
"""

import os
import re
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from logger import get_db_connection

log = logging.getLogger(__name__)

KB_CATEGORIES = ["general", "sales", "inquiry", "billing", "support", "bug"]
KB_LANGS = ["en", "fi"]

_BACKEND_DIR = Path(__file__).resolve().parent

# Bumped on every change so the retriever knows to rebuild its cache
_version = 0
_version_lock = threading.Lock()


class KnowledgeLimitError(ValueError):
    """Raised when a save would exceed the configured knowledge-base limits."""


def limits() -> dict:
    return {
        "max_article_chars": int(os.getenv("KB_MAX_ARTICLE_CHARS", "15000")),
        "chunk_chars": int(os.getenv("KB_CHUNK_CHARS", "900")),
        "max_total_chunks": int(os.getenv("KB_MAX_TOTAL_CHUNKS", "500")),
        "context_max_chars": int(os.getenv("RAG_CONTEXT_MAX_CHARS", "6000")),
    }


def get_version() -> int:
    return _version


def _bump_version():
    global _version
    with _version_lock:
        _version += 1


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_chars: Optional[int] = None) -> list[str]:
    """
    Split text into chunks of roughly `chunk_chars`, keeping paragraphs together.
    Paragraphs longer than the limit are split on sentence boundaries.
    """
    size = chunk_chars or limits()["chunk_chars"]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    pieces: list[str] = []
    for para in paragraphs:
        if len(para) <= size:
            pieces.append(para)
            continue
        sentence_buf = ""
        for sentence in re.split(r"(?<=[.!?])\s+|\n", para):
            if not sentence.strip():
                continue
            if sentence_buf and len(sentence_buf) + len(sentence) + 1 > size:
                pieces.append(sentence_buf.strip())
                sentence_buf = ""
            # A single huge "sentence" is hard-cut so no chunk exceeds the limit
            while len(sentence) > size:
                pieces.append(sentence[:size])
                sentence = sentence[size:]
            sentence_buf += sentence + "\n"
        if sentence_buf.strip():
            pieces.append(sentence_buf.strip())

    # Merge small neighbouring pieces so chunks are not too fragmented
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if buf and len(buf) + len(piece) + 2 > size:
            chunks.append(buf)
            buf = ""
        buf = f"{buf}\n\n{piece}" if buf else piece
    if buf:
        chunks.append(buf)
    return chunks


# ── Schema ────────────────────────────────────────────────────────────────────

def init_knowledge_base():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                lang TEXT NOT NULL DEFAULT 'en',
                content TEXT NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kb_category ON kb_articles(category);")
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM kb_articles").fetchone()[0]

    if count == 0:
        _import_seed_files()
    _bump_version()


def _kb_dir() -> Path:
    path = Path(os.getenv("KNOWLEDGE_BASE_DIR", "../data/knowledge_base"))
    return path if path.is_absolute() else (_BACKEND_DIR / path).resolve()


def _import_seed_files():
    """One-time import of the original knowledge-base text files."""
    base = _kb_dir()
    if not base.exists():
        return
    imported = 0
    for file_path in sorted(base.glob("*")):
        if file_path.suffix.lower() not in {".txt", ".md"}:
            continue
        parts = file_path.stem.split("-")
        lang = parts[-1].lower() if len(parts) > 1 and parts[-1].lower() in KB_LANGS else "en"
        title = file_path.stem.replace("-", " ").replace("_", " ").strip().title()
        content = file_path.read_text(encoding="utf-8", errors="ignore").strip()
        try:
            create_article(title=title, category="general", lang=lang, content=content)
            imported += 1
        except KnowledgeLimitError as e:
            log.warning("Skipped seeding %s: %s", file_path.name, e)
    log.info("Imported %d knowledge-base file(s) from %s into the dashboard KB.", imported, base)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate(title: str, category: str, lang: str, content: str) -> tuple[str, str, str, str]:
    title = (title or "").strip()
    content = (content or "").replace("\r\n", "\n").strip()
    category = (category or "general").strip().lower()
    lang = (lang or "en").strip().lower()
    lim = limits()

    if not title:
        raise ValueError("Title is required.")
    if len(title) > 200:
        raise ValueError("Title must be 200 characters or fewer.")
    if not content:
        raise ValueError("Content is required.")
    if category not in KB_CATEGORIES:
        raise ValueError(f"Category must be one of: {', '.join(KB_CATEGORIES)}.")
    if lang not in KB_LANGS:
        raise ValueError(f"Language must be one of: {', '.join(KB_LANGS)}.")
    if len(content) > lim["max_article_chars"]:
        raise KnowledgeLimitError(
            f"Article is {len(content):,} characters; the limit is {lim['max_article_chars']:,}. "
            "Split it into smaller articles."
        )
    return title, category, lang, content


def _check_total_chunks(new_chunks: int, exclude_id: Optional[int] = None):
    lim = limits()
    with get_db_connection() as conn:
        if exclude_id is None:
            used = conn.execute("SELECT COALESCE(SUM(chunk_count), 0) FROM kb_articles").fetchone()[0]
        else:
            used = conn.execute(
                "SELECT COALESCE(SUM(chunk_count), 0) FROM kb_articles WHERE id != ?", (exclude_id,)
            ).fetchone()[0]
    if used + new_chunks > lim["max_total_chunks"]:
        raise KnowledgeLimitError(
            f"This would use {used + new_chunks} chunks; the knowledge-base limit is "
            f"{lim['max_total_chunks']}. Shorten or delete other articles first."
        )


def _row(row) -> dict:
    return dict(row) if row else None


def list_articles(category: Optional[str] = None) -> list[dict]:
    with get_db_connection() as conn:
        sql = ("SELECT id, title, category, lang, chunk_count, length(content) AS char_count, "
               "substr(content, 1, 160) AS excerpt, updated_at FROM kb_articles")
        if category:
            rows = conn.execute(sql + " WHERE category = ? ORDER BY updated_at DESC", (category,)).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_article(article_id: int) -> Optional[dict]:
    with get_db_connection() as conn:
        return _row(conn.execute("SELECT * FROM kb_articles WHERE id = ?", (article_id,)).fetchone())


def all_articles_full() -> list[dict]:
    with get_db_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM kb_articles").fetchall()]


def create_article(*, title: str, category: str, lang: str, content: str) -> dict:
    title, category, lang, content = _validate(title, category, lang, content)
    chunk_count = len(chunk_text(content))
    _check_total_chunks(chunk_count)
    now = _now()
    with get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO kb_articles (title, category, lang, content, chunk_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, category, lang, content, chunk_count, now, now),
        )
        conn.commit()
        new_id = cur.lastrowid
    _bump_version()
    return get_article(new_id)


def update_article(article_id: int, *, title: str, category: str, lang: str, content: str) -> Optional[dict]:
    if not get_article(article_id):
        return None
    title, category, lang, content = _validate(title, category, lang, content)
    chunk_count = len(chunk_text(content))
    _check_total_chunks(chunk_count, exclude_id=article_id)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE kb_articles SET title = ?, category = ?, lang = ?, content = ?, chunk_count = ?, "
            "updated_at = ? WHERE id = ?",
            (title, category, lang, content, chunk_count, _now(), article_id),
        )
        conn.commit()
    _bump_version()
    return get_article(article_id)


def delete_article(article_id: int) -> bool:
    with get_db_connection() as conn:
        cur = conn.execute("DELETE FROM kb_articles WHERE id = ?", (article_id,))
        conn.commit()
    _bump_version()
    return cur.rowcount > 0


def usage() -> dict:
    lim = limits()
    with get_db_connection() as conn:
        articles, chunks, chars = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(chunk_count), 0), COALESCE(SUM(length(content)), 0) FROM kb_articles"
        ).fetchone()
        by_category = {c: n for c, n in conn.execute(
            "SELECT category, COUNT(*) FROM kb_articles GROUP BY category"
        ).fetchall()}
    return {
        "articles": articles,
        "chunks_used": chunks,
        "total_chars": chars,
        "by_category": by_category,
        "categories": KB_CATEGORIES,
        "langs": KB_LANGS,
        **lim,
    }
