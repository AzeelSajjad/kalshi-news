from unittest.mock import MagicMock, patch

from app.embeddings import EMBED_MODEL, embed_texts


def test_embed_texts_preserves_order_despite_out_of_order_response():
    """Verify that vectors are returned in input order, not response order.

    OpenAI's batch embeddings endpoint does not guarantee response order
    matches request order. This test returns items out of order and asserts
    the result is sorted by index before returning.
    """
    fake = MagicMock()
    # Return items OUT OF ORDER: index=1 first, then index=0
    # Use distinguishable values to pin which embedding is which
    fake.data = [MagicMock(embedding=[0.2] * 1536, index=1),
                 MagicMock(embedding=[0.1] * 1536, index=0)]
    with patch("app.embeddings._client") as client:
        client.embeddings.create.return_value = fake
        vectors = embed_texts(["first", "second"])

    # Assert vectors come back in input order, not response order
    assert len(vectors) == 2
    assert vectors[0][0] == 0.1, "First vector should match index=0 item"
    assert vectors[1][0] == 0.2, "Second vector should match index=1 item"
    assert client.embeddings.create.call_args.kwargs["model"] == EMBED_MODEL


def test_embed_texts_batches_correctly_at_boundary():
    """Verify that batching splits at BATCH_SIZE=256 correctly.

    Tests the loop with 300 inputs, expecting two calls:
    - First call with 256 items
    - Second call with 44 items
    Verifies all 300 vectors are returned in input order.
    """
    # Create a mock that returns different results for each call
    first_call_response = MagicMock()
    first_call_response.data = [
        MagicMock(embedding=[0.1 + i*0.0001] * 1536, index=i)
        for i in range(256)
    ]

    second_call_response = MagicMock()
    second_call_response.data = [
        MagicMock(embedding=[0.2 + i*0.0001] * 1536, index=i)
        for i in range(44)
    ]

    with patch("app.embeddings._client") as client:
        client.embeddings.create.side_effect = [first_call_response, second_call_response]

        # Request 300 items
        inputs = [f"text_{i}" for i in range(300)]
        vectors = embed_texts(inputs)

    # Verify two calls were made
    assert client.embeddings.create.call_count == 2

    # Verify first call had 256 items
    first_call_input = client.embeddings.create.call_args_list[0].kwargs["input"]
    assert len(first_call_input) == 256

    # Verify second call had 44 items
    second_call_input = client.embeddings.create.call_args_list[1].kwargs["input"]
    assert len(second_call_input) == 44

    # Verify all 300 vectors returned in input order
    assert len(vectors) == 300
    assert vectors[0][0] == 0.1, "First vector from first batch"
    assert vectors[255][0] > 0.1, "Last vector from first batch"
    assert vectors[256][0] == 0.2, "First vector from second batch"
    assert vectors[299][0] > 0.2, "Last vector from second batch"


def test_embed_texts_returns_empty_for_empty_input():
    assert embed_texts([]) == []
