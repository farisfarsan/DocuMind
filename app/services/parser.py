import fitz  # PyMuPDF
from typing import List


def extract_text_from_pdf(filepath: str) -> str:
    """Open a PDF and extract all text from every page as one big string."""
    doc = fitz.open(filepath)
    full_text = ""

    for page in doc:
        full_text += page.get_text()

    doc.close()
    return full_text.strip()


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """
    Split text into overlapping chunks by word count.

    chunk_size = max words per chunk
    overlap    = how many words to repeat at the start of the next chunk
    """
    words  = text.split()
    chunks = []
    start  = 0

    while start < len(words):
        end   = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start = end - overlap  # step back by overlap amount

    return chunks
