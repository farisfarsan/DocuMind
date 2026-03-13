import uuid
import os
import aiofiles

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime

from app.core.config import settings
from app.models.db import Document, DocumentStatus, get_db
from app.services.user import get_current_user
from app.workers.tasks import ingest_document_task  # ← NEW (Celery)
from app.models.db import User
from app.core.cache import clear_document_cache      # ← NEW (Redis)

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_TYPES = {"application/pdf", "text/plain"}
MAX_BYTES = settings.MAX_FILE_SIZE_MB * 1024 * 1024


# ── Schema ────────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    filename: str
    file_size: int
    status: DocumentStatus
    uploaded_at: datetime

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=202)
async def upload_document(
    file: UploadFile = File(...),                        # ← REMOVED BackgroundTasks
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ── Step 1: Validate file type ────────────────────────────────────────────
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, detail="Only PDF and plain-text files accepted")

    # ── Step 2: Read and validate file size ───────────────────────────────────
    contents = await file.read()

    if len(contents) > MAX_BYTES:
        raise HTTPException(413, detail=f"File too large — max {settings.MAX_FILE_SIZE_MB}MB")

    # ── Step 3: Generate unique ID and save file to disk ──────────────────────
    doc_id = str(uuid.uuid4())
    ext    = os.path.splitext(file.filename)[1] or ".pdf"
    dest   = os.path.join(settings.UPLOAD_DIR, f"{doc_id}{ext}")

    async with aiofiles.open(dest, "wb") as f:
        await f.write(contents)

    # ── Step 4: Save document record to DB ────────────────────────────────────
    doc = Document(
        id=doc_id,
        filename=file.filename,
        filepath=dest,
        file_size=len(contents),
        status=DocumentStatus.pending,
        owner_id=current_user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # ── Step 5: Send to Celery worker via RabbitMQ ────────────────────────────
    ingest_document_task.delay(doc_id)               # ← NEW ✅

    return {
        "document_id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "message": "Upload received — processing will start shortly",
    }


@router.get("/", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(Document)
        .filter(Document.owner_id == current_user.id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )


@router.get("/{doc_id}/status")
def get_status(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = _get_owned_doc(db, doc_id, current_user.id)
    return {"document_id": doc.id, "status": doc.status}


@router.delete("/{doc_id}", status_code=204)
def delete_document(
    doc_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = _get_owned_doc(db, doc_id, current_user.id)

    # ── Delete file from disk ─────────────────────────────────────────────────
    if os.path.exists(doc.filepath):
        os.remove(doc.filepath)

    # ── Clear Redis cache for this document ───────────────────────────────────
    clear_document_cache(doc_id)                     # ← NEW ✅

    # ── Delete document from DB (cascades to chunks) ──────────────────────────
    db.delete(doc)
    db.commit()


# ── Private helper ────────────────────────────────────────────────────────────

def _get_owned_doc(db: Session, doc_id: str, user_id: int) -> Document:
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, detail="Document not found")
    if doc.owner_id != user_id:
        raise HTTPException(403, detail="Not your document")
    return doc