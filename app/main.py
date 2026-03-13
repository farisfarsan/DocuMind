from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.routers import auth, documents, query
from app.models.db import Base, engine

# Enable pgvector extension FIRST (before creating tables)
with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()

# Creates all tables in PostgreSQL on startup
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="DocuMind API",
    description="AI Document Intelligence — Week 3: RAG Query Pipeline",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(query.router)


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "message": "DocuMind API is running 🚀"}