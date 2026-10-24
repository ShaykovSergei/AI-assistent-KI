"""Проверка подключения к GigaChat API.

Запуск:
    python check_connection.py

Скрипт скажет, найден ли ключ в .env, работает ли он и какие модели доступны.
Сам ключ никогда не выводится на экран.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from console import setup_console  # noqa: E402
from gigachat import GigaChatError, get_models, get_settings  # noqa: E402


def main() -> int:
    setup_console()
    settings = get_settings()

    print("=" * 62)
    print(" Проверка подключения к GigaChat API")
    print("=" * 62)
    print(f" Модель из .env:   {settings['model']}")
    print(f" Версия API:       {settings['scope']}")

    if not settings["key"]:
        print(" Ключ авторизации: НЕ НАЙДЕН")
        print("-" * 62)
        print(" Что делать:")
        print("   1) Откройте файл .env в папке проекта")
        print("   2) Впишите значение GIGACHAT_AUTHORIZATION_KEY")
        print("      (ключ из личного кабинета Studio: проект GigaChat API ->")
        print("       Настройки API -> Получить ключ -> Authorization Key)")
        print("-" * 62)
        return 1

    print(" Ключ авторизации: найден (значение не показываю)")
    print("-" * 62)
    print(" Подключаюсь к GigaChat...")

    try:
        models = get_models()
    except GigaChatError as error:
        print(" ОШИБКА:", error)
        print("-" * 62)
        print(" Подробности и подсказки — в README, раздел «Если что-то не работает».")
        return 2

    print(" Соединение установлено, ключ работает.")
    print(" Доступные модели:")
    for name in models:
        marker = " <- выбрана в .env" if name == settings["model"] else ""
        print(f"   - {name}{marker}")
    if settings["model"] not in models:
        print(f" Внимание: модели {settings['model']} нет в списке.")
        print(" Попробуйте указать в .env одну из моделей выше.")
    print("=" * 62)
    print(" Всё готово. Запускайте приложение: python app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())