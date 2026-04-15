from pathlib import Path

from jarvis.db.models.chat_message import ChatMessage
from jarvis.db.models.chat_session import ChatSession
from jarvis.db.models.digest import Digest
from jarvis.db.models.generation_log import GenerationLog


def test_layer5_model_primary_keys_match_contract() -> None:
    assert list(ChatSession.__table__.primary_key.columns.keys()) == ["id"]
    assert list(ChatMessage.__table__.primary_key.columns.keys()) == ["id"]
    assert list(GenerationLog.__table__.primary_key.columns.keys()) == ["id"]


def test_layer5_model_columns_match_contract() -> None:
    assert "generation_log_id" in ChatMessage.__table__.columns
    assert "documents_used" in GenerationLog.__table__.columns
    assert "prompt_version" in GenerationLog.__table__.columns
    assert "confidence" in GenerationLog.__table__.columns
    assert "generation_log_id" in Digest.__table__.columns


def test_layer5_migration_contains_expected_tables() -> None:
    migration = Path("alembic/versions/20260414_0006_layer5_generation_schema.py").read_text(encoding="utf-8")
    for table_name in [
        "chat_sessions",
        "chat_messages",
        "generation_logs",
    ]:
        assert f'"{table_name}"' in migration
    assert '"fk_digests_generation_log"' in migration
