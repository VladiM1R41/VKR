"""Qdrant integration helpers for Layer 2.

MVP: только dense vectors. Коллекция создаётся без sparse_vectors_config,
потому что общий token→index словарь (term_vocabulary) ещё не построен.
После реализации term_vocabulary — добавим sparse через reindex.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.core.settings import get_settings


@dataclass(frozen=True, slots=True)
class IndexedChunk:
    """Chunk payload plus vectors ready for Qdrant upsert."""

    point_id: str
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    payload: dict[str, Any]


class QdrantIndexer:
    """Thin lazy-import wrapper around the Qdrant client."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def _client(self):
        from qdrant_client import QdrantClient

        return QdrantClient(url=self._settings.qdrant_url)

    def ensure_collection(self) -> None:
        from qdrant_client import models

        client = self._client()
        alias = self._settings.qdrant_collection_alias
        collections = {collection.name for collection in client.get_collections().collections}
        if alias in collections:
            return

        # Dense + sparse vectors
        client.create_collection(
            collection_name=alias,
            vectors_config={
                "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(),
            },
        )

        # Payload indexes для фильтрации при поиске
        payload_indexes = {
            "news_id": "integer",
            "source_id": "integer",
            "language": "keyword",
            "zone": "keyword",
            "urgency": "keyword",
            "information_type": "keyword",
            "content_grade": "integer",
            "event_cluster_id": "integer",
            "published_at": "datetime",     # date-range filtering
            "topics": "keyword",            # array filtering
            "entities": "keyword",          # array filtering
            "keywords": "keyword",          # array filtering
        }
        for field_name, field_schema in payload_indexes.items():
            try:
                client.create_payload_index(
                    collection_name=alias,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            except Exception:
                pass  # индекс может уже существовать

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return

        from qdrant_client import models

        client = self._client()
        client.delete(
            collection_name=self._settings.qdrant_collection_alias,
            points_selector=models.PointIdsList(points=point_ids),
        )

    def upsert_chunks(self, chunks: list[IndexedChunk]) -> None:
        if not chunks:
            return

        from qdrant_client import models

        client = self._client()
        points = []
        for chunk in chunks:
            vectors = {
                "dense": chunk.dense_vector,
            }
            # Добавляем sparse если есть данные
            if chunk.sparse_indices and chunk.sparse_values:
                vectors["sparse"] = models.SparseVector(
                    indices=chunk.sparse_indices,
                    values=chunk.sparse_values,
                )
            point = models.PointStruct(
                id=chunk.point_id,
                vector=vectors,
                payload=chunk.payload,
            )
            points.append(point)
        client.upsert(collection_name=self._settings.qdrant_collection_alias, points=points)

    def update_entity_payload(
        self,
        point_ids: list[str],
        entity_names: list[str],
        entity_ids: list[int],
    ) -> None:
        """Обновить entity_ids/entities в payload чанков после commit в PostgreSQL.

        Вызывается вторым проходом из process_article: сначала upsert_chunks с пустыми
        entity_ids (чтобы не блокировать сохранение), потом этот метод — после flush entities.
        Использует Qdrant set_payload, который обновляет только указанные поля без
        повторной передачи векторов.
        """
        if not point_ids:
            return

        client = self._client()
        client.set_payload(
            collection_name=self._settings.qdrant_collection_alias,
            payload={"entities": entity_names, "entity_ids": entity_ids},
            points=point_ids,
        )
