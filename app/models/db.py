from sqlalchemy import (
    Column, String, Integer, DateTime, ForeignKey, Enum, BigInteger, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import enum

from pgvector.sqlalchemy import Vector
from app.core.config import settings


# ── Base & Engine ─────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Enums ─────────────────────────────────────────────────────────────────────

class DocumentStatus(str, enum.Enum):
    pending    = "pending"
    processing = "processing"
    ready      = "ready"
    failed     = "failed"


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    email      = Column(String, unique=True, index=True, nullable=False)
    username   = Column(String, unique=True, index=True, nullable=False)
    hashed_pw  = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    documents  = relationship("Document", back_populates="owner", cascade="all, delete")


class Document(Base):
    __tablename__ = "documents"

    id          = Column(String, primary_key=True, index=True)
    filename    = Column(String, nullable=False)
    filepath    = Column(String, nullable=False)
    file_size   = Column(BigInteger, default=0)
    status      = Column(Enum(DocumentStatus), default=DocumentStatus.pending)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    owner_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    owner       = relationship("User", back_populates="documents")
    chunks      = relationship("DocumentChunk", back_populates="document", cascade="all, delete")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id          = Column(Integer, primary_key=True, index=True)
    doc_id      = Column(String, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content     = Column(Text, nullable=False)
    embedding   = Column(Vector(384))

    document    = relationship("Document", back_populates="chunks")