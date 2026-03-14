# DocuMind 🧠
### AI Document Intelligence API


<p align="center">
  <b>Upload a PDF. Ask anything. Get AI-powered answers with source references.</b><br/>
  A production-grade RAG backend built with distributed systems, async workers, and semantic search.
</p>

Working Video:[https://www.loom.com/share/29bfce3333574325ac6de4383cb31569](https://www.loom.com/share/951e5621f4f343c2af4630955d3f0335)

---

## What Is DocuMind?

DocuMind is a backend API that lets you upload PDF documents and query them using natural language. It combines:

- **Semantic search** via pgvector to find the most relevant chunks of your document
- **LLM answer generation** via Groq (llama-3.3-70b) to produce accurate, grounded answers
- **Async processing** via Celery + RabbitMQ so uploads are non-blocking
- **Redis caching** so repeated queries return in milliseconds instead of seconds

Companies like Notion AI, ChatPDF, and Adobe Acrobat AI are built on this exact pattern.

---

## Architecture

```
                        ┌──────────────┐
                        │    Client    │
                        └──────┬───────┘
                               │ HTTPS
                        ┌──────▼───────────────────────┐
                        │     FastAPI  (port 8000)      │
                        │  JWT Auth | Routers | Schemas │
                        └──┬────────┬──────────┬────────┘
                           │        │          │
               ┌───────────▼──┐  ┌──▼────┐  ┌─▼───────────┐
               │  PostgreSQL  │  │ Redis │  │  RabbitMQ   │
               │  + pgvector  │  │ Cache │  │   Queue     │
               │  (vectors +  │  │ 1hr   │  └──────┬──────┘
               │   chunks)    │  │  TTL  │         │
               └──────────────┘  └───────┘  ┌──────▼──────┐
                                             │Celery Worker│
                                             │PDF → chunks │
                                             │→ embeddings │
                                             └──────┬──────┘
                                                    │
                                    ┌───────────────▼─────────────┐
                                    │  HuggingFace all-MiniLM-L6  │
                                    │  384-dim vectors (offline)  │
                                    └───────────────┬─────────────┘
                                                    │
                                    ┌───────────────▼─────────────┐
                                    │     Groq  llama-3.3-70b     │
                                    │     LLM Answer Generation   │
                                    └─────────────────────────────┘
```

### Request Flow

**Upload (non-blocking):**
```
POST /documents/upload
  → Save file to disk
  → Create DB record (status: pending)
  → Fire Celery task via RabbitMQ  ← returns doc_id immediately
        (background worker)
  → Extract text → chunk (500 words, 50 overlap)
  → Generate embeddings → store in pgvector
  → Update status: ready
```

**Query (RAG pipeline):**
```
POST /query/
  → Check Redis cache           ← return instantly if hit
  → Embed question (384-dim)
  → Cosine similarity search in pgvector (top 5 chunks)
  → Build prompt: chunks + question
  → Send to Groq LLM
  → Cache result (TTL: 1 hour)
  → Return answer + source references
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API | FastAPI + JWT | Async, fast, auto-docs |
| Task Queue | Celery + RabbitMQ | Decouples upload from processing |
| Vector DB | PostgreSQL + pgvector | Cosine similarity at scale |
| Cache | Redis | 70%+ latency reduction on repeat queries |
| Embeddings | HuggingFace all-MiniLM-L6-v2 | Fully offline, 384-dim, fast |
| LLM | Groq llama-3.3-70b | Fast inference, free tier |
| Containers | Docker Compose | One-command setup, 5 services |
| Testing | PyTest + GitHub Actions | 54 tests, CI on every push |

---

## Quick Start

### Prerequisites
- [Docker + Docker Compose](https://docs.docker.com/get-docker/)
- Python 3.11+
- Groq API key — free at [console.groq.com](https://console.groq.com)

### 1. Clone
```bash
git clone https://github.com/farisfarsan/DocuMind.git
cd DocuMind
```

### 2. Configure
```bash
cp .env.example .env
```
Open `.env` and set:
```env
GROQ_API_KEY=your_groq_api_key_here
SECRET_KEY=any-random-secret-string
```

### 3. Start all 5 services
```bash
docker compose up -d
```

### 4. Verify
```bash
curl http://localhost:8000/
# {"status": "ok", "message": "DocuMind API is running"}
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## API Reference

### Auth

**Register**
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "username": "yourname", "password": "pass123"}'

# 201
{"message": "Account created", "username": "yourname"}
```

**Login**
```bash
curl -X POST http://localhost:8000/auth/login \
  -d "username=yourname&password=pass123"

