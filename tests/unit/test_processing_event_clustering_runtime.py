"""Runtime-oriented tests for Layer 2 event clustering."""

from types import SimpleNamespace

from jarvis.processing.services.event_clustering import (
    find_best_cluster_match,
    resolve_event_cluster_id,
)


def test_find_best_cluster_match_uses_current_dense_vector(monkeypatch) -> None:
    current = SimpleNamespace(id=100, published_at=None)
    candidate_a = SimpleNamespace(id=10, event_cluster_id=10)
    candidate_b = SimpleNamespace(id=20, event_cluster_id=20)

    monkeypatch.setattr(
        "jarvis.processing.services.event_clustering._get_article_dense_vectors",
        lambda news_ids: {10: [1.0, 0.0], 20: [0.0, 1.0]},
    )

    best = find_best_cluster_match(
        current,
        [candidate_a, candidate_b],
        current_dense_vector=[1.0, 0.0],
    )

    assert best is candidate_a


def test_find_best_cluster_match_uses_yandex_story_tag_without_vectors() -> None:
    current = SimpleNamespace(id=100, published_at=None, extra={"yandex_story_tag": "story-1"})
    candidate = SimpleNamespace(id=10, event_cluster_id=7, extra={"yandex_story_tag": "story-1"})

    best = find_best_cluster_match(current, [candidate], current_dense_vector=None)

    assert best is candidate


def test_resolve_event_cluster_id_uses_best_match_cluster(monkeypatch) -> None:
    news = SimpleNamespace(id=50, published_at="stub")
    candidate = SimpleNamespace(id=12, event_cluster_id=7)

    monkeypatch.setattr(
        "jarvis.processing.services.event_clustering.find_cluster_candidates",
        lambda news_obj: [candidate],
    )
    monkeypatch.setattr(
        "jarvis.processing.services.event_clustering.find_best_cluster_match",
        lambda news_obj, candidates, current_dense_vector=None: candidate,
    )

    cluster_id = resolve_event_cluster_id(news, current_dense_vector=[0.1, 0.2])

    assert cluster_id == 7
