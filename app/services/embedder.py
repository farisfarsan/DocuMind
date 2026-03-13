from sentence_transformers import SentenceTransformer
from typing import List

# Load the model once when the module is first imported.
# This takes ~2 seconds on first load, then stays in memory.
model = SentenceTransformer("all-MiniLM-L6-v2")


def get_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Convert a list of text chunks into a list of vectors.
    Each vector is a list of 384 floats.
    """
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def get_single_embedding(text: str) -> List[float]:
    """
    Convert a single piece of text into a vector.
    Used later in Week 3 when we embed the user's question.
    """
    embedding = model.encode([text], show_progress_bar=False)
    return embedding[0].tolist()