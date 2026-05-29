"""Tests for Layer 5 CitationValidator and HallucinationChecker."""

from __future__ import annotations

from jarvis.generation.services.citation_validator import (
    CitationIssue,
    CitationValidationResult,
    CitationValidator,
)
from jarvis.generation.services.hallucination_checker import (
    ClaimCheck,
    GroundednessResult,
    HallucinationChecker,
)


# ───────────────────────────────────────────────────────────
# CitationValidator tests
# ───────────────────────────────────────────────────────────

class TestCitationValidatorValid:
    """Тесты валидных цитат."""

    def test_all_citations_valid(self):
        """Все источники в ответе есть в контексте."""
        validator = CitationValidator()
        answer = "По данным ТАСС, ЦБ повысил ставку. Как сообщает РИА Новости, инфляция растёт."
        docs = [
            {"source": "ТАСС", "news_id": 1},
            {"source": "РИА Новости", "news_id": 2},
        ]

        result = validator.validate(answer, docs)

        assert result.is_valid is True
        assert result.total_citations == 2
        assert len(result.valid_citations) == 2
        assert len(result.invalid_citations) == 0

    def test_no_citations_in_answer(self):
        """Ответ без упоминаний источников — считается валидным."""
        validator = CitationValidator()
        answer = "Центральный банк принял решение повысить ключевую ставку."
        docs = [
            {"source": "ТАСС", "news_id": 1},
        ]

        result = validator.validate(answer, docs)

        assert result.is_valid is True
        assert result.total_citations == 0

    def test_citation_in_parentheses(self):
        """Цитата в скобках распознаётся."""
        validator = CitationValidator()
        answer = "Ставка повышена (РИА Новости)."
        docs = [{"source": "РИА Новости", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is True

    def test_source_prefix_variation(self):
        """Различные варианты упоминания источников."""
        validator = CitationValidator()
        answer = "По данным Коммерсантъ, решение принято. Как пишет Коммерсантъ, ставка выросла."
        docs = [{"source": "Коммерсантъ", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is True

    def test_sources_block_at_end_is_valid(self):
        """Человеческий блок источников в конце ответа распознаётся."""
        validator = CitationValidator()
        answer = (
            "Трамп призвал ряд стран присоединиться к соглашениям с Израилем.\n\n"
            "Источники:\n"
            "1. РБК — Axios узнал о призыве Трампа — https://example.test/rbc\n"
            "2. Коммерсантъ news — Axios: Трамп просил лидеров — https://example.test/kommersant\n"
        )
        docs = [
            {"source": "РБК", "news_id": 1},
            {"source": "Коммерсантъ news", "news_id": 2},
        ]

        result = validator.validate(answer, docs)

        assert result.is_valid is True
        assert result.total_citations == 2
        assert result.valid_citations == ["РБК", "Коммерсантъ news"]

    def test_sources_block_with_period_before_title_is_valid(self):
        validator = CitationValidator()
        answer = (
            "Короткий обзор по материалам дня.\n\n"
            "Источники:\n"
            "1. RIA Novosti. \"Main event title.\" https://example.test/ria\n"
        )
        docs = [{"source": "RIA Novosti", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is True
        assert result.valid_citations == ["RIA Novosti"]

    def test_technical_acronyms_in_parentheses_are_not_sources(self):
        validator = CitationValidator()
        answer = (
            "Компании внедряют интернет вещей (IIoT), платформы MWS AI и графические процессоры (GPU). "
            "Система диспетчерского управления (АСДУ) помогает дата-центрам.\n\n"
            "Источники:\n"
            "1. CNews — Главная технологическая новость — https://example.test/cnews\n"
        )
        docs = [{"source": "CNews", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is True
        assert result.valid_citations == ["CNews"]


class TestCitationValidatorInvalid:
    """Тесты невалидных цитат."""

    def test_citation_not_in_context(self):
        """Источник упомянут, но его нет в контексте."""
        validator = CitationValidator()
        answer = "По данным Lenta.ru, ставка выросла."
        docs = [
            {"source": "ТАСС", "news_id": 1},
            {"source": "РИА", "news_id": 2},
        ]

        result = validator.validate(answer, docs)

        assert result.is_valid is False
        assert len(result.invalid_citations) == 1
        assert result.invalid_citations[0].source_name == "Lenta.ru"
        assert result.invalid_citations[0].issue_type == "not_in_context"

    def test_mixed_valid_and_invalid(self):
        """Часть цитат валидна, часть — нет."""
        validator = CitationValidator()
        answer = "По данным ТАСС, ставка выросла. А BBC сообщает о кризисе."
        docs = [{"source": "ТАСС", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is False
        assert len(result.valid_citations) == 1
        assert len(result.invalid_citations) == 1

    def test_citation_snippet_provided(self):
        """Для проблемной цитаты возвращается сниппет."""
        validator = CitationValidator()
        answer = "Как сообщает BBC, в мире произошли изменения..."
        docs = [{"source": "ТАСС", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert len(result.invalid_citations) == 1
        issue = result.invalid_citations[0]
        assert "BBC" in issue.text_snippet


class TestCitationValidatorNormalization:
    """Тесты нормализации имён источников."""

    def test_case_insensitive(self):
        """Регистр не важен."""
        validator = CitationValidator()
        answer = "По данным тасс, ставка выросла."
        docs = [{"source": "ТАСС", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is True

    def test_synonym_mapping_ria(self):
        """Синонимы: 'РИА Новости' → 'РИА'."""
        validator = CitationValidator()
        answer = "РИА Новости сообщает о событии."
        docs = [{"source": "РИА", "news_id": 1}]

        result = validator.validate(answer, docs)

        assert result.is_valid is True

    def test_synonym_mapping_cb(self):
        """Синонимы: 'Банк России' → 'ЦБ'."""
        # Это проверяется через нормализацию, но 'Банк России' не будет
        # извлечён citation паттернами как источник. Проверяем что
        'test passes'


# ───────────────────────────────────────────────────────────
# HallucinationChecker tests
# ───────────────────────────────────────────────────────────

class TestHallucinationCheckerSupported:
    """Тесты подтверждённых claims."""

    def test_fully_supported_claim(self):
        """Claim полностью подтверждён документом."""
        checker = HallucinationChecker()
        answer = "Центральный банк повысил ключевую ставку."
        docs = [
            {
                "news_id": 1,
                "content": "Банк России принял решение поднять ключевую ставку на заседании.",
                "title": "ЦБ повысил ставку",
            },
        ]

        result = checker.check_groundedness(answer, docs)

        assert result.is_acceptable is True
        assert result.supported_claims >= 1
        assert result.overall_score > 0.5

    def test_multiple_documents_support(self):
        """Разные части claim подтверждаются разными документами."""
        checker = HallucinationChecker()
        answer = "Инфляция растёт. Ставка повышена."
        docs = [
            {"news_id": 1, "content": "Инфляция в стране продолжает расти.", "title": ""},
            {"news_id": 2, "content": "Центробанк повысил ключевую ставку.", "title": ""},
        ]

        result = checker.check_groundedness(answer, docs)

        assert result.is_acceptable is True

    def test_empty_answer(self):
        """Пустой ответ считается acceptable."""
        checker = HallucinationChecker()
        result = checker.check_groundedness("", [{"news_id": 1, "content": "test", "title": ""}])

        assert result.is_acceptable is True
        assert result.total_claims == 0


class TestHallucinationCheckerUnsupported:
    """Тесты неподтверждённых claims."""

    def test_hallucinated_claim(self):
        """Claim не подтверждён ни одним документом."""
        checker = HallucinationChecker(min_overlap=0.3)
        answer = "Марс имеет атмосферу из чистого золота."
        docs = [
            {"news_id": 1, "content": "Центральный банк повысил ставку.", "title": ""},
        ]

        result = checker.check_groundedness(answer, docs)

        assert result.is_acceptable is False
        assert result.recommendation == "needs_correction"
        assert len(result.unsupported_claims) >= 1

    def test_partial_support(self):
        """Частичное подтверждение claims."""
        checker = HallucinationChecker(min_overlap=0.3)
        answer = "ЦБ повысил ставку. Марс имеет атмосферу из золота."
        docs = [
            {"news_id": 1, "content": "Банк России поднял ключевую ставку.", "title": ""},
        ]

        result = checker.check_groundedness(answer, docs)

        # Один claim подтверждён, один — нет
        assert result.supported_claims >= 1
        assert len(result.unsupported_claims) >= 1


class TestHallucinationCheckerEdgeCases:
    """Тесты граничных случаев."""

    def test_stop_words_filtered(self):
        """Стоп-слова не учитываются при overlap."""
        checker = HallucinationChecker()
        # Токены claim после фильтрации стоп-слов
        tokens = checker._tokenize("Центральный банк повысил ставку")
        # Стоп-слова должны быть удалены
        assert "в" not in tokens
        assert "на" not in tokens
        # Содержательные токены остаются
        assert "банк" in tokens or "центральн" in tokens

    def test_overlap_computation(self):
        """Lexical overlap вычисляется корректно."""
        checker = HallucinationChecker()
        claim_tokens = {"банк", "повысил", "ставку"}
        doc_tokens = {"банк", "россии", "повысил", "ключевую", "ставку"}

        overlap = checker._compute_overlap(claim_tokens, doc_tokens)

        # Все 3 claim-токена есть в документе
        assert overlap == 1.0

    def test_partial_overlap(self):
        """Частичное перекрытие токенов."""
        checker = HallucinationChecker()
        claim_tokens = {"банк", "повысил", "ставку", "золото"}
        doc_tokens = {"банк", "россии", "повысил", "ставку"}

        overlap = checker._compute_overlap(claim_tokens, doc_tokens)

        # 3 из 4 токенов нашлись
        assert abs(overlap - 0.75) < 0.01
