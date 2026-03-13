from app.workers.celery_app import celery_app
from app.models.db import SessionLocal, Document, DocumentChunk, DocumentStatus
from app.services.parser import extract_text_from_pdf, chunk_text
from app.services.embedder import get_embeddings


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="ingest_document"
)
def ingest_document_task(self, doc_id: str):
    """
    Celery task — same pipeline as ingestion.py
    but now runs as a proper background worker.

    bind=True            → gives access to `self` (the task)
    max_retries=3        → retry up to 3 times on failure
    default_retry_delay  → wait 10 seconds between retries
    """

    # ── Step 1: Create fresh DB session ──────────────────────────────────────
    db = SessionLocal()

    try:
        # ── Step 2: Get document from DB ──────────────────────────────────────
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return {"status": "failed", "reason": "document not found"}

        # ── Step 3: Mark as processing ────────────────────────────────────────
        doc.status = DocumentStatus.processing
        db.commit()

        # ── Step 4: Extract text from PDF ─────────────────────────────────────
        text = extract_text_from_pdf(doc.filepath)

        if not text.strip():
            raise ValueError("No text found in document")

        # ── Step 5: Split into chunks ─────────────────────────────────────────
        chunks = chunk_text(text, chunk_size=500, overlap=50)

        # ── Step 6: Generate embeddings ───────────────────────────────────────
        embeddings = get_embeddings(chunks)

        # ── Step 7: Delete old chunks ─────────────────────────────────────────
        db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).delete()

        # ── Step 8: Save chunks + embeddings ─────────────────────────────────
        for index, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = DocumentChunk(
                doc_id=doc_id,
                chunk_index=index,
                content=chunk_text_content,
                embedding=embedding,
            )
            db.add(chunk)

        # ── Step 9: Mark as ready ─────────────────────────────────────────────
        doc.status = DocumentStatus.ready
        db.commit()

        return {"status": "ready", "doc_id": doc_id, "chunks": len(chunks)}

    except Exception as e:
        # ── Retry logic ───────────────────────────────────────────────────────
        try:
            self.retry(exc=e)   # retry up to max_retries times
        except self.MaxRetriesExceededError:
            # all retries failed → mark as failed
            doc.status = DocumentStatus.failed
            db.commit()
            return {"status": "failed", "reason": str(e)}

    finally:
        db.close()   # always close DB session ✅