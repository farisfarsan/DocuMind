"""
conftest.py — shared fixtures for all DocuMind tests

Matches your exact code:
- cache.py       → redis_client, get_cached_answer, cache_answer, clear_document_cache
- tasks.py       → ingest_document_task.delay
- routers/auth   → /auth/register, /auth/login (OAuth2PasswordRequestForm)
- routers/docs   → /documents/upload, list, status, delete
- routers/query  → /query/ (doc_id + question)
- services/llm   → ask_groq
- services/retriever → get_relevant_chunks
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ── Set env vars BEFORE any app import ───────────────────────────────────────
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/documind_test"
)
os.environ["SECRET_KEY"]                  = "test-secret-key-not-for-production"
os.environ["REDIS_URL"]                   = "redis://localhost:6379/1"
os.environ["RABBITMQ_URL"]                = "amqp://guest:guest@localhost:5672//"
os.environ["GROQ_API_KEY"]                = "test-groq-key"
os.environ["UPLOAD_DIR"]                  = "/tmp/documind_test_uploads"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
os.environ["ALGORITHM"]                   = "HS256"

os.makedirs("/tmp/documind_test_uploads", exist_ok=True)

from app.models.db import Base, get_db
from app.main import app

# ── DB setup ──────────────────────────────────────────────────────────────────

TEST_DB_URL = os.environ["DATABASE_URL"]
engine = create_engine(TEST_DB_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Once per session: create pgvector extension + all tables."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    """Each test gets a rolled-back session — no data bleeds between tests."""
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    """
    TestClient with:
    - DB overridden to test session
    - redis_client mocked (matches your cache.py)
    - ingest_document_task.delay mocked (matches your tasks.py)
    """
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    with patch("app.core.cache.redis_client") as mock_redis, \
         patch("app.workers.tasks.ingest_document_task.delay") as mock_task:

        # Default: cache miss
        mock_redis.get.return_value = None
        mock_redis.setex.return_value = True
        mock_redis.keys.return_value = []
        mock_redis.delete.return_value = 1

        mock_task.return_value = MagicMock(id="test-task-id")

        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

    app.dependency_overrides.clear()


# ── Reusable test users ───────────────────────────────────────────────────────

TEST_USER = {
    "email": "test@documind.com",
    "username": "testuser",
    "password": "SecurePass123!",
}

TEST_USER_2 = {
    "email": "other@documind.com",
    "username": "otheruser",
    "password": "OtherPass456!",
}


@pytest.fixture()
def registered_user(client):
    """Register TEST_USER and return response JSON."""
    resp = client.post("/auth/register", json=TEST_USER)
    assert resp.status_code == 201, f"Register failed: {resp.json()}"
    return resp.json()


@pytest.fixture()
def auth_headers(client, registered_user):
    """Login as TEST_USER and return Bearer auth headers."""
    resp = client.post("/auth/login", data={
        "username": TEST_USER["username"],
        "password": TEST_USER["password"],
    })
    assert resp.status_code == 200, f"Login failed: {resp.json()}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def sample_pdf(tmp_path):
    """Write a minimal but valid PDF to a temp file."""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 44>>\nstream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello DocuMind) Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f\n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n0\n%%EOF"
    )
    return pdf_path