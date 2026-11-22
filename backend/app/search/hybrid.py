"""Hybrid search combining SQLite FTS5 keyword search and vector similarity with RRF."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.db import GENERIC_WORDS, compute_term_idfs, get_chunks_for_model, search_fts
from app.search.embedder import Embedder, get_embedder

logger = logging.getLogger(__name__)


@dataclass
class VectorMatrixCache:
    """In-memory cache for contiguous float32 vector matrix and chunk metadata."""

    cache_key: tuple[str, int, int] | None = None  # (model_name, chunk_count, max_chunk_id)
    matrix: np.ndarray | None = None  # 2D float32 array of shape (N, D)
    metadata: list[dict[str, Any]] = field(default_factory=list)


_vector_cache = VectorMatrixCache()


def invalidate_vector_cache() -> None:
    """Clear cached vector matrix (called on re-chunking or database resets)."""
    global _vector_cache
    _vector_cache = VectorMatrixCache()


def get_cached_vector_matrix(
    conn: sqlite3.Connection,
    model_name: str,
) -> tuple[np.ndarray | None, list[dict[str, Any]]]:
    """
    Retrieve in-memory float32 vector matrix and metadata.
    Reloads from SQLite only when chunks change or on first run.
    Validates chunk_count and max_chunk_id in O(1) time.
    """
    global _vector_cache

    try:
        cur = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM chunks WHERE model = ?",
            (model_name,),
        )
        row = cur.fetchone()
        chunk_count = int(row[0]) if row else 0
        max_chunk_id = int(row[1]) if row else 0
    except Exception:
        chunk_count = 0
        max_chunk_id = 0

    if chunk_count == 0:
        return None, []

    current_key = (model_name, chunk_count, max_chunk_id)
    if (
        _vector_cache.cache_key == current_key
        and _vector_cache.matrix is not None
        and len(_vector_cache.metadata) == chunk_count
    ):
        return _vector_cache.matrix, _vector_cache.metadata

    # Reload from SQLite
    rows = get_chunks_for_model(conn, model_name)
    if not rows:
        _vector_cache = VectorMatrixCache()
        return None, []

    vector_list = [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
    matrix = np.array(vector_list, dtype=np.float32)

    meta = [
        {
            "file_id": r["file_id"],
            "path": r["path"],
            "filename": r["filename"],
            "modified_at": r["modified_at"],
            "text": r["text"],
        }
        for r in rows
    ]

    _vector_cache = VectorMatrixCache(
        cache_key=current_key,
        matrix=matrix,
        metadata=meta,
    )
    return matrix, meta


def warmup_vector_cache(conn: sqlite3.Connection) -> None:
    """Pre-warm FastEmbed model and load vector matrix into memory for instant /ask queries."""
    try:
        embedder = get_embedder()
        model_name = embedder.model_name
        get_cached_vector_matrix(conn, model_name)
    except Exception as exc:
        logger.warning("Vector cache warmup failed: %s", exc)


def make_snippet(text: str, max_chars: int = 150) -> str:
    """Create a concise snippet from text."""
    clean = " ".join(text.split())
    if len(clean) > max_chars:
        return clean[:max_chars].rstrip() + "..."
    return clean


def vector_search(
    conn: sqlite3.Connection,
    query: str,
    embedder: Embedder | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """
    Search chunks using cosine similarity over normalized float32 embeddings.
    Uses in-memory float32 matrix cache for high throughput (< 50ms).
    Groups chunks by parent file so the best chunk wins for each file.
    If the embedding model is missing or fails to load, gracefully returns [].
    """
    model_name = embedder.model_name if embedder is not None else settings.embedding_model

    # 1. Retrieve or reload cached matrix
    matrix, meta = get_cached_vector_matrix(conn, model_name)
    if matrix is None or not meta:
        return []

    # 2. Embed query safely
    try:
        if embedder is None:
            embedder = get_embedder()
        query_vectors = embedder.embed_texts([query])
        if len(query_vectors) == 0:
            return []
        query_vec = query_vectors[0]
    except Exception as exc:
        logger.warning("Embedding query failed (%s); falling back to keyword search.", exc)
        return []

    # 3. Compute dot-product cosine similarity with in-memory matrix
    similarities = matrix @ query_vec

    # 4. Group by file_id (best chunk score wins)
    file_best: dict[int, dict[str, Any]] = {}
    for idx, row in enumerate(meta):
        sim = float(similarities[idx])
        fid = row["file_id"]
        if fid not in file_best or sim > file_best[fid]["sim"]:
            file_best[fid] = {
                "file_id": fid,
                "sim": sim,
                "row": row,
                "best_text": row["text"],
            }

    # 5. Sort by similarity descending
    sorted_files = sorted(file_best.values(), key=lambda x: x["sim"], reverse=True)
    results: list[dict[str, Any]] = []
    for rank, item in enumerate(sorted_files[:limit], start=1):
        r = item["row"]
        results.append({
            "rank": rank,
            "file_id": item["file_id"],
            "path": r["path"],
            "filename": r["filename"],
            "modified_at": r["modified_at"],
            "score": item["sim"],
            "best_text": item["best_text"],
        })
    return results


IMAGE_WORDS: set[str] = {
    "photo",
    "picture",
    "image",
    "screenshot",
    "png",
    "jpg",
    "pic",
    "tasveer",
}


def query_has_image_word(query: str) -> bool:
    """Check if query contains words referring to images/photos."""
    tokens = re.findall(r"\b[a-zA-Z0-9_]+\b", query.lower())
    for token in tokens:
        t = token.rstrip("s")
        if t in IMAGE_WORDS or token in IMAGE_WORDS:
            return True
    return False


def is_image_result(item: dict[str, Any]) -> bool:
    """Check if a search result item represents an image file."""
    path_str = item.get("path", "")
    ext = Path(path_str).suffix.lower()
    doc_type = (item.get("doc_type") or "").lower()
    return ext in {".png", ".jpg", ".jpeg"} or doc_type in ("image", "photo")


def apply_image_search_policy(
    results: list[dict[str, Any]],
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Search policy:
    Results of type image are returned ONLY when:
    - query contains an image word (photo, picture, image, screenshot, png, jpg, pic, tasveer), OR
    - fewer than 3 document results exist.
    Never let image results outrank documents for other queries.
    """
    if query_has_image_word(query):
        filtered = results[:limit]
        for idx, r in enumerate(filtered, start=1):
            r["rank"] = idx
        return filtered

    docs = [r for r in results if not is_image_result(r)]
    images = [r for r in results if is_image_result(r)]

    if len(docs) >= 3:
        filtered = docs[:limit]
    else:
        filtered = (docs + images)[:limit]

    for idx, r in enumerate(filtered, start=1):
        r["rank"] = idx

    return filtered