# 200
{"access_token": "eyJhbGciOiJIUzI1NiJ9...", "token_type": "bearer"}
```

---

### Documents

**Upload PDF**
```bash
curl -X POST http://localhost:8000/documents/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@report.pdf"

# 202 - returns immediately, processing happens in background
{
  "document_id": "3f7a1c2e-...",
  "filename": "report.pdf",
  "status": "pending",
  "message": "Upload received - processing will start shortly"
}
```

**Check Status**
```bash
curl http://localhost:8000/documents/3f7a1c2e-.../status \
  -H "Authorization: Bearer YOUR_TOKEN"

# pending -> processing -> ready -> (failed)
{"document_id": "3f7a1c2e-...", "status": "ready"}
```

**List Documents**
```bash
curl http://localhost:8000/documents/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Delete Document**
```bash
curl -X DELETE http://localhost:8000/documents/3f7a1c2e-... \
  -H "Authorization: Bearer YOUR_TOKEN"
# 204 - also clears Redis cache for this document
```

---

### Query (RAG)

**Ask a Question**
```bash
curl -X POST http://localhost:8000/query/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"doc_id": "3f7a1c2e-...", "question": "What are the key findings?"}'

# 200
{
  "question": "What are the key findings?",
  "answer": "The key findings include three main points: first...",
  "sources": [
    {"chunk_index": 2, "content": "The analysis revealed that..."},
    {"chunk_index": 7, "content": "Furthermore, the data shows..."}
  ]
}
```

> Ask the same question twice — the second response returns from Redis instantly with no LLM call.

**Generate Summary**
```bash
curl -X POST http://localhost:8000/summary/3f7a1c2e-... \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Query History**
```bash
curl http://localhost:8000/query/history/3f7a1c2e-... \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Performance

| Scenario | Latency |
|---|---|
| Upload (returns doc_id) | ~50ms |
| Query - cache miss (LLM call) | ~1-3s |
| Query - cache hit (Redis) | ~10-30ms |
| Embedding generation | ~100ms (local) |

Redis caching reduces repeated query latency by **70%+** — verified by automated speed tests in the pytest suite.

---

## Running Tests

```bash
# Install test deps
pip install -r requirements-test.txt

# Start services
docker compose up -d postgres redis
docker exec documind_postgres createdb -U postgres documind_test

# Run all 54 tests
python -m pytest

# With coverage report
python -m pytest --cov=app --cov-report=term-missing
```

| File | Tests | Covers |
|---|---|---|
| `test_auth.py` | 19 | Register, login, JWT, protected routes |
| `test_documents.py` | 17 | Upload, status, list, delete, ownership |
| `test_query.py` | 17 | RAG pipeline, cache hit/miss, speed benchmark |

---

## Project Structure

```
documind/
├── app/
│   ├── main.py                  # FastAPI app + middleware
│   ├── routers/
│   │   ├── auth.py              # JWT register / login
│   │   ├── documents.py         # upload, list, status, delete
│   │   └── query.py             # RAG query pipeline
│   ├── services/
│   │   ├── parser.py            # PyMuPDF text extraction + chunking
│   │   ├── embedder.py          # HuggingFace embedding wrapper
│   │   ├── retriever.py         # pgvector cosine similarity search
│   │   └── llm.py               # Groq prompt builder + response
│   ├── workers/
│   │   ├── celery_app.py        # Celery + RabbitMQ config
│   │   └── tasks.py             # ingest_document_task
│   ├── models/
│   │   └── db.py                # SQLAlchemy models
│   └── core/
│       ├── config.py            # Pydantic settings
│       ├── cache.py             # Redis helpers
│       └── security.py          # JWT + bcrypt
├── tests/
│   ├── conftest.py              # fixtures, test DB, mocks
│   ├── test_auth.py
│   ├── test_documents.py
│   └── test_query.py
├── docker-compose.yml           # 5 services
├── Dockerfile
├── requirements.txt
├── requirements-test.txt
├── pytest.ini
└── .github/workflows/ci.yml     # GitHub Actions CI
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | JWT signing secret |
| `GROQ_API_KEY` | Groq API key (free at console.groq.com) |
| `REDIS_URL` | Redis connection string |
| `RABBITMQ_URL` | RabbitMQ connection string |
| `UPLOAD_DIR` | File storage path |
| `MAX_FILE_SIZE_MB` | Max upload size (default: 20) |

---



## Built By

**Faris Farsan M** — Backend Engineer



---

MIT License
