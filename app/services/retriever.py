from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector
from app.models.db import DocumentChunk
from app.services.embedder import get_single_embedding


def get_relevant_chunks(doc_id: str, question: str, db: Session, top_k: int = 5):
    """
    Convert the question to a vector, then find the top_k most
    similar chunks from the document using cosine similarity.
    """

    # Step 1 — convert question to vector
    question_vector = get_single_embedding(question)

    # Step 2 — search pgvector for closest chunks
    results = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.doc_id == doc_id)
        .order_by(DocumentChunk.embedding.cosine_distance(question_vector))
        .limit(top_k)
        .all()
    )

    return results
