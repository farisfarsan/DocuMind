from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.models.db import Document, DocumentStatus, get_db
from app.services.user import get_current_user
from app.services.retriever import get_relevant_chunks
from app.services.llm import ask_groq
from app.models.db import User
from app.core.cache import get_cached_answer, cache_answer  # ← NEW

router = APIRouter(prefix="/query", tags=["Query"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    doc_id: str
    question: str


class ChunkSource(BaseModel):
    chunk_index: int
    content: str


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[ChunkSource]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/", response_model=QueryResponse)
def query_document(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ── Step 1: Check document exists and belongs to user ─────────────────────
    doc = db.query(Document).filter(Document.id == payload.doc_id).first()

    if not doc:
        raise HTTPException(404, detail="Document not found")
    if doc.owner_id != current_user.id:
        raise HTTPException(403, detail="Not your document")

    # ── Step 2: Check document is ready ───────────────────────────────────────
    if doc.status != DocumentStatus.ready:
        raise HTTPException(
            400,
            detail=f"Document is not ready yet — current status: {doc.status}"
        )

    # ── Step 3: Check Redis cache ─────────────────────────────────────────────
    cached = get_cached_answer(payload.doc_id, payload.question)
    if cached:
        return cached  # ← return instantly, skip RAG pipeline ⚡

    # ── Step 4: Find relevant chunks via similarity search ────────────────────
    chunks = get_relevant_chunks(
        doc_id=payload.doc_id,
        question=payload.question,
        db=db,
        top_k=5
    )

    if not chunks:
        raise HTTPException(404, detail="No content found in this document")

    # ── Step 5: Send chunks + question to Groq ────────────────────────────────
    answer = ask_groq(
        question=payload.question,
        chunks=chunks
    )

    # ── Step 6: Build response ────────────────────────────────────────────────
    response = QueryResponse(
        question=payload.question,
        answer=answer,
        sources=[
            ChunkSource(
                chunk_index=chunk.chunk_index,
                content=chunk.content
            )
            for chunk in chunks
        ]
    )

    # ── Step 7: Save to Redis cache ───────────────────────────────────────────
    cache_answer(payload.doc_id, payload.question, response.dict())

    return response