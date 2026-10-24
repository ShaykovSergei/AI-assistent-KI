"""Анонимизация персональных данных перед отправкой в нейросеть.

Найденные ПДн заменяются на токены вида [ИМЯ_1], [ТЕЛЕФОН_1], [EMAIL_1], [АДРЕС_1].
Соответствие хранится только в памяти текущего запроса и используется для
обратной подстановки после получения ответа модели.
"""

from __future__ import annotations

import re
from typing import Any


class Anonymizer:
    def __init__(self):
        self.mapping: dict[str, str] = {}
        self.counters = {
            "ИМЯ": 0,
            "ТЕЛЕФОН": 0,
            "EMAIL": 0,
            "АДРЕС": 0,
            "ПДН": 0,
        }

    def _next_token(self, prefix: str) -> str:
        self.counters[prefix] += 1
        token = f"[{prefix}_{self.counters[prefix]}]"
        return token

    def anonymize(self, text: str) -> tuple[str, dict[str, str]]:
        if not text:
            return text, {}

        result = text
        self.mapping = {}
        self.counters = {k: 0 for k in self.counters}

        # 1) Email
        email_pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
        def replace_email(m):
            token = self._next_token("EMAIL")
            self.mapping[token] = m.group(0)
            return token
        result = email_pattern.sub(replace_email, result)

        # 2) Телефоны (российские и международные)
        phone_pattern = re.compile(
            r"(\+?\d{1,3}[\s\-\(\)]?)?(\(?\d{3,4}\)?[\s\-\)]?)?[\d\s\-\(\)]{7,}\d"
        )
        def replace_phone(m):
            val = m.group(0)
            # Фильтр: слишком короткие совпадения пропускаем
            digits = re.sub(r"\D", "", val)
            if len(digits) < 7:
                return val
            token = self._next_token("ТЕЛЕФОН")
            self.mapping[token] = val
            return token
        result = phone_pattern.sub(replace_phone, result)

        # 3) Адреса (простые эвристики)
        address_pattern = re.compile(
            r"(?i)\b(ул\.?|улица|пр\.?|проспект|пер\.?|переулок|б-р|бульвар|пл\.?|площадь|"
            r"д\.?\s*\d+[а-яА-Я]?\b|дом\s*\d+[а-яА-Я]?\b|кв\.?\s*\d+\b|корп\.?\s*\d+\b|офис\s*\d+\b|"
            r"г\.\s*[А-Яа-я\-]+\b|город\s*[А-Яа-я\-]+\b)"
        )
        # Более жёсткий подход - ищем фрагменты с адресными признаками
        # Для простоты заменяем совпадения целиком в связке
        def replace_address(m):
            val = m.group(0)
            token = self._next_token("АДРЕС")
            self.mapping[token] = val
            return token
        result = address_pattern.sub(replace_address, result)

        # 4) Имена (эвристика: "Имя:", "ФИО:", заглавные слова в контексте)
        # Сначала явные метки из формы
        name_label_pattern = re.compile(r"(?i)(имя|фио|контактное\s+лицо|обращаться)\s*:\s*([^\n\r]+)")
        def replace_name_label(m):
            label = m.group(1)
            name_val = m.group(2).strip()
            if not name_val or name_val.lower() in ("не указано", "-", ""):
                return m.group(0)
            token = self._next_token("ИМЯ")
            self.mapping[token] = name_val
            return f"{label}: {token}"
        result = name_label_pattern.sub(replace_name_label, result)

        # Отдельные ФИО из 2-3 слов с заглавной буквы (осторожная эвристика)
        fio_pattern = re.compile(r"\b([А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)\b")
        def replace_fio(m):
            val = m.group(1)
            # Исключаем названия компаний/организаций
            low = val.lower()
            if any(x in low for x in ["компания", "ооо", "ип", "зао", "оао", "мебель"]):
                return val
            # Если уже токенизировано - пропускаем
            if val in self.mapping.values():
                return val
            token = self._next_token("ИМЯ")
            self.mapping[token] = val
            return token
        result = fio_pattern.sub(replace_fio, result)

        return result, self.mapping


def anonymize(text: str) -> tuple[str, dict[str, str]]:
    a = Anonymizer()
    return a.anonymize(text)


def deanonymize_text(text: str, mapping: dict[str, str]) -> str:
    if not text or not mapping:
        return text
    result = text
    # Заменяем токены обратно (от более длинных к коротким не нужно, просто все)
    for token, original in mapping.items():
        result = result.replace(token, original)
    return result


def deanonymize_obj(obj: Any, mapping: dict[str, str]) -> Any:
    if not mapping:
        return obj
    if isinstance(obj, str):
        return deanonymize_text(obj, mapping)
    if isinstance(obj, list):
        return [deanonymize_obj(item, mapping) for item in obj]
    if isinstance(obj, dict):
        return {k: deanonymize_obj(v, mapping) for k, v in obj.items()}
    return obj

