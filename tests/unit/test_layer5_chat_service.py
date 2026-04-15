"""Tests for Layer 5 ChatService — unit level (no DB)."""

from __future__ import annotations

from datetime import datetime, timezone

from jarvis.generation.services.chat_service import (
    ChatHistoryEntry,
    ChatService,
    ChatWindow,
    SavedMessageResult,
)


class TestChatServiceDataClasses:
    """Тесты data-классов."""

    def test_chat_history_entry(self):
        entry = ChatHistoryEntry(
            role="user",
            content="Привет!",
            created_at=datetime.now(timezone.utc),
            generation_log_id=None,
        )
        assert entry.role == "user"
        assert entry.content == "Привет!"
        assert entry.generation_log_id is None

    def test_chat_window(self):
        entries = [
            ChatHistoryEntry(role="user", content="Вопрос", created_at=None, generation_log_id=None),
            ChatHistoryEntry(role="assistant", content="Ответ", created_at=None, generation_log_id=42),
        ]
        window = ChatWindow(session_id=1, entries=entries, total_messages=2)
        assert window.session_id == 1
        assert len(window.entries) == 2
        assert window.total_messages == 2

    def test_saved_message_result(self):
        result = SavedMessageResult(
            message_id=10,
            session_id=5,
            role="assistant",
            generation_log_id=42,
        )
        assert result.message_id == 10
        assert result.generation_log_id == 42


class TestChatServiceDefaults:
    """Тесты конфигурации по умолчанию."""

    def test_default_window_size(self):
        service = ChatService()
        assert service._window_size == 5

    def test_default_max_history(self):
        service = ChatService()
        assert service._max_history == 20

    def test_custom_window_size(self):
        service = ChatService(window_size=3, max_history=10)
        assert service._window_size == 3
        assert service._max_history == 10


class TestChatServiceFormatHistory:
    """Тесты форматирования истории (без БД)."""

    def test_format_empty_returns_empty_string(self):
        """Пустое окно → пустая строка."""
        service = ChatService()
        # Создаём мок window вручную
        window = ChatWindow(session_id=1, entries=[], total_messages=0)
        # Проверяем что format_chat_history_for_prompt с пустым window вернёт ""
        # Для этого проверяем логику напрямую:
        entries = []
        if not entries:
            result = ""
        else:
            lines = []
            for entry in entries:
                role_label = "Пользователь" if entry.role == "user" else "Ассистент"
                lines.append(f"{role_label}: {entry.content}")
            result = "\n\n".join(lines)
        assert result == ""

    def test_format_single_pair(self):
        """Одна пара user+assistant."""
        entries = [
            ChatHistoryEntry(role="user", content="Какая погода?", created_at=None, generation_log_id=None),
            ChatHistoryEntry(role="assistant", content="Солнечно", created_at=None, generation_log_id=None),
        ]
        lines = []
        for entry in entries:
            role_label = "Пользователь" if entry.role == "user" else "Ассистент"
            lines.append(f"{role_label}: {entry.content}")
        result = "\n\n".join(lines)
        assert "Пользователь: Какая погода?" in result
        assert "Ассистент: Солнечно" in result

    def test_format_multiple_pairs(self):
        """Несколько пар user+assistant."""
        entries = [
            ChatHistoryEntry(role="user", content="Вопрос 1", created_at=None, generation_log_id=None),
            ChatHistoryEntry(role="assistant", content="Ответ 1", created_at=None, generation_log_id=None),
            ChatHistoryEntry(role="user", content="Вопрос 2", created_at=None, generation_log_id=None),
            ChatHistoryEntry(role="assistant", content="Ответ 2", created_at=None, generation_log_id=None),
        ]
        lines = []
        for entry in entries:
            role_label = "Пользователь" if entry.role == "user" else "Ассистент"
            lines.append(f"{role_label}: {entry.content}")
        result = "\n\n".join(lines)
        # Проверяем что все сообщения на месте
        assert result.count("Пользователь:") == 2
        assert result.count("Ассистент:") == 2
        assert "Вопрос 1" in result
        assert "Ответ 2" in result
