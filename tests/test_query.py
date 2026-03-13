"""
test_query.py — tests for POST /query

Your router uses:
  - payload.doc_id, payload.question      (QueryRequest schema)
  - get_cached_answer(doc_id, question)   (cache.py)
  - get_relevant_chunks(doc_id, question, db, top_k=5)  (retriever.py)
  - ask_groq(question, chunks)            (llm.py)
  - cache_answer(doc_id, question, response.dict())     (cache.py)

Response: QueryResponse { question, answer, sources: [{chunk_index, content}] }
"""

import io
import time
import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import TEST_USER_2


# ── Helpers ───────────────────────────────────────────────────────────────────

def do_upload(client, auth_headers, filename="test.pdf"):
    content = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    return client.post(
        "/documents/upload",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
        headers=auth_headers,
    )


def get_doc_id(resp):
    return resp.json().get("document_id") or resp.json().get("id")


def make_ready_doc(client, auth_headers, db_session):
    """Upload a doc and force status=ready directly in the test DB session."""
    from app.models.db import Document, DocumentStatus
    upload_resp = do_upload(client, auth_headers)
    doc_id = get_doc_id(upload_resp)

    doc = db_session.query(Document).filter(Document.id == doc_id).first()
    if doc:
        doc.status = DocumentStatus.ready
        db_session.commit()

    return doc_id


def mock_chunks():
    """Two fake DocumentChunk objects for patching retriever."""
    c1 = MagicMock()
    c1.chunk_index = 0
    c1.content = "DocuMind is an AI-powered document intelligence API."
    c2 = MagicMock()
    c2.chunk_index = 1
    c2.content = "It supports PDF upload, semantic search, and Groq LLM answers."
    return [c1, c2]


# ── Basic validation ──────────────────────────────────────────────────────────

