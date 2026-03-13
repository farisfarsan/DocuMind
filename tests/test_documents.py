"""
test_documents.py — tests for /documents endpoints

Your router:
  POST   /documents/upload       → 202 { document_id, filename, status, message }
  GET    /documents/             → 200 list[DocumentOut]
  GET    /documents/{id}/status  → 200 { document_id, status }
  DELETE /documents/{id}         → 204

ALLOWED_TYPES = {"application/pdf", "text/plain"}
Ownership enforced via _get_owned_doc → 404 if not found, 403 if wrong owner
"""

import io
import pytest
from tests.conftest import TEST_USER_2


# ── Upload helper ─────────────────────────────────────────────────────────────

def do_upload(client, auth_headers, content=None, filename="test.pdf",
              content_type="application/pdf"):
    if content is None:
        content = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF"
        )
    return client.post(
        "/documents/upload",
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=auth_headers,
    )


def get_doc_id(resp):
    """Extract document_id from upload response."""
    return resp.json().get("document_id") or resp.json().get("id")


# ── Upload ────────────────────────────────────────────────────────────────────

class TestUpload:

    def test_upload_pdf_success(self, client, auth_headers, sample_pdf):
        """Valid PDF → 202 with document_id and pending/processing status."""
        resp = do_upload(client, auth_headers,
                         content=sample_pdf.read_bytes())
        assert resp.status_code == 202
        data = resp.json()
        assert "document_id" in data
        assert data["status"] in ("pending", "processing")
        assert "message" in data

    def test_upload_fires_celery_task(self, client, auth_headers, sample_pdf):
        """Celery task must be triggered on every upload."""
        from unittest.mock import patch
        with patch("app.workers.tasks.ingest_document_task.delay") as mock_delay:
            do_upload(client, auth_headers, content=sample_pdf.read_bytes())
            mock_delay.assert_called_once()

    def test_upload_txt_allowed(self, client, auth_headers):
        """Plain-text files are in ALLOWED_TYPES — should be accepted."""
        resp = client.post(
            "/documents/upload",
            files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
            headers=auth_headers,
        )
        assert resp.status_code == 202

    def test_upload_non_pdf_rejected(self, client, auth_headers):
        """application/octet-stream not in ALLOWED_TYPES → 400."""
        resp = client.post(
            "/documents/upload",
            files={"file": ("bad.exe", b"MZ\x90\x00", "application/octet-stream")},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_upload_image_rejected(self, client, auth_headers):
        """image/jpeg not in ALLOWED_TYPES → 400."""
        resp = client.post(
            "/documents/upload",
            files={"file": ("photo.jpg", b"\xff\xd8\xff", "image/jpeg")},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_upload_requires_auth(self, client, sample_pdf):
        """No token → 401."""
        resp = client.post(
            "/documents/upload",
            files={"file": ("test.pdf", io.BytesIO(sample_pdf.read_bytes()), "application/pdf")},
        )
        assert resp.status_code == 401

    def test_upload_returns_document_id(self, client, auth_headers, sample_pdf):
        """document_id in response must be a non-empty string."""
        resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(resp)
        assert doc_id
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0


# ── Status ────────────────────────────────────────────────────────────────────

class TestDocumentStatus:

    def test_status_after_upload(self, client, auth_headers, sample_pdf):
        """Status endpoint returns valid status string."""
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)

        resp = client.get(f"/documents/{doc_id}/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == doc_id
        assert data["status"] in ("pending", "processing", "ready", "failed")

    def test_status_nonexistent_doc(self, client, auth_headers):
        """Unknown doc_id → 404."""
        resp = client.get("/documents/nonexistent-abc-999/status",
                          headers=auth_headers)
        assert resp.status_code == 404

    def test_status_requires_auth(self, client, auth_headers, sample_pdf):
        """No token → 401."""
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)
        resp = client.get(f"/documents/{doc_id}/status")
        assert resp.status_code == 401

    def test_status_wrong_owner(self, client, auth_headers, sample_pdf):
        """User B cannot see User A's document status → 403."""
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)

        client.post("/auth/register", json=TEST_USER_2)
        login = client.post("/auth/login", data={
            "username": TEST_USER_2["username"],
            "password": TEST_USER_2["password"],
        })
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = client.get(f"/documents/{doc_id}/status", headers=other_headers)
        assert resp.status_code == 403


