from openai import OpenAI

from app.config import get_settings

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 256

_client = OpenAI(api_key=get_settings().openai_api_key or "unset")


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        response = _client.embeddings.create(model=EMBED_MODEL, input=batch)
        if len(response.data) != len(batch):
            raise RuntimeError(
                f"embeddings API returned {len(response.data)} vectors "
                f"for {len(batch)} inputs"
            )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors
