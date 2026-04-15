"""Tests for Layer 3 query preprocessing."""

from jarvis.processing.services.embedding_runtime import EmbeddingOutput
from jarvis.retrieval.services.intent_classifier import IntentResult
from jarvis.retrieval.services.query_preprocessing import preprocess_query


def test_preprocess_query_uses_lemma_for_sparse_embedding(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "jarvis.retrieval.services.query_preprocessing.lemmatize_text",
        lambda query: "ключевая ставка",
    )
    monkeypatch.setattr(
        "jarvis.retrieval.services.query_preprocessing.classify_intent",
        lambda query: IntentResult(intent="FACTUAL", confidence=0.9, method="rule-based"),
    )

    def fake_encode_texts(texts, *, sparse_texts=None):
        captured["texts"] = texts
        captured["sparse_texts"] = sparse_texts
        return [
            EmbeddingOutput(
                dense_vector=[0.1, 0.2],
                sparse_indices=[11, 42],
                sparse_values=[0.3, 0.7],
            )
        ]

    monkeypatch.setattr(
        "jarvis.retrieval.services.query_preprocessing.encode_texts",
        fake_encode_texts,
    )

    ctx = preprocess_query("ключевой ставке")

    assert captured["texts"] == ["ключевой ставке"]
    assert captured["sparse_texts"] == ["ключевая ставка"]
    assert ctx.original == "ключевой ставке"
    assert ctx.lemma == "ключевая ставка"
    assert ctx.intent.intent == "FACTUAL"
    assert ctx.dense_vector == [0.1, 0.2]
    assert ctx.sparse_indices == [11, 42]
    assert ctx.sparse_values == [0.3, 0.7]