# ── List ──────────────────────────────────────────────────────────────────────

class TestListDocuments:

    def test_list_empty_for_new_user(self, client, auth_headers):
        """Brand new user has no documents."""
        resp = client.get("/documents/", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_shows_uploaded_doc(self, client, auth_headers, sample_pdf):
        """After upload, doc appears in list."""
        do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        resp = client.get("/documents/", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_multiple_docs(self, client, auth_headers):
        """Upload 3 docs → list returns 3."""
        for i in range(3):
            do_upload(client, auth_headers, filename=f"doc{i}.pdf")
        resp = client.get("/documents/", headers=auth_headers)
        assert len(resp.json()) == 3

    def test_list_only_own_docs(self, client, auth_headers, sample_pdf):
        """User A only sees their own docs, not User B's."""
        do_upload(client, auth_headers, content=sample_pdf.read_bytes())

        client.post("/auth/register", json=TEST_USER_2)
        login = client.post("/auth/login", data={
            "username": TEST_USER_2["username"],
            "password": TEST_USER_2["password"],
        })
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        do_upload(client, other_headers, filename="user2.pdf")

        resp = client.get("/documents/", headers=auth_headers)
        assert len(resp.json()) == 1

    def test_list_requires_auth(self, client):
        """No token → 401."""
        resp = client.get("/documents/")
        assert resp.status_code == 401

    def test_list_doc_has_expected_fields(self, client, auth_headers, sample_pdf):
        """Each item in list has id, filename, status, file_size, uploaded_at."""
        do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        docs = client.get("/documents/", headers=auth_headers).json()
        doc = docs[0]
        assert "id"          in doc
        assert "filename"    in doc
        assert "status"      in doc
        assert "file_size"   in doc
        assert "uploaded_at" in doc


# ── Delete ────────────────────────────────────────────────────────────────────

class TestDeleteDocument:

    def test_delete_success(self, client, auth_headers, sample_pdf):
        """Upload → delete → 204, doc gone from list."""
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)

        del_resp = client.delete(f"/documents/{doc_id}", headers=auth_headers)
        assert del_resp.status_code == 204

        docs = client.get("/documents/", headers=auth_headers).json()
        assert all(d["id"] != doc_id for d in docs)

    def test_delete_clears_redis_cache(self, client, auth_headers, sample_pdf):
        """Deleting a doc must call clear_document_cache (your cache.py function)."""
        from unittest.mock import patch
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)

        with patch("app.routers.documents.clear_document_cache") as mock_clear:
            client.delete(f"/documents/{doc_id}", headers=auth_headers)
            mock_clear.assert_called_once_with(doc_id)

    def test_delete_nonexistent_doc(self, client, auth_headers):
        """Non-existent doc → 404."""
        resp = client.delete("/documents/does-not-exist-xyz", headers=auth_headers)
        assert resp.status_code == 404

    def test_delete_requires_auth(self, client, auth_headers, sample_pdf):
        """No token → 401."""
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)
        resp = client.delete(f"/documents/{doc_id}")
        assert resp.status_code == 401

    def test_delete_wrong_owner(self, client, auth_headers, sample_pdf):
        """User B cannot delete User A's document → 403."""
        upload_resp = do_upload(client, auth_headers, content=sample_pdf.read_bytes())
        doc_id = get_doc_id(upload_resp)

        client.post("/auth/register", json=TEST_USER_2)
        login = client.post("/auth/login", data={
            "username": TEST_USER_2["username"],
            "password": TEST_USER_2["password"],
        })
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = client.delete(f"/documents/{doc_id}", headers=other_headers)
        assert resp.status_code == 403