"""Настройка вывода в консоль.

Зачем это нужно: в окне терминала по умолчанию может стоять старая кодировка
(например, CP866), и русский текст тогда превращается в «кракозябры». Здесь мы
переключаем вывод на ту кодировку, которую реально использует окно.
"""

from __future__ import annotations

import ctypes
import os
import sys


def setup_console() -> None:
    """Переводит вывод консоли в кодировку, которую понимает окно терминала."""
    if os.name != "nt":
        return

    try:
        codepage = int(ctypes.windll.kernel32.GetConsoleOutputCP())
    except Exception:
        return

    if codepage in (0, 65001):
        return  # консоль уже в UTF-8 — менять нечего

    encoding = f"cp{codepage}"
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is None or not stream.isatty():
                continue
            stream.reconfigure(encoding=encoding, errors="replace")
        except (AttributeError, OSError, ValueError):
            continue
