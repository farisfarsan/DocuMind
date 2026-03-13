import redis
import json
from app.core.config import settings

# connect to Redis once at startup
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_cached_answer(doc_id: str, question: str):
    """
    Check if this question was already answered.
    Returns cached answer or None.
    """
    key = f"query:{doc_id}:{question}"
    cached = redis_client.get(key)

    if cached:
        return json.loads(cached)  # convert string back to dict
    return None


def cache_answer(doc_id: str, question: str, answer: dict, ttl: int = 3600):
    """
    Save answer to Redis.
    TTL = 3600 seconds = 1 hour
    """
    key = f"query:{doc_id}:{question}"
    redis_client.setex(key, ttl, json.dumps(answer))  # save as string


def clear_document_cache(doc_id: str):
    """
    Delete all cached answers for a document.
    Used when document is deleted.
    """
    pattern = f"query:{doc_id}:*"
    keys = redis_client.keys(pattern)
    if keys:
        redis_client.delete(*keys)
