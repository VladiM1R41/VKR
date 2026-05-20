from jarvis.processing.services.chunking import build_chunks
from jarvis.processing.services.grading import derive_content_grade, derive_uncertainty


def test_build_chunks_includes_title_and_body_segments() -> None:
    chunks = build_chunks(
        title="Important title",
        body="First sentence. Second sentence. Third sentence.",
    )

    assert len(chunks) >= 2
    assert chunks[0].zone == "title"
    assert chunks[0].text == "Important title"
    assert all(chunk.total_chunks == len(chunks) for chunk in chunks)
    assert any(chunk.zone == "body" for chunk in chunks)


def test_build_chunks_falls_back_to_snippet_when_body_missing() -> None:
    chunks = build_chunks(
        title="Fallback title",
        body=None,
        fallback_body="Fallback lead sentence.",
    )

    assert len(chunks) == 2
    assert chunks[1].zone == "body"
    assert chunks[1].text == "Fallback lead sentence."


def test_body_chunk_lemma_text_matches_chunk_span() -> None:
    body = " ".join(
        f"Section {index} marker{index} contains enough words to build a long article chunk for retrieval quality."
        for index in range(90)
    )

    chunks = build_chunks(title="Chunking title", body=body)
    body_chunks = [chunk for chunk in chunks if chunk.zone == "body"]

    assert len(body_chunks) > 2
    assert body_chunks[1].char_start > body_chunks[0].char_start
    assert "marker0" not in body_chunks[1].lemma_text
    assert "marker0" not in body_chunks[2].lemma_text
    assert body[body_chunks[1].char_start:body_chunks[1].char_end].strip() == body_chunks[1].text


def test_grade_and_uncertainty_follow_mvp_rules() -> None:
    assert derive_content_grade(reliability="A", cluster_source_count=2) == 1
    assert derive_content_grade(reliability="C", cluster_source_count=1) == 3
    assert derive_content_grade(reliability="E", cluster_source_count=1) == 4
    assert derive_content_grade(reliability="E", cluster_source_count=3) == 4
    assert derive_content_grade(reliability="B", cluster_source_count=2, has_contradiction=True) == 5

    assert derive_uncertainty(reliability="E", cluster_source_count=1) is True
    assert derive_uncertainty(reliability="B", cluster_source_count=3) is False
