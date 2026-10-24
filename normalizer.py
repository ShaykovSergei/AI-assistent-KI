"""Приведение ответа модели к единому виду.

Модель может ответить немного по-разному: где-то пропустить поле, где-то
написать «целевой лид», где-то вернуть список вместо строки. Здесь ответ
приводится к строгому виду, чтобы карточка всегда содержала все поля,
а в черновике не осталось обещаний, которых нет в заявке.
"""

from __future__ import annotations

import re

NOT_SPECIFIED = "не указано"

LEAD_TYPES = ("целевой", "нецелевой", "неясно")

LEAD_TYPE_SYNONYMS = {
    "целевой": "целевой",
    "целевой лид": "целевой",
    "целевая заявка": "целевой",
    "target": "целевой",
    "нецелевой": "нецелевой",
    "нецелевой лид": "нецелевой",
    "нецелевая заявка": "нецелевой",
    "не релевантный": "нецелевой",
    "нерелевантный": "нецелевой",
    "неясно": "неясно",
    "не определён": "неясно",
    "не определен": "неясно",
    "непонятно": "неясно",
    "unclear": "неясно",
}

# Признаки обещаний, которых не должно быть в черновике.
CURRENCY_MARKERS = ("₽", "руб", "р.", "тенге", "$", "€")
PROMISE_MARKERS = ("скидк", "гарантир", "обеща", "%", "процент")
DEADLINE_MARKERS = ("доставим", "поставим", "привезём", "привезем", "срок", "в течение", "в течен")

FALLBACK_DRAFT = (
    "Здравствуйте! Мы получили вашу заявку и уже занимаемся её обработкой. "
    "Детали уточним по тексту заявки."
)


def _as_text(value) -> str:
    """Любое значение превращаем в аккуратный текст."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(parts)
    if isinstance(value, dict):
        parts = [f"{key}: {item}" for key, item in value.items() if str(item).strip()]
        return "; ".join(parts)
    return str(value).strip()


def _as_list(value) -> list[str]:
    """Список строк: строки без пустых элементов."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = [_as_text(item) for item in value]
    else:
        items = [_as_text(value)]
    return [item for item in items if item]


def _normalize_lead_type(value) -> str:
    text = _as_text(value).lower()
    if not text:
        return "неясно"
    if text in LEAD_TYPE_SYNONYMS:
        return LEAD_TYPE_SYNONYMS[text]
    for key, value_ in LEAD_TYPE_SYNONYMS.items():
        if key in text:
            return value_
    return "неясно"


def _normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = _as_text(value).lower()
    if text in ("true", "да", "yes", "1", "истина"):
        return True
    if text in ("false", "нет", "no", "0", "ложь"):
        return False
    return False


def _numbers(text: str) -> set[str]:
    """Все числа из текста в нормализованном виде («1,5 млн» -> «1.5», «40» -> «40»)."""
    found = re.findall(r"\d+(?:[.,]\d+)?", text.replace(" ", ""))
    return {value.replace(",", ".") for value in found}


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def sanitize_reply_draft(draft: str, source_text: str) -> tuple[str, int]:
    """Убирает из черновика обещания, которых нет в исходной заявке.

    Например, если модель написала «поставим за 3 дня», а в заявке про 3 дня
    не было — предложение удаляется. Возвращает (текст, число удалённых фраз).
    """
    if not draft:
        return draft, 0

    source_numbers = _numbers(source_text)
    source_lower = source_text.lower()
    kept: list[str] = []
    removed = 0

    for sentence in _split_sentences(draft):
        low = sentence.lower()
        numbers = _numbers(sentence)
        new_numbers = [value for value in numbers if value not in source_numbers]

        has_currency = any(marker in low for marker in CURRENCY_MARKERS)
        has_promise = any(marker in low for marker in PROMISE_MARKERS)
        has_deadline = any(marker in low for marker in DEADLINE_MARKERS)

        suspicious = False
        if has_currency and new_numbers:
            suspicious = True
        if has_promise and not any(
            marker in source_lower for marker in ("скидк", "%", "процент")
        ):
            suspicious = True
        if has_deadline and new_numbers:
            suspicious = True

        if suspicious:
            removed += 1
        else:
            kept.append(sentence)

    if removed == 0:
        return draft, 0

    cleaned = " ".join(kept).strip()
    if not cleaned:
        cleaned = FALLBACK_DRAFT
    return cleaned, removed


def normalize_result(raw: dict, source_text: str) -> tuple[dict, list[str]]:
    """Приводит ответ модели к карточке с девятью полями."""
    raw = raw if isinstance(raw, dict) else {}
    notes: list[str] = []

    company = _as_text(raw.get("company")) or NOT_SPECIFIED
    summary = _as_text(raw.get("summary")) or NOT_SPECIFIED
    lead_type = _normalize_lead_type(raw.get("lead_type"))

    key_data = _as_list(raw.get("key_data"))
    missing_data = _as_list(raw.get("missing_data"))

    next_step = _as_text(raw.get("next_step"))
    reply_draft = _as_text(raw.get("reply_draft"))

    needs_human = _normalize_bool(raw.get("needs_human"))
    human_reason = _as_text(raw.get("human_reason"))

    # Если данных мало — это надо отметить и задать уточняющие вопросы.
    if lead_type == "неясно" and not missing_data:
        missing_data = ["Недостаточно данных для квалификации заявки"]
    if lead_type == "неясно" and not next_step:
        next_step = "Уточнить у клиента, что именно нужно приобрести и для какого офиса"
    if not next_step:
        next_step = (
            "Связаться с клиентом и уточнить детали заявки"
            if needs_human
            else "Подготовить ответ клиенту по его запросу"
        )
    if not reply_draft:
        reply_draft = FALLBACK_DRAFT

    cleaned_draft, removed = sanitize_reply_draft(reply_draft, source_text)
    if removed:
        notes.append(
            "Из черновика ответа убраны формулировки с условиями (цены, сроки, "
            "скидки), которых нет в тексте заявки."
        )
    reply_draft = cleaned_draft

    if needs_human:
        human_reason = human_reason or NOT_SPECIFIED
    else:
        human_reason = "не требуется"

    result = {
        "company": company,
        "summary": summary,
        "lead_type": lead_type,
        "key_data": key_data,
        "missing_data": missing_data,
        "next_step": next_step,
        "reply_draft": reply_draft,
        "needs_human": needs_human,
        "human_reason": human_reason,
    }
    return result, notes