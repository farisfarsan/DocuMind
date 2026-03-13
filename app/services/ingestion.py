from sqlalchemy.orm import Session

from app.models.db import Document, DocumentChunk, DocumentStatus
from app.services.parser import extract_text_from_pdf, chunk_text
from app.services.embedder import get_embeddings


def ingest_document(doc_id: str, db: Session) -> None:
    """
    Full pipeline: PDF → text → chunks → embeddings → saved to DB.
    Called after a document is uploaded.
    """

    # ── Step 1: Get document from DB ─────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        return

    try:
        # ── Step 2: Mark as processing ────────────────────────────────────────
        doc.status = DocumentStatus.processing
        db.commit()

        # ── Step 3: Extract text from PDF ─────────────────────────────────────
        text = extract_text_from_pdf(doc.filepath)

        if not text.strip():
            raise ValueError("No text found in document")

        # ── Step 4: Split into chunks ─────────────────────────────────────────
        chunks = chunk_text(text, chunk_size=500, overlap=50)

        # ── Step 5: Generate embeddings for all chunks ────────────────────────
        embeddings = get_embeddings(chunks)

        # ── Step 6: Delete old chunks if reprocessing ─────────────────────────
        db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).delete()

        # ── Step 7: Save all chunks + embeddings to DB ────────────────────────
        for index, (chunk_text_content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = DocumentChunk(
                doc_id=doc_id,
                chunk_index=index,
                content=chunk_text_content,
                embedding=embedding,
            )
            db.add(chunk)

        # ── Step 8: Mark as ready ─────────────────────────────────────────────
        doc.status = DocumentStatus.ready
        db.commit()

    except Exception as e:
        doc.status = DocumentStatus.failed
        db.commit()
        print(f"[ingestion error] doc_id={doc_id} error={e}")