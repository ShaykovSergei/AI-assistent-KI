"""Журнал анонимизации без хранения персональных данных.

В CSV пишутся только время, идентификатор запроса и количество найденных
токенов по категориям. Сами имена, телефоны, почты и адреса не сохраняются.
"""

from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "anonymization.csv"
FIELDS = [
    "timestamp",
    "request_id",
    "total_tokens",
    "names",
    "phones",
    "emails",
    "addresses",
    "anonymized_length",
]

TOKEN_PATTERN = re.compile(r"^\[([А-ЯЁ]+)_\d+\]$")


def log_anonymization(
    mapping: dict[str, str],
    anonymized_text: str,
    request_id: str,
) -> None:
    counts = {"ИМЯ": 0, "ТЕЛЕФОН": 0, "EMAIL": 0, "АДРЕС": 0, "ПДН": 0}
    for token in mapping:
        match = TOKEN_PATTERN.match(token)
        if match and match.group(1) in counts:
            counts[match.group(1)] += 1

    row = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "request_id": request_id,
        "total_tokens": len(mapping),
        "names": counts["ИМЯ"],
        "phones": counts["ТЕЛЕФОН"],
        "emails": counts["EMAIL"],
        "addresses": counts["АДРЕС"],
        "anonymized_length": len(anonymized_text or ""),
    }

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        is_new = not LOG_FILE.is_file() or LOG_FILE.stat().st_size == 0
        with LOG_FILE.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    except OSError as error:
        logger.warning("Не удалось записать журнал анонимизации: %s", error)
