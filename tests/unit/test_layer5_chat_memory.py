from __future__ import annotations

from jarvis.generation.services.chat_memory_service import ChatMemoryService


class _FakeChatService:
    def format_chat_history_for_prompt(self, session, session_id: int, window_size=None) -> str:
        return "Пользователь: Привет\n\nАссистент: Здравствуйте"

    def load_chat_window(self, session, session_id: int, window_size=None):
        class _Window:
            total_messages = 12
            entries = [
                type("Entry", (), {"role": "user", "content": "вопрос"}),
                type("Entry", (), {"role": "assistant", "content": "ответ"}),
            ] * 3

        return _Window()


class _FakeRedis:
    def __init__(self) -> None:
        self.storage = {}

    def get(self, key: str):
        return self.storage.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.storage[key] = value


def test_chat_memory_builds_block_with_summary() -> None:
    service = ChatMemoryService(chat_service=_FakeChatService())
    service._redis = _FakeRedis()
    service.set_summary(7, "Старый диалог о ставке")

    block = service.build_memory_block(session=None, session_id=7)

    assert "Старый диалог о ставке" in block
    assert "Пользователь: Привет" in block


def test_chat_memory_refresh_summary_if_needed() -> None:
    service = ChatMemoryService(chat_service=_FakeChatService())
    service._redis = _FakeRedis()

    summary = service.refresh_summary_if_needed(session=None, session_id=7)

    assert "вопрос" in summary

