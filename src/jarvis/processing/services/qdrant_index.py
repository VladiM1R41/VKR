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
        self._client_instance: Any | None = None
        self._ensured_collections: set[str] = set()

    def _client(self):
        from qdrant_client import QdrantClient

        if self._client_instance is None:
            self._client_instance = QdrantClient(url=self._settings.qdrant_url)
        return self._client_instance

    def ensure_collection(self) -> None:
        self._ensure_collection_named(self._settings.qdrant_collection_alias)

    def _ensure_collection_named(self, collection_name: str) -> None:
        from qdrant_client import models

        if collection_name in self._ensured_collections:
            return

        client = self._client()
        collections = {collection.name for collection in client.get_collections().collections}
        if collection_name in collections:
            self._ensured_collections.add(collection_name)
            return

        # Dense + sparse vectors
        client.create_collection(
            collection_name=collection_name,
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
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            except Exception:
                pass  # индекс может уже существовать
        self._ensured_collections.add(collection_name)

    def ensure_versioned_collection(self, collection_name: str) -> None:
        """Create a versioned collection for manual reindex runs."""

        self._ensure_collection_named(collection_name)

    def switch_alias(self, *, alias_name: str, target_collection: str) -> None:
        """Switch a Qdrant alias to a prepared versioned collection."""

        from qdrant_client import models

        client = self._client()
        operations = [
            models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias_name)),
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    alias_name=alias_name,
                    collection_name=target_collection,
                )
            ),
        ]
        client.update_collection_aliases(change_aliases_operations=operations)

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return

        from qdrant_client import models

        client = self._client()
        client.delete(
            collection_name=self._settings.qdrant_collection_alias,
            points_selector=models.PointIdsList(points=point_ids),
        )

    def list_point_ids_for_news(self, news_id: int) -> list[str]:
        """Return all Qdrant point ids currently indexed for one article."""

        from qdrant_client import models

        client = self._client()
        point_ids: list[str] = []
        offset = None
        news_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="news_id",
                    match=models.MatchValue(value=news_id),
                )
            ]
        )

        while True:
            points, offset = client.scroll(
                collection_name=self._settings.qdrant_collection_alias,
                scroll_filter=news_filter,
                limit=256,
                offset=offset,
                with_payload=False,
                with_vectors=False,
            )
            point_ids.extend(str(point.id) for point in points)
            if offset is None:
                break

        return point_ids

    def delete_stale_points_for_news(self, news_id: int, *, keep_point_ids: set[str]) -> int:
        """Delete Qdrant points for news_id that are not part of the expected chunk set."""

        current_point_ids = self.list_point_ids_for_news(news_id)
        stale_point_ids = [point_id for point_id in current_point_ids if point_id not in keep_point_ids]
        self.delete_points(stale_point_ids)
        return len(stale_point_ids)

    def retrieve_existing_point_ids(self, point_ids: list[str]) -> set[str]:
        """Return subset of point ids that exists in Qdrant."""

        if not point_ids:
            return set()

        client = self._client()
        existing: set[str] = set()
        for start in range(0, len(point_ids), 256):
            batch = point_ids[start : start + 256]
            points = client.retrieve(
                collection_name=self._settings.qdrant_collection_alias,
                ids=batch,
                with_payload=False,
                with_vectors=False,
            )
            existing.update(str(point.id) for point in points)
        return existing

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

    def update_payload(self, point_ids: list[str], payload: dict[str, Any]) -> None:
        """Update arbitrary payload fields for existing points."""

        if not point_ids:
            return

        client = self._client()
        client.set_payload(
            collection_name=self._settings.qdrant_collection_alias,
            payload=payload,
            points=point_ids,
        )

    def count_points(self) -> int:
        """Return approximate collection point count."""

        client = self._client()
        result = client.count(
            collection_name=self._settings.qdrant_collection_alias,
            exact=True,
        )
        return int(result.count)