def matches_filters(
    path: str,
    modified_at: float,
    file_types: list[str] | None = None,
    min_modified: float | None = None,
    source: str | None = None,
    sender: str | None = None,
    sender_map: dict[str, str] | None = None,
) -> bool:
    """Check if a file path and timestamp satisfy optional file type, date, source, and sender filters."""
    if source == "gmail" and not path.startswith("gmail://"):
        return False
    if sender and sender_map:
        file_sender = sender_map.get(path, "").lower()
        if sender.lower() not in file_sender:
            return False
    if file_types:
        ext = Path(path).suffix.lower()
        if ext not in file_types:
            return False
    if min_modified is not None:
        if modified_at < min_modified:
            return False
    return True


def hybrid_search(
    conn: sqlite3.Connection,
    query: str,
    embedder: Embedder | None = None,
    mode: str = "hybrid",  # "keyword", "semantic", "hybrid"
    limit: int = 10,
    k: int = 60,
    file_types: list[str] | None = None,
    min_modified: float | None = None,
    doc_types: list[str] | None = None,
    source: str | None = None,
    sender: str | None = None,
) -> list[dict[str, Any]]:
    """
    Execute keyword, semantic, or hybrid search with optional file type, date, doc_type, source, and sender filters.
    Hybrid mode merges keyword and vector rankings using Reciprocal Rank Fusion (RRF, k=60).
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # Map paths to doc_types and senders
    doc_type_map: dict[str, str] = {}
    try:
        dt_cur = conn.execute("SELECT path, doc_type FROM files")
        doc_type_map = {row["path"]: (row["doc_type"] or "other") for row in dt_cur.fetchall()}
    except Exception:
        pass

    sender_map: dict[str, str] = {}
    if sender:
        try:
            s_cur = conn.execute("SELECT f.path, e.sender FROM files f JOIN emails e ON f.id = e.file_id")
            sender_map = {row["path"]: (row["sender"] or "").lower() for row in s_cur.fetchall()}
        except Exception:
            pass

    # Extract terms and identify rare term via IDF (generic words deprioritized)
    terms = [t.lower() for t in re.findall(r"\w+", clean_query) if t.strip()]
    idfs = compute_term_idfs(conn, terms) if terms else {}
    non_generic = [t for t in terms if t not in GENERIC_WORDS]
    rare_term = (
        max(non_generic, key=lambda t: idfs.get(t, 0.0))
        if non_generic
        else (max(terms, key=lambda t: idfs.get(t, 0.0)) if terms else "")
    )

    # Keyword only mode
    if mode == "keyword":
        raw_fts = search_fts(conn, clean_query, limit=limit * 4 if (file_types or min_modified or source or sender) else limit)
        filtered = [
            item for item in raw_fts
            if matches_filters(item["path"], item["modified_at"], file_types, min_modified, source, sender, sender_map)
        ]
        # Sort: rare term in filename first (1.0), in folder (0.5), then by score descending
        def kw_sort_key(it: dict[str, Any]) -> tuple[float, float]:
            fn = it["filename"].lower()
            pt = it["path"].lower()
            if rare_term and rare_term in fn:
                pri = 1.0
            elif rare_term and rare_term in pt:
                pri = 0.5
            else:
                pri = 0.0
            return (pri, it["score"])

        filtered.sort(key=kw_sort_key, reverse=True)
        raw_res = [
            {
                "rank": idx,
                "path": item["path"],
                "filename": item["filename"],
                "modified_at": item["modified_at"],
                "snippet": item["snippet"],
                "score": item["score"],
                "match_type": "keyword",
                "doc_type": doc_type_map.get(item["path"], "other"),
            }
            for idx, item in enumerate(filtered, start=1)
        ]
        return apply_image_search_policy(raw_res, clean_query, limit=limit)

    # Semantic only mode
    if mode == "semantic":
        try:
            raw_vec = vector_search(
                conn,
                clean_query,
                embedder=embedder,
                limit=limit * 3 if (file_types or min_modified) else limit,
            )
        except Exception as exc:
            logger.warning("Semantic search error (%s); falling back to keyword search.", exc)
            raw_vec = []

        if not raw_vec:
            return hybrid_search(
                conn,
                clean_query,
                embedder=embedder,
                mode="keyword",
                limit=limit,
                k=k,
                file_types=file_types,
                min_modified=min_modified,
                doc_types=doc_types,
                source=source,
                sender=sender,
            )

        filtered = [
            item for item in raw_vec
            if matches_filters(item["path"], item["modified_at"], file_types, min_modified, source, sender, sender_map)
        ]
        raw_res = [
            {
                "rank": idx,
                "path": item["path"],
                "filename": item["filename"],
                "modified_at": item["modified_at"],
                "snippet": make_snippet(item["best_text"]),
                "score": item["score"],
                "match_type": "meaning",
                "doc_type": doc_type_map.get(item["path"], "other"),
            }
            for idx, item in enumerate(filtered, start=1)
        ]
        return apply_image_search_policy(raw_res, clean_query, limit=limit)

    # Hybrid mode (default): weighted RRF merge (2 to 1 for keyword vs semantic)
    pool_size = max(50, limit * 4)
    raw_fts = search_fts(conn, clean_query, limit=pool_size)
    try:
        raw_vec = vector_search(conn, clean_query, embedder=embedder, limit=pool_size)
    except Exception as exc:
        logger.warning("Vector search failed (%s); using keyword results.", exc)
        raw_vec = []

    fts_results = [
        item for item in raw_fts
        if matches_filters(item["path"], item["modified_at"], file_types, min_modified, source, sender, sender_map)
    ]
    vec_results = [
        item for item in raw_vec
        if matches_filters(item["path"], item["modified_at"], file_types, min_modified, source, sender, sender_map)
    ]

    scores: dict[str, float] = {}
    file_info: dict[str, dict[str, Any]] = {}
    matched_methods: dict[str, set[str]] = {}

    # Weight keyword ranking 2 to 1 over semantic ranking
    w_keyword = 2.0
    w_semantic = 1.0

    for item in fts_results:
        path = item["path"]
        scores[path] = scores.get(path, 0.0) + w_keyword * (1.0 / (k + item["rank"]))
        file_info[path] = {
            "path": path,
            "filename": item["filename"],
            "modified_at": item["modified_at"],
            "snippet": item["snippet"],
        }
        matched_methods.setdefault(path, set()).add("keyword")

    for item in vec_results:
        path = item["path"]
        scores[path] = scores.get(path, 0.0) + w_semantic * (1.0 / (k + item["rank"]))
        if path not in file_info:
            file_info[path] = {
                "path": path,
                "filename": item["filename"],
                "modified_at": item["modified_at"],
                "snippet": make_snippet(item["best_text"]),
            }
        matched_methods.setdefault(path, set()).add("meaning")

    # Boost score if file's doc_type matches query doc_types
    if doc_types:
        for path in scores:
            if doc_type_map.get(path) in doc_types:
                scores[path] += 0.05

    # Sort: put files whose filename matches the rare term first, then folder, then by score descending
    def sort_key(p: str) -> tuple[float, float]:
        fname = file_info[p]["filename"].lower()
        path_lower = p.lower()
        if rare_term and rare_term in fname:
            pri = 1.0
        elif rare_term and rare_term in path_lower:
            pri = 0.5
        else:
            pri = 0.0
        return (pri, scores[p])

    sorted_paths = sorted(scores.keys(), key=sort_key, reverse=True)
    results: list[dict[str, Any]] = []

    for idx, path in enumerate(sorted_paths, start=1):
        methods = matched_methods[path]
        if "keyword" in methods and "meaning" in methods:
            match_type = "both"
        elif "keyword" in methods:
            match_type = "keyword"
        else:
            match_type = "meaning"

        info = file_info[path]
        results.append({
            "rank": idx,
            "path": path,
            "filename": info["filename"],
            "modified_at": info["modified_at"],
            "snippet": info["snippet"],
            "score": scores[path],
            "match_type": match_type,
            "doc_type": doc_type_map.get(path, "other"),
        })

    return apply_image_search_policy(results, clean_query, limit=limit)
