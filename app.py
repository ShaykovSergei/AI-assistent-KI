"""AI-помощник для первичной обработки входящих заявок.

Запуск:
    python app.py
Затем откройте в браузере http://127.0.0.1:5000

Секреты читаются из файла .env и никуда не выводятся.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from anonymizer import anonymize, deanonymize_obj  # noqa: E402
from audit import log_anonymization  # noqa: E402
from console import setup_console  # noqa: E402
from gigachat import GigaChatError, analyze_request, get_settings  # noqa: E402
from normalizer import normalize_result  # noqa: E402
from samples import SAMPLES  # noqa: E402
from bitrix import send_lead_to_bitrix  # noqa: E402

app = Flask(__name__)
app.json.ensure_ascii = False  # чтобы русский текст в JSON читался без \uXXXX

MAX_TEXT_LENGTH = 20000
MAX_NAME_LENGTH = 120
MAX_PHONE_LENGTH = 40
MAX_EMAIL_LENGTH = 120

PHONE_PATTERN = re.compile(r"^[+\d()\s\-]{7,}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def _clean(value) -> str:
    """Схлопывает пробелы и обрезает значение поля формы."""
    return " ".join(str(value or "").split())


def _build_request_text(name: str, phone: str, email: str, text: str) -> str:
    """Собирает из полей формы единый текст заявки для модели."""
    lines = [f"Имя: {name}", f"Телефон: {phone}"]
    if email:
        lines.append(f"Email: {email}")
    lines.extend(["", "Текст заявки:", text])
    return "\n".join(lines)


@app.get("/")
def index():
    """Одна страница приложения с формой и кнопками тестовых заявок."""
    return render_template("index.html", samples=SAMPLES)


@app.post("/api/anonymize")
def api_anonymize():
    """Возвращает анонимизированный текст заявки для предпросмотра на странице."""
    data = request.get_json(silent=True) or {}

    name = _clean(data.get("name"))
    phone = _clean(data.get("phone"))
    email = _clean(data.get("email"))
    text = str(data.get("text") or "").strip()

    request_text = _build_request_text(name, phone, email, text)
    anonymized_text, _ = anonymize(request_text)

    return jsonify({"anonymized_text": anonymized_text})


@app.post("/api/analyze")
def api_analyze():
    """Принимает данные формы заявки и возвращает разобранный результат."""
    data = request.get_json(silent=True) or {}

    name = _clean(data.get("name"))
    phone = _clean(data.get("phone"))
    email = _clean(data.get("email"))
    text = str(data.get("text") or "").strip()

    if not name:
        return jsonify({"error": "Укажите имя — как к вам обращаться."}), 400

    if len(name) > MAX_NAME_LENGTH:
        return (
            jsonify({"error": f"Имя слишком длинное (максимум {MAX_NAME_LENGTH} символов)."}),
            400,
        )

    if not phone:
        return jsonify({"error": "Укажите телефон клиента."}), 400

    if len(phone) > MAX_PHONE_LENGTH:
        return (
            jsonify({"error": f"Телефон слишком длинный (максимум {MAX_PHONE_LENGTH} символов)."}),
            400,
        )

    if not PHONE_PATTERN.match(phone):
        return (
            jsonify({"error": "Телефон выглядит некорректно. Пример: +7 916 245-18-03"}),
            400,
        )

    if len(email) > MAX_EMAIL_LENGTH:
        return (
            jsonify({"error": f"Почта слишком длинная (максимум {MAX_EMAIL_LENGTH} символов)."}),
            400,
        )

    if email and not EMAIL_PATTERN.match(email):
        return jsonify({"error": "Почта выглядит некорректно. Пример: name@company.ru"}), 400

    if not text:
        return (
            jsonify(
                {
                    "error": "Впишите текст заявки в поле или нажмите одну из "
                    "кнопок с тестовыми заявками."
                }
            ),
            400,
        )

    if len(text) > MAX_TEXT_LENGTH:
        return (
            jsonify(
                {
                    "error": "Текст заявки слишком длинный "
                    f"(максимум {MAX_TEXT_LENGTH} символов). Сократите его."
                }
            ),
            400,
        )

    request_text = _build_request_text(name, phone, email, text)

    # Анонимизация ПДн перед отправкой в нейросеть
    anonymized_text, pdn_mapping = anonymize(request_text)
    request_id = uuid.uuid4().hex[:12]
    log_anonymization(pdn_mapping, anonymized_text, request_id)

    try:
        raw_result = analyze_request(anonymized_text)
    except GigaChatError as error:
        return jsonify({"error": str(error), "anonymized_text": anonymized_text}), 502
    except Exception:
        app.logger.exception("Непредвиденная ошибка при обработке заявки")
        return (
            jsonify(
                {
                    "error": "Внутренняя ошибка приложения. Подробности видны в "
                    "консоли, где запущена программа.",
                    "anonymized_text": anonymized_text,
                }
            ),
            500,
        )

    # Обратная подстановка реальных значений
    if pdn_mapping:
        raw_result = deanonymize_obj(raw_result, pdn_mapping)

    result, notes = normalize_result(raw_result, request_text)
    if pdn_mapping:
        result = deanonymize_obj(result, pdn_mapping)
        notes = deanonymize_obj(notes, pdn_mapping)

    # Отправка лида, задачи и уведомления в Битрикс24 (если настроен вебхук)
    bitrix_status = None
    try:
        bitrix_status = send_lead_to_bitrix(
            contacts={"name": name, "phone": phone, "email": email},
            result=result,
            original_text=request_text,
            notes=notes,
        )
    except Exception:
        app.logger.exception("Не удалось отправить лид в Битрикс24")

    return jsonify(
        {
            "result": result,
            "notes": notes,
            "contacts": {"name": name, "phone": phone, "email": email},
            "anonymized_text": anonymized_text,
            "request_id": request_id,
            "bitrix": bitrix_status,
        }
    )


def _print_banner() -> None:
    settings = get_settings()
    print("=" * 62)
    print(" AI-помощник обработки заявок (MVP, GigaChat API)")
    print("=" * 62)
    print(f" Модель:            {settings['model']}")
    print(f" Версия API:        {settings['scope']}")
    if settings["key"]:
        print(" Ключ авторизации:  найден в .env")
    else:
        print(" Ключ авторизации:  НЕ НАЙДЕН.")
        print("   -> Впишите GIGACHAT_AUTHORIZATION_KEY в файл .env (шаг 3 в README).")
    print("-" * 62)
    print(" Откройте в браузере: http://127.0.0.1:5000")
    print(" Остановить программу: нажмите Ctrl+C")
    print("=" * 62)


if __name__ == "__main__":
    setup_console()
    _print_banner()
    try:
        app.run(host="127.0.0.1", port=5000, debug=False)
    except OSError as error:
        print()
        print(" Не удалось запустить приложение:", error)
        print(" Скорее всего, порт 5000 уже занят другой программой.")
        print(" Закройте её и запустите приложение ещё раз.")