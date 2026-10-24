"""Работа с GigaChat API: получение токена доступа и отправка заявки на анализ.

Авторизация — по актуальной документации GigaChat (developers.sber.ru):
1) POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth
   с заголовком Authorization: Basic <ключ авторизации> и заголовком RqUID,
   в теле scope=GIGACHAT_API_PERS (для физических лиц);
2) запросы к моделям — https://api.giga.chat/v1/chat/completions
   с заголовком Authorization: Bearer <токен доступа>.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

import requests

from prompt import PLAIN_JSON_PROMPT, RESULT_SCHEMA, SYSTEM_PROMPT

BASE_DIR = Path(__file__).resolve().parent
CERT_DIR = BASE_DIR / "certs"
ROOT_CA_FILE = CERT_DIR / "russian_trusted_root_ca_pem.crt"
CA_BUNDLE_FILE = CERT_DIR / "ca_bundle.pem"
ROOT_CA_URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"

TOKEN_URL = os.getenv(
    "GIGACHAT_TOKEN_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
)
BASE_URL = os.getenv("GIGACHAT_BASE_URL", "https://api.giga.chat").rstrip("/")

DEFAULT_MODEL = "GigaChat-2-Pro"
DEFAULT_SCOPE = "GIGACHAT_API_PERS"

TOKEN_TIMEOUT = 30
CHAT_TIMEOUT = 90

# Кэш токена: токен живёт 30 минут, обновляем его заранее.
_token_cache: dict[str, object] = {"token": None, "expires_at": 0.0}


class GigaChatError(Exception):
    """Ошибка, которую можно показать пользователю понятным текстом."""

    def __init__(self, message: str, retryable: bool = False, auth_error: bool = False):
        super().__init__(message)
        self.retryable = retryable
        self.auth_error = auth_error


def get_settings() -> dict[str, str]:
    """Настройки из .env (с запасными значениями)."""
    return {
        "key": (os.getenv("GIGACHAT_AUTHORIZATION_KEY") or "").strip(),
        "scope": (os.getenv("GIGACHAT_SCOPE") or DEFAULT_SCOPE).strip(),
        "model": (os.getenv("GIGACHAT_MODEL") or DEFAULT_MODEL).strip(),
    }


def ensure_root_certificate() -> bool:
    """Скачивает корневой сертификат Минцифры, если его ещё нет.

    Сервер выдачи токенов работает на сертификате НУЦ Минцифры, которого нет
    в стандартном наборе сертификатов Python, — без него будет ошибка SSL.
    """
    if ROOT_CA_FILE.is_file():
        return True
    try:
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        response = requests.get(ROOT_CA_URL, timeout=TOKEN_TIMEOUT)
        response.raise_for_status()
        ROOT_CA_FILE.write_bytes(response.content)
        return True
    except Exception:
        return False


def _build_ca_bundle() -> str | None:
    """Собирает общий файл сертификатов: системные + корневой Минцифры.

    Так проверка работает и для серверов Минцифры, и для обычных публичных
    сертификатов (если адрес API изменится).
    """
    if not ROOT_CA_FILE.is_file():
        return None
    parts: list[str] = []
    try:
        import certifi

        system_bundle = Path(certifi.where())
        if system_bundle.is_file():
            parts.append(system_bundle.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        parts.append(ROOT_CA_FILE.read_text(encoding="utf-8"))
    except OSError:
        return None
    try:
        CERT_DIR.mkdir(parents=True, exist_ok=True)
        CA_BUNDLE_FILE.write_text("\n".join(parts), encoding="utf-8")
    except OSError:
        return None
    return str(CA_BUNDLE_FILE)


def _ssl_verify():
    """Каким набором сертификатов проверять HTTPS-соединения."""
    bundle = (os.getenv("GIGACHAT_CA_BUNDLE") or "").strip()
    if bundle and Path(bundle).is_file():
        return bundle
    if CA_BUNDLE_FILE.is_file():
        return str(CA_BUNDLE_FILE)
    if ROOT_CA_FILE.is_file():
        return str(ROOT_CA_FILE)
    return True


def _network_error(error: Exception) -> GigaChatError:
    """Превращает техническую ошибку сети в понятное сообщение."""
    if isinstance(error, requests.exceptions.SSLError):
        return GigaChatError(
            "Не удалось проверить сертификат сервера GigaChat. Скачайте сертификат "
            "Минцифры командой из README (раздел «Сертификаты») и повторите попытку."
        )
    if isinstance(error, requests.exceptions.Timeout):
        return GigaChatError(
            "GigaChat API не ответил вовремя. Проверьте интернет-соединение и "
            "повторите попытку."
        )
    if isinstance(error, requests.exceptions.ConnectionError):
        return GigaChatError(
            "Не удалось связаться с GigaChat. Проверьте интернет-соединение и "
            "попробуйте ещё раз."
        )
    return GigaChatError(
        "Непредвиденная ошибка при обращении к GigaChat. Подробности в консоли, "
        "где запущено приложение."
    )


def get_access_token(force_refresh: bool = False) -> str:
    """Возвращает токен доступа (с кэшем на ~25 минут)."""
    settings = get_settings()
    key = settings["key"]

    if not key:
        raise GigaChatError(
            "Не задан ключ GigaChat. Откройте файл .env в папке проекта и впишите "
            "значение GIGACHAT_AUTHORIZATION_KEY (инструкция в README)."
        )

    cached_token = _token_cache.get("token")
    cached_until = float(_token_cache.get("expires_at") or 0)
    if not force_refresh and cached_token and cached_until > time.time():
        return str(cached_token)

    ensure_root_certificate()
    _build_ca_bundle()

    authorization = (
        key if key.lower().startswith("basic ") else f"Basic {key}"
    )
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": authorization,
    }

    try:
        response = requests.post(
            TOKEN_URL,
            data={"scope": settings["scope"]},
            headers=headers,
            verify=_ssl_verify(),
            timeout=TOKEN_TIMEOUT,
        )
    except requests.exceptions.RequestException as error:
        raise _network_error(error) from error

    if response.status_code == 401:
        raise GigaChatError(
            "GigaChat не принял ключ авторизации. Проверьте, что в файле .env "
            "ключ скопирован полностью, без пробелов и кавычек."
        )
    if response.status_code == 400:
        raise GigaChatError(
            "GigaChat отклонил запрос получения токена. Проверьте, что ключ "
            "авторизации скопирован полностью, и значение GIGACHAT_SCOPE в файле "
            ".env (для физических лиц — GIGACHAT_API_PERS)."
        )
    if response.status_code >= 400:
        raise GigaChatError(
            f"GigaChat вернул ошибку при получении токена (код {response.status_code}). "
            "Попробуйте ещё раз или обратитесь в поддержку GigaChat API."
        )

    try:
        payload = response.json()
    except ValueError as error:
        raise GigaChatError(
            "GigaChat вернул ответ, который не удалось прочитать. Попробуйте ещё раз."
        ) from error

    token = payload.get("access_token")
    if not token:
        raise GigaChatError(
            "GigaChat вернул ответ без токена доступа. Проверьте ключ в файле .env."
        )

    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        expires_at = time.time() + 25 * 60
    elif expires_at > 1e11:  # API иногда присылает время в миллисекундах
        expires_at = expires_at / 1000

    _token_cache["token"] = token
    _token_cache["expires_at"] = float(expires_at) - 60
    return str(token)


def get_models() -> list[str]:
    """Список доступных моделей — используется для проверки подключения."""
    token = get_access_token()
    try:
        response = requests.get(
            f"{BASE_URL}/v1/models",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            verify=_ssl_verify(),
            timeout=TOKEN_TIMEOUT,
        )
    except requests.exceptions.RequestException as error:
        raise _network_error(error) from error

    if response.status_code == 401:
        raise GigaChatError("GigaChat отклонил токен доступа. Попробуйте ещё раз.")
    if response.status_code >= 400:
        raise GigaChatError(
            f"GigaChat вернул ошибку при получении списка моделей "
            f"(код {response.status_code})."
        )

    try:
        data = response.json()
    except ValueError as error:
        raise GigaChatError("Не удалось прочитать ответ GigaChat.") from error

    return [str(item.get("id")) for item in data.get("data", []) if item.get("id")]


def _payloads(model: str, text: str) -> list[dict]:
    """Три варианта запроса: от самого строгого к самому простому."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    schema_payload = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "schema": RESULT_SCHEMA,
            "strict": True,
        },
    }
    schema_payload_soft = {
        "model": model,
        "messages": messages,
        "response_format": {
            "type": "json_schema",
            "schema": RESULT_SCHEMA,
        },
    }
    plain_payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": PLAIN_JSON_PROMPT.format(
                    fields=", ".join(RESULT_SCHEMA["required"]), text=text
                ),
            },
        ],
    }
    return [schema_payload, schema_payload_soft, plain_payload]


def _request_completion(token: str, payload: dict) -> str:
    """Один запрос к модели. Возвращает текст ответа."""
    try:
        response = requests.post(
            f"{BASE_URL}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json=payload,
            verify=_ssl_verify(),
            timeout=CHAT_TIMEOUT,
        )
    except requests.exceptions.RequestException as error:
        raise _network_error(error) from error

    if response.status_code == 401:
        raise GigaChatError(
            "GigaChat отклонил токен доступа. Попробуйте повторить обработку заявки.",
            auth_error=True,
        )
    if response.status_code == 429:
        raise GigaChatError(
            "Закончились токены GigaChat или превышен лимит запросов. Проверьте "
            "остаток токенов в личном кабинете."
        )
    if response.status_code in (400, 422):
        raise GigaChatError(
            f"GigaChat отклонил формат запроса (код {response.status_code}).",
            retryable=True,
        )
    if response.status_code >= 400:
        raise GigaChatError(
            f"GigaChat вернул ошибку (код {response.status_code}). Попробуйте ещё раз."
        )

    try:
        data = response.json()
        return str(data["choices"][0]["message"]["content"])
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise GigaChatError(
            "GigaChat вернул неожиданный ответ. Попробуйте ещё раз."
        ) from error


def _parse_json_object(text: str) -> dict:
    """Разбирает JSON из ответа модели (даже если он обёрнут в ```json ... ```)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except ValueError:
            pass

    raise GigaChatError(
        "GigaChat вернул ответ, который не удалось разобрать. Попробуйте ещё раз "
        "или немного измените текст заявки."
    )


def analyze_request(text: str) -> dict:
    """Отправляет заявку в GigaChat и возвращает разобранный JSON-ответ."""
    settings = get_settings()
    model = settings["model"]
    token = get_access_token()

    last_error: GigaChatError | None = None
    for payload in _payloads(model, text):
        for attempt in range(2):
            try:
                content = _request_completion(token, payload)
            except GigaChatError as error:
                last_error = error
                if error.auth_error and attempt == 0:
                    # токен мог протухнуть: обновляем его и пробуем ещё раз
                    token = get_access_token(force_refresh=True)
                    continue
                if error.retryable:
                    break  # переходим к следующему, более простому формату запроса
                raise
            return _parse_json_object(content)

    if last_error:
        raise last_error
    raise GigaChatError("Не удалось получить ответ от GigaChat. Попробуйте ещё раз.")