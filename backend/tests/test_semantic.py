"""Tests for semantic search: chunker, embedder, incremental embedding, and hybrid search."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import numpy as np
import pytest

from app.config import settings
from app.db import (
    compute_term_idfs,
    delete_chunks_by_file_id,
    delete_file_by_path,
    get_chunks_for_model,
    get_connection,
    get_stats,
    init_db,
    search_fts,
    upsert_file_record,
)
from app.ingestion.chunker import (
    MAX_CHUNKS_PER_FILE,
    chunk_file,
    make_title_chunk,
)
from app.search.embedder import set_embedder
from app.search.hybrid import hybrid_search, vector_search


class FakeEmbedder:
    """Deterministic, lightweight fake embedder with zero downloads for testing."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dim: int = 16,
    ) -> None:
        self.model_name = model_name
        self.dim = dim

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)

        results = []
        for text in texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            words = text.lower().split()
            if words:
                for word in words:
                    # Deterministic hash index
                    idx = abs(hash(word)) % self.dim
                    vec[idx] += 1.0
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
                else:
                    vec[0] = 1.0
            else:
                vec[0] = 1.0
            results.append(vec)

        return np.array(results, dtype=np.float32)


@pytest.fixture(autouse=True)
def setup_fake_embedder():
    """Ensure FakeEmbedder is active for all tests in this module."""
    fake = FakeEmbedder(model_name=settings.embedding_model)
    set_embedder(fake)
    yield fake
    set_embedder(None)


@pytest.fixture
def test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up an isolated temporary database for semantic tests."""
    temp_data_dir = tmp_path / "data"
    temp_data_dir.mkdir(parents=True, exist_ok=True)
    temp_db = temp_data_dir / "recall.db"
    monkeypatch.setattr(settings, "data_dir", temp_data_dir)
    monkeypatch.setattr(settings, "db_path", temp_db)
    init_db(temp_db)
    return temp_db


def test_chunking_title_and_text():
    """Verify title chunk generation, word chunking with overlap, and chunk cap."""
    path = r"D:\documents\Finance\tax_report_2025.pdf"
    title = make_title_chunk(path)
    assert "Finance" in title
    assert "tax report 2025" in title

    # Generate 500 words of dummy text
    words = [f"word{i}" for i in range(500)]
    full_text = " ".join(words)

    chunks = chunk_file(path, status="indexed", text=full_text)
    assert len(chunks) > 1
    # First chunk is title
    assert chunks[0].chunk_index == 0
    assert chunks[0].kind == "title"
    assert "tax report 2025" in chunks[0].text

    # Subsequent chunks are text with ~200 words and 40 word overlap
    assert chunks[1].chunk_index == 1
    assert chunks[1].kind == "text"
    first_chunk_words = chunks[1].text.split()
    assert len(first_chunk_words) == 200

    second_chunk_words = chunks[2].text.split()
    # Check overlap (last 40 words of chunk 1 == first 40 words of chunk 2)
    assert first_chunk_words[-40:] == second_chunk_words[:40]

    # Test chunk cap (200 chunks max)
    huge_text = " ".join([f"word{i}" for i in range(40000)])
    huge_chunks = chunk_file(path, status="indexed", text=huge_text)
    assert len(huge_chunks) == MAX_CHUNKS_PER_FILE


def test_title_only_for_needs_ocr_and_empty():
    """Files with needs_ocr or empty status should only receive a title chunk."""
    path_ocr = r"D:\scans\document_scanned.pdf"
    chunks_ocr = chunk_file(path_ocr, status="needs_ocr", text="")
    assert len(chunks_ocr) == 1
    assert chunks_ocr[0].kind == "title"
    assert chunks_ocr[0].chunk_index == 0
    assert "document scanned" in chunks_ocr[0].text

    path_empty = r"D:\notes\blank_file.txt"
    chunks_empty = chunk_file(path_empty, status="empty", text="")
    assert len(chunks_empty) == 1
    assert chunks_empty[0].kind == "title"
    assert chunks_empty[0].chunk_index == 0
    assert "blank file" in chunks_empty[0].text


def test_incremental_embedding(test_db: Path):
    """Verify incremental embedding: skip unchanged files, re-embed changed files."""
    from app.cli import handle_embed

    conn = get_connection(test_db)
    try:
        # 1. Insert two indexed files
        upsert_file_record(
            conn,
            path="D:/docs/file1.txt",
            filename="file1.txt",
            ext=".txt",
            size=100,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="hash1",
            indexed_at=1000.0,
            status="indexed",
            text="First document containing alpha and beta concepts.",
        )
        upsert_file_record(
            conn,
            path="D:/docs/file2.txt",
            filename="file2.txt",
            ext=".txt",
            size=200,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="hash2",
            indexed_at=1000.0,
            status="indexed",
            text="Second document discussing gamma and delta principles.",
        )
        conn.commit()

        # Run embed CLI command
        args = argparse.Namespace()
        ret = handle_embed(args)
        assert ret == 0

        # Verify chunks exist
        rows1 = conn.execute("SELECT * FROM chunks WHERE file_id = 1").fetchall()
        rows2 = conn.execute("SELECT * FROM chunks WHERE file_id = 2").fetchall()
        assert len(rows1) > 0
        assert len(rows2) > 0

        # Run embed a second time: should skip because nothing changed
        ret2 = handle_embed(args)
        assert ret2 == 0

        # Now edit file 1 (new content)
        upsert_file_record(
            conn,
            path="D:/docs/file1.txt",
            filename="file1.txt",
            ext=".txt",
            size=150,
            created_at=1000.0,
            modified_at=1050.0,
            content_hash="hash1_new",
            indexed_at=1050.0,
            status="indexed",
            text="First document edited with completely new words and omega topics.",
        )
        conn.commit()

        # Re-run embed: only file 1 should re-embed
        ret3 = handle_embed(args)
        assert ret3 == 0

        # Check that file 1's chunk now contains the new text
        cur = conn.execute("SELECT text FROM chunks WHERE file_id = 1 AND kind = 'text'")
        updated_chunk = cur.fetchone()
        assert updated_chunk is not None
        assert "omega" in updated_chunk["text"]

    finally:
        conn.close()


def test_deleted_file_cleanup_chunks(test_db: Path):
    """Verify that chunks belonging to deleted files are cleaned up."""
    from app.cli import handle_embed

    conn = get_connection(test_db)
    try:
        upsert_file_record(
            conn,
            path="D:/docs/temp.txt",
            filename="temp.txt",
            ext=".txt",
            size=50,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="temp_hash",
            indexed_at=1000.0,
            status="indexed",
            text="Temporary document content.",
        )
        conn.commit()

        args = argparse.Namespace()
        handle_embed(args)

        # Confirm chunks exist
        chunks_before = conn.execute("SELECT COUNT(*) AS total FROM chunks").fetchone()["total"]
        assert chunks_before > 0

        # Delete the file from the files table
        delete_file_by_path(conn, "D:/docs/temp.txt")
        conn.commit()

        # Running handle_embed triggers orphan chunk cleanup
        handle_embed(args)

        chunks_after = conn.execute("SELECT COUNT(*) AS total FROM chunks").fetchone()["total"]
        assert chunks_after == 0

    finally:
        conn.close()


def test_hybrid_search_rrf(test_db: Path):
    """Verify hybrid search with RRF scoring and match types (keyword, meaning, both)."""
    from app.cli import handle_embed

    conn = get_connection(test_db)
    try:
        # File A contains exact keyword "quantum" and concept "physics"
        upsert_file_record(
            conn,
            path="D:/docs/quantum.txt",
            filename="quantum.txt",
            ext=".txt",
            size=100,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_q",
            indexed_at=1000.0,
            status="indexed",
            text="Quantum computing utilizes quantum superposition and entanglement in physics.",
        )
        # File B contains only related concept "physics research lab equipment"
        upsert_file_record(
            conn,
            path="D:/docs/physics.txt",
            filename="physics.txt",
            ext=".txt",
            size=100,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_p",
            indexed_at=1000.0,
            status="indexed",
            text="Advanced physics research laboratory equipment for university science department.",
        )
        conn.commit()

        # Embed all files
        args = argparse.Namespace()
        handle_embed(args)

        # 1. Keyword search mode: only file A has the word 'quantum'
        kw_results = hybrid_search(conn, "quantum", mode="keyword")
        assert len(kw_results) == 1
        assert kw_results[0]["filename"] == "quantum.txt"
        assert kw_results[0]["match_type"] == "keyword"

        # 2. Semantic search mode
        sem_results = hybrid_search(conn, "physics", mode="semantic")
        assert len(sem_results) > 0
        assert all(r["match_type"] == "meaning" for r in sem_results)

        # 3. Hybrid search mode: when searching for 'quantum physics'
        hybrid_results = hybrid_search(conn, "quantum", mode="hybrid")
        assert len(hybrid_results) > 0
        # The document with exact keyword match and semantic relevance gets 'both' or ranked highest
        top_match = hybrid_results[0]
        assert top_match["filename"] == "quantum.txt"
        assert top_match["match_type"] in ("both", "keyword")

    finally:
        conn.close()


def test_hybrid_ranking_nasa_certificate_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    With nasa.pdf as a scanned PDF in folder 'my certif' (title chunk only)
    plus several other certificate PDFs, both queries 'nasa certificate' and 'nasa'
    must return nasa.pdf as result 1.
    Verifies:
    - Generic words ('certificate') treated as low weight
    - Rare words ('nasa') win with IDF weighting
    - Rare term in filename/folder receives strong boost
    - Keyword search tries AND first, falls back to OR with score = sum of term weights
    - 2:1 hybrid merge with rare-term prioritization
    """
    from app.cli import handle_embed

    temp_data = tmp_path / "data"
    temp_data.mkdir(parents=True, exist_ok=True)
    temp_db = temp_data / "recall.db"
    monkeypatch.setattr(settings, "data_dir", temp_data)
    monkeypatch.setattr(settings, "db_path", temp_db)
    init_db(temp_db)

    fake = FakeEmbedder()
    set_embedder(fake)

    # File 1: nasa.pdf - scanned PDF in 'my certif' folder (needs_ocr, title chunk only)
    p_nasa = r"D:\documents\my certif\nasa.pdf"
    p_cert1 = r"D:\documents\courses\certificate_python_course.pdf"
    p_cert2 = r"D:\documents\courses\certificate_cloud_architecture.pdf"
    p_cert3 = r"D:\documents\courses\certificate_data_science.pdf"
    p_cert4 = r"D:\documents\courses\infosis_course_certificate.pdf"

    conn = get_connection(temp_db)
    try:
        upsert_file_record(
            conn,
            path=p_nasa,
            filename="nasa.pdf",
            ext=".pdf",
            size=1000,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_nasa",
            indexed_at=1000.0,
            status="needs_ocr",  # Scanned PDF: only title chunk!
            text=None,
        )
        upsert_file_record(
            conn,
            path=p_cert1,
            filename="certificate_python_course.pdf",
            ext=".pdf",
            size=1000,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_c1",
            indexed_at=1000.0,
            status="indexed",
            text="Certificate of completion in advanced python programming and web development.",
        )
        upsert_file_record(
            conn,
            path=p_cert2,
            filename="certificate_cloud_architecture.pdf",
            ext=".pdf",
            size=1000,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_c2",
            indexed_at=1000.0,
            status="indexed",
            text="Certificate of participation in distributed cloud systems engineering.",
        )
        upsert_file_record(
            conn,
            path=p_cert3,
            filename="certificate_data_science.pdf",
            ext=".pdf",
            size=1000,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_c3",
            indexed_at=1000.0,
            status="indexed",
            text="Certificate of excellence in machine learning and data science algorithms.",
        )
        upsert_file_record(
            conn,
            path=p_cert4,
            filename="infosis_course_certificate.pdf",
            ext=".pdf",
            size=1000,
            created_at=1000.0,
            modified_at=1000.0,
            content_hash="h_c4",
            indexed_at=1000.0,
            status="indexed",
            text="Official certificate awarded for successful completion of agile scrum training.",
        )
        conn.commit()

        # Embed all files using handle_embed
        args = argparse.Namespace()
        handle_embed(args)

        # 1. Test query "nasa certificate"
        # Hybrid search
        hybrid_nasa_cert = hybrid_search(conn, "nasa certificate", mode="hybrid")
        assert len(hybrid_nasa_cert) > 0
        assert hybrid_nasa_cert[0]["filename"] == "nasa.pdf", f"Expected nasa.pdf first in hybrid for 'nasa certificate', got {hybrid_nasa_cert[0]['filename']}"

        # Keyword search
        kw_nasa_cert = hybrid_search(conn, "nasa certificate", mode="keyword")
        assert len(kw_nasa_cert) > 0
        assert kw_nasa_cert[0]["filename"] == "nasa.pdf", f"Expected nasa.pdf first in keyword for 'nasa certificate', got {kw_nasa_cert[0]['filename']}"

        # Direct search_fts
        fts_nasa_cert = search_fts(conn, "nasa certificate")
        assert len(fts_nasa_cert) > 0
        assert fts_nasa_cert[0]["filename"] == "nasa.pdf", f"Expected nasa.pdf first in search_fts for 'nasa certificate', got {fts_nasa_cert[0]['filename']}"

        # 2. Test query "nasa"
        # Hybrid search
        hybrid_nasa = hybrid_search(conn, "nasa", mode="hybrid")
        assert len(hybrid_nasa) > 0
        assert hybrid_nasa[0]["filename"] == "nasa.pdf", f"Expected nasa.pdf first in hybrid for 'nasa', got {hybrid_nasa[0]['filename']}"

        # Keyword search
        kw_nasa = hybrid_search(conn, "nasa", mode="keyword")
        assert len(kw_nasa) > 0
        assert kw_nasa[0]["filename"] == "nasa.pdf", f"Expected nasa.pdf first in keyword for 'nasa', got {kw_nasa[0]['filename']}"

        # Direct search_fts
        fts_nasa = search_fts(conn, "nasa")
        assert len(fts_nasa) > 0
        assert fts_nasa[0]["filename"] == "nasa.pdf", f"Expected nasa.pdf first in search_fts for 'nasa', got {fts_nasa[0]['filename']}"

    finally:
        conn.close()