class TestQueryValidation:

    def test_query_requires_auth(self, client):
        """No token → 401."""
        resp = client.post("/query/", json={"doc_id": "x", "question": "what?"})
        assert resp.status_code == 401

    def test_query_missing_doc_id(self, client, auth_headers):
        """Missing doc_id → 422."""
        resp = client.post("/query/", json={"question": "what?"}, headers=auth_headers)
        assert resp.status_code == 422

    def test_query_missing_question(self, client, auth_headers):
        """Missing question → 422."""
        resp = client.post("/query/", json={"doc_id": "abc"}, headers=auth_headers)
        assert resp.status_code == 422

    def test_query_nonexistent_doc(self, client, auth_headers):
        """doc_id that doesn't exist in DB → 404."""
        resp = client.post("/query/", json={
            "doc_id": "nonexistent-doc-id-99999",
            "question": "What is this?",
        }, headers=auth_headers)
        assert resp.status_code == 404

    def test_query_pending_doc_rejected(self, client, auth_headers):
        """Doc still in pending state → 400 (not ready yet)."""
        upload_resp = do_upload(client, auth_headers)
        doc_id = get_doc_id(upload_resp)

        resp = client.post("/query/", json={
            "doc_id": doc_id,
            "question": "What is this about?",
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "not ready" in resp.json()["detail"].lower()

    def test_query_wrong_owner(self, client, auth_headers, db_session):
        """User B cannot query User A's document → 403."""
        doc_id = make_ready_doc(client, auth_headers, db_session)

        client.post("/auth/register", json=TEST_USER_2)
        login = client.post("/auth/login", data={
            "username": TEST_USER_2["username"],
            "password": TEST_USER_2["password"],
        })
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = client.post("/query/", json={
            "doc_id": doc_id,
            "question": "What is this?",
        }, headers=other_headers)
        assert resp.status_code == 403


# ── Full RAG pipeline ─────────────────────────────────────────────────────────

class TestQueryPipeline:

    def test_query_success_returns_answer(self, client, auth_headers, db_session):
        """
        Full RAG flow with mocked retriever + LLM.
        Verifies response shape, answer present, sources populated.
        """
        doc_id = make_ready_doc(client, auth_headers, db_session)

        with patch("app.routers.query.get_cached_answer", return_value=None), \
             patch("app.routers.query.get_relevant_chunks", return_value=mock_chunks()), \
             patch("app.routers.query.ask_groq", return_value="DocuMind is an AI API."):

            resp = client.post("/query/", json={
                "doc_id": doc_id,
                "question": "What is DocuMind?",
            }, headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["question"] == "What is DocuMind?"
        assert data["answer"]   == "DocuMind is an AI API."
        assert len(data["sources"]) == 2
        assert data["sources"][0]["chunk_index"] == 0

    def test_query_sources_have_correct_fields(self, client, auth_headers, db_session):
        """Each source must have chunk_index and content (your ChunkSource schema)."""
        doc_id = make_ready_doc(client, auth_headers, db_session)

        with patch("app.routers.query.get_cached_answer", return_value=None), \
             patch("app.routers.query.get_relevant_chunks", return_value=mock_chunks()), \
             patch("app.routers.query.ask_groq", return_value="Some answer."):

            resp = client.post("/query/", json={
                "doc_id": doc_id,
                "question": "Explain this.",
            }, headers=auth_headers)

        for source in resp.json()["sources"]:
            assert "chunk_index" in source
            assert "content"     in source

    def test_query_no_chunks_returns_404(self, client, auth_headers, db_session):
        """If retriever returns empty list → 404 'No content found'."""
        doc_id = make_ready_doc(client, auth_headers, db_session)

        with patch("app.routers.query.get_cached_answer", return_value=None), \
             patch("app.routers.query.get_relevant_chunks", return_value=[]):

            resp = client.post("/query/", json={
                "doc_id": doc_id,
                "question": "Anything?",
            }, headers=auth_headers)

        assert resp.status_code == 404
        assert "no content" in resp.json()["detail"].lower()


# ── Redis cache behaviour ─────────────────────────────────────────────────────

class TestQueryCache:

    def test_cache_hit_skips_llm(self, client, auth_headers, db_session):
        """
        When get_cached_answer returns a result,
        ask_groq must NOT be called — your router returns early on cache hit.
        """
        doc_id = make_ready_doc(client, auth_headers, db_session)

        cached = {
            "question": "What is DocuMind?",
            "answer":   "Cached answer from Redis",
            "sources":  [],
        }

        with patch("app.routers.query.get_cached_answer", return_value=cached), \
             patch("app.routers.query.ask_groq") as mock_llm:

            resp = client.post("/query/", json={
                "doc_id": doc_id,
                "question": "What is DocuMind?",
            }, headers=auth_headers)

            mock_llm.assert_not_called()

        assert resp.status_code == 200
        assert resp.json()["answer"] == "Cached answer from Redis"

    def test_cache_miss_calls_llm(self, client, auth_headers, db_session):
        """On cache miss, ask_groq must be called exactly once."""
        doc_id = make_ready_doc(client, auth_headers, db_session)

        with patch("app.routers.query.get_cached_answer", return_value=None), \
             patch("app.routers.query.get_relevant_chunks", return_value=mock_chunks()), \
             patch("app.routers.query.ask_groq", return_value="Fresh answer") as mock_llm, \
             patch("app.routers.query.cache_answer"):

            client.post("/query/", json={
                "doc_id": doc_id,
                "question": "What is this?",
            }, headers=auth_headers)

            mock_llm.assert_called_once()

    def test_cache_answer_called_after_llm(self, client, auth_headers, db_session):
        """After LLM responds, cache_answer must be called to store the result."""
        doc_id = make_ready_doc(client, auth_headers, db_session)

        with patch("app.routers.query.get_cached_answer", return_value=None), \
             patch("app.routers.query.get_relevant_chunks", return_value=mock_chunks()), \
             patch("app.routers.query.ask_groq", return_value="Fresh answer"), \
             patch("app.routers.query.cache_answer") as mock_cache:

            client.post("/query/", json={
                "doc_id": doc_id,
                "question": "What is this?",
            }, headers=auth_headers)

            mock_cache.assert_called_once()
            call_args = mock_cache.call_args[0]
            assert call_args[0] == doc_id
            assert call_args[1] == "What is this?"

    def test_cache_speed_difference(self, client, auth_headers, db_session):
        """
        Cache hit is measurably faster than a full LLM call.
        This is the metric behind your '70%+ latency reduction' resume bullet.
        """
        doc_id = make_ready_doc(client, auth_headers, db_session)

        # Measure: cache miss path (LLM simulates 50ms)
        def slow_llm(*args, **kwargs):
            time.sleep(0.05)
            return "Slow LLM answer"

        with patch("app.routers.query.get_cached_answer", return_value=None), \
             patch("app.routers.query.get_relevant_chunks", return_value=mock_chunks()), \
             patch("app.routers.query.ask_groq", side_effect=slow_llm), \
             patch("app.routers.query.cache_answer"):

            start = time.perf_counter()
            client.post("/query/", json={
                "doc_id": doc_id, "question": "Speed test?",
            }, headers=auth_headers)
            uncached_ms = (time.perf_counter() - start) * 1000

        # Measure: cache hit path (no LLM)
        cached = {"question": "Speed test?", "answer": "Cached answer", "sources": []}

        with patch("app.routers.query.get_cached_answer", return_value=cached), \
             patch("app.routers.query.ask_groq") as mock_llm:

            start = time.perf_counter()
            client.post("/query/", json={
                "doc_id": doc_id, "question": "Speed test?",
            }, headers=auth_headers)
            cached_ms = (time.perf_counter() - start) * 1000
            mock_llm.assert_not_called()

        assert cached_ms < uncached_ms, (
            f"Cache should be faster: "
            f"cached={cached_ms:.1f}ms  uncached={uncached_ms:.1f}ms"
        )