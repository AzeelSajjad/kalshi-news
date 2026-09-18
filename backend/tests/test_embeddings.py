from unittest.mock import MagicMock, patch

from app.embeddings import EMBED_MODEL, embed_texts


def test_embed_texts_preserves_order_and_uses_the_right_model():
    fake = MagicMock()
    fake.data = [MagicMock(embedding=[0.1] * 1536, index=0),
                 MagicMock(embedding=[0.2] * 1536, index=1)]
    with patch("app.embeddings._client") as client:
        client.embeddings.create.return_value = fake
        vectors = embed_texts(["first", "second"])

    assert len(vectors) == 2
    assert vectors[0][0] == 0.1 and vectors[1][0] == 0.2
    assert client.embeddings.create.call_args.kwargs["model"] == EMBED_MODEL


def test_embed_texts_returns_empty_for_empty_input():
    assert embed_texts([]) == []
