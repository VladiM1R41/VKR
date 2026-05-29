"""Quality filters for corpus terms and collocations.

These helpers are intentionally conservative: they filter analytics noise
without changing the base lemmatization output used by article chunks.
"""

from __future__ import annotations

from math import log1p
import re


_STOP_TERMS = {
    "а",
    "без",
    "более",
    "бы",
    "был",
    "была",
    "были",
    "было",
    "быть",
    "в",
    "вам",
    "вас",
    "апрель",
    "весь",
    "во",
    "вот",
    "все",
    "всего",
    "всей",
    "всем",
    "всех",
    "вы",
    "где",
    "год",
    "говориться",
    "да",
    "добавить",
    "данные",
    "два",
    "для",
    "до",
    "его",
    "ее",
    "если",
    "есть",
    "еще",
    "же",
    "за",
    "заявить",
    "и",
    "из",
    "или",
    "им",
    "их",
    "как",
    "когда",
    "который",
    "кроме",
    "май",
    "март",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
    "январь",
    "февраль",
    "ли",
    "либо",
    "любой",
    "мочь",
    "мы",
    "на",
    "над",
    "не",
    "него",
    "нее",
    "нет",
    "ни",
    "но",
    "о",
    "об",
    "один",
    "он",
    "она",
    "они",
    "оно",
    "от",
    "отметить",
    "первый",
    "по",
    "под",
    "подчеркнуть",
    "после",
    "при",
    "про",
    "получить",
    "ранее",
    "с",
    "сей",
    "сказать",
    "ссылка",
    "слово",
    "со",
    "сообщить",
    "стать",
    "свой",
    "себя",
    "так",
    "также",
    "такой",
    "там",
    "то",
    "тот",
    "тут",
    "ты",
    "у",
    "уже",
    "число",
    "что",
    "чтобы",
    "это",
    "этот",
    "этом",
    "эти",
    "этих",
    "являться",
}

_ALLOWED_SHORT_TERMS = {
    "ai",
    "it",
    "ес",
    "ии",
    "мвд",
    "мид",
    "млн",
    "млрд",
    "оон",
    "рф",
    "руб",
    "сша",
    "цб",
}

_CODE_LIKE_TERMS = {
    "autofill",
    "bin",
    "diannas",
    "dontbuild",
    "etc",
    "hookeventname",
    "hookspecificoutput",
    "http",
    "https",
    "localhost",
    "locked",
    "nginx",
    "pipefail",
    "proxy_add_x_forwarded_for",
    "proxy_set_header",
    "scheme",
    "skip",
    "src",
    "usr",
    "var",
    "x-forwarded-for",
    "x-forwarded-proto",
}

_BAD_CHARS_RE = re.compile(r"[{}<>=/\\|$@`_]")
_ASCII_MULTI_HYPHEN_RE = re.compile(r"^[a-z]+(?:-[a-z]+){2,}$")


def normalize_quality_term(term: str) -> str:
    """Normalize a term before analytics filtering."""

    return " ".join(term.strip().lower().replace("ё", "е").split())


def _has_letter(term: str) -> bool:
    return any(char.isalpha() for char in term)


def _is_code_like(term: str) -> bool:
    if term in _CODE_LIKE_TERMS:
        return True
    if _BAD_CHARS_RE.search(term):
        return True
    if term.startswith("-") or term.endswith("-"):
        return True
    return bool(_ASCII_MULTI_HYPHEN_RE.match(term))


def is_informative_term(term: str) -> bool:
    """Return True when a lemma is useful for vocabulary/collocation analytics."""

    normalized = normalize_quality_term(term)
    if not normalized:
        return False
    if normalized in _STOP_TERMS:
        return False
    if _is_code_like(normalized):
        return False
    if normalized.isdigit():
        return False
    if len(normalized) < 3 and normalized not in _ALLOWED_SHORT_TERMS:
        return False
    if len(normalized) > 64:
        return False
    return _has_letter(normalized)


def is_query_expansion_term(term: str) -> bool:
    """Return True when a term is safe to use as part of query expansion."""

    normalized = normalize_quality_term(term)
    if not is_informative_term(normalized):
        return False
    return len(normalized) >= 4 or normalized in _ALLOWED_SHORT_TERMS


def is_informative_bigram(term_a: str, term_b: str) -> bool:
    """Return True when a bigram is likely to be a meaningful news phrase."""

    first = normalize_quality_term(term_a)
    second = normalize_quality_term(term_b)
    if first == second:
        return False
    return is_informative_term(first) and is_informative_term(second)


def collocation_expansion_score(*, pmi_score: float, frequency: int) -> float:
    """Rank expansion candidates by association strength and corpus support."""

    return float(pmi_score) * log1p(max(0, int(frequency)))
