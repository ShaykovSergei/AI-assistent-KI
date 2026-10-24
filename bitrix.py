"""Интеграция с Битрикс24 через входящий вебхук.

Создаётся лид (crm.lead.add), задача для менеджера (tasks.task.add) и
уведомление в мессенджере (im.notify). Если вебхук не настроен, приложение
продолжает работать без интеграции.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict

import requests

logger = logging.getLogger(__name__)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Да" if value else "Нет"
    if isinstance(value, (list, tuple, set)):
        parts = []
        for item in value:
            s = _as_text(item).strip()
            if s:
                parts.append(f"• {s}")
        return "\n".join(parts)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            sv = _as_text(v).strip()
            if sv:
                parts.append(f"• {k}: {sv}")
        return "\n".join(parts)
    return str(value).strip()


def _webhook_base() -> str:
    return (os.getenv("B24_URL") or os.getenv("BITRIX24_WEBHOOK_URL") or "").strip().rstrip("/")


def _webhook_owner_id(webhook: str) -> int:
    match = re.search(r"/rest/(\d+)/", webhook)
    if match:
        return int(match.group(1))
    return 1


def _manager_id(webhook: str) -> int:
    raw = (os.getenv("B24_MANAGER_ID") or "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return _webhook_owner_id(webhook)


def _method_url(webhook: str, method: str) -> str:
    if webhook.endswith(f"/{method}.json"):
        return webhook
    if webhook.endswith(f"/{method}"):
        return f"{webhook}.json"
    return f"{webhook}/{method}.json"


def _call(webhook: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(_method_url(webhook, method), json=payload, timeout=15)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Bitrix24 {method}: HTTP {response.status_code} {response.text[:300]}"
        )
    data = response.json()
    if data.get("error"):
        raise RuntimeError(
            f"Bitrix24 {method}: {data.get('error')} "
            f"{data.get('error_description') or ''}".strip()
        )
    return data


def _lead_fields(
    contacts: Dict[str, str],
    result: Dict[str, Any],
    comments: str,
) -> Dict[str, Any]:
    name = (contacts.get("name") or "").strip()
    phone = (contacts.get("phone") or "").strip()
    email = (contacts.get("email") or "").strip()
    summary = _as_text(result.get("summary"))
    title = summary or "Заявка с сайта"
    if len(title) > 255:
        title = title[:252] + "..."

    fields: Dict[str, Any] = {
        "TITLE": title,
        "SOURCE_ID": "WEB",
        "COMMENTS": comments,
    }
    if name:
        fields["NAME"] = name
    if (result.get("company") or "").strip() and result.get("company") != "не указано":
        fields["COMPANY_TITLE"] = result.get("company").strip()
    if phone:
        fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
    if email:
        fields["EMAIL"] = [{"VALUE": email, "VALUE_TYPE": "WORK"}]

    lead_type = _as_text(result.get("lead_type"))
    if lead_type:
        fields["UF_CRM_LEAD_TYPE_AI"] = lead_type
    if summary:
        fields["UF_CRM_AI_SUMMARY"] = summary
    key_data = _as_text(result.get("key_data"))
    if key_data:
        fields["UF_CRM_AI_KEY_DATA"] = key_data
    missing_data = _as_text(result.get("missing_data"))
    if missing_data:
        fields["UF_CRM_AI_MISSING"] = missing_data
    next_step = _as_text(result.get("next_step"))
    if next_step:
        fields["UF_CRM_AI_NEXT_STEP"] = next_step
    reply_draft = _as_text(result.get("reply_draft"))
    if reply_draft:
        fields["UF_CRM_AI_REPLY_DRAFT"] = reply_draft
    needs_human = result.get("needs_human")
    if isinstance(needs_human, bool):
        fields["UF_CRM_AI_NEEDS_HUMAN"] = "Y" if needs_human else "N"
    human_reason = _as_text(result.get("human_reason"))
    if human_reason:
        fields["UF_CRM_AI_HUMAN_REASON"] = human_reason
    return fields


def _comments(
    contacts: Dict[str, str],
    result: Dict[str, Any],
    original_text: str,
    notes: list[str] | None,
) -> str:
    name = (contacts.get("name") or "").strip()
    phone = (contacts.get("phone") or "").strip()
    email = (contacts.get("email") or "").strip()
    summary = _as_text(result.get("summary"))
    lead_type = _as_text(result.get("lead_type"))
    key_data = _as_text(result.get("key_data"))
    missing_data = _as_text(result.get("missing_data"))
    next_step = _as_text(result.get("next_step"))
    reply_draft = _as_text(result.get("reply_draft"))
    needs_human = result.get("needs_human")
    human_reason = _as_text(result.get("human_reason"))

    lines = [
        "=== ДАННЫЕ ИЗ ФОРМЫ ===",
        f"Имя: {name or 'не указано'}",
        f"Телефон: {phone or 'не указано'}",
        f"Почта: {email or 'не указано'}",
        "",
        "=== ИСХОДНЫЙ ТЕКСТ ЗАЯВКИ ===",
        (original_text or "").strip() or "не указано",
        "",
        "=== АНАЛИЗ AI ===",
        f"Компания: {_as_text(result.get('company')) or 'не указано'}",
        f"Суть запроса: {summary or 'не указано'}",
        f"Тип лида: {lead_type or 'неясно'}",
        f"Известные данные:\n{key_data or 'не указано'}",
        f"Чего не хватает:\n{missing_data or 'не указано'}",
        f"Следующий шаг: {next_step or 'не указано'}",
        f"Нужен человек: {'Да' if needs_human else 'Нет'}",
        f"Причина передачи человеку: {human_reason or 'не требуется'}",
        "",
        "=== ЧЕРНОВИК ОТВЕТА ===",
        reply_draft or "не указано",
    ]
    for note in notes or []:
        note = str(note).strip()
        if note:
            lines.extend(["", f"Примечание: {note}"])
    return "\n".join(lines)


def _task_id(data: Dict[str, Any]) -> int | None:
    result = data.get("result")
    if isinstance(result, dict):
        task = result.get("task")
        if isinstance(task, dict):
            task = task.get("id")
        if task is not None:
            try:
                return int(task)
            except (TypeError, ValueError):
                return None
        if result.get("id") is not None:
            try:
                return int(result["id"])
            except (TypeError, ValueError):
                return None
    return None


def _create_task(
    webhook: str,
    manager_id: int,
    lead_id: int,
    contacts: Dict[str, str],
    result: Dict[str, Any],
    description: str,
) -> int | None:
    name = (contacts.get("name") or "").strip() or "без имени"
    lead_type = _as_text(result.get("lead_type")) or "неясно"
    title = f"Заявка: {name} ({lead_type})"
    if len(title) > 255:
        title = title[:252] + "..."

    fields: Dict[str, Any] = {
        "TITLE": title,
        "DESCRIPTION": description,
        "CREATED_BY": manager_id,
        "RESPONSIBLE_ID": manager_id,
        "PRIORITY": 2 if result.get("needs_human") else 1,
    }
    if lead_id:
        fields["UF_CRM_TASK"] = [f"L_{lead_id}"]

    try:
        data = _call(webhook, "tasks.task.add", {"fields": fields})
        return _task_id(data)
    except RuntimeError as error:
        logger.warning("Bitrix24 task create failed, retry without CRM link: %s", error)

    fields.pop("UF_CRM_TASK", None)
    data = _call(webhook, "tasks.task.add", {"fields": fields})
    return _task_id(data)


def _notify(
    webhook: str,
    manager_id: int,
    lead_id: int | None,
    task_id: int | None,
    contacts: Dict[str, str],
    result: Dict[str, Any],
) -> int | bool | None:
    name = (contacts.get("name") or "").strip() or "не указано"
    phone = (contacts.get("phone") or "").strip() or "не указано"
    lead_type = _as_text(result.get("lead_type")) or "неясно"
    needs_human = "Да" if result.get("needs_human") else "Нет"
    next_step = _as_text(result.get("next_step")) or "не указано"

    lines = [
        "Новая заявка в CRM",
        f"Клиент: {name}",
        f"Телефон: {phone}",
        f"Тип лида: {lead_type}",
        f"Нужен человек: {needs_human}",
        f"Следующий шаг: {next_step}",
    ]
    if lead_id:
        lines.append(f"Лид: #{lead_id}")
    if task_id:
        lines.append(f"Задача: #{task_id}")

    data = _call(
        webhook,
        "im.notify",
        {
            "USER_ID": manager_id,
            "TYPE": "SYSTEM",
            "MESSAGE": "\n".join(lines),
            "MESSAGE_OUT": "\n".join(lines),
        },
    )
    return data.get("result")


def send_lead_to_bitrix(
    contacts: Dict[str, str],
    result: Dict[str, Any],
    original_text: str,
    notes: list[str] | None = None,
) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "configured": False,
        "lead_id": None,
        "task_id": None,
        "notification_id": None,
        "errors": [],
    }

    webhook = _webhook_base()
    if not webhook:
        return status

    status["configured"] = True
    manager_id = _manager_id(webhook)
    comments = _comments(contacts, result, original_text, notes)

    try:
        data = _call(webhook, "crm.lead.add", {"fields": _lead_fields(contacts, result, comments)})
        lead_id = data.get("result")
        status["lead_id"] = int(lead_id) if lead_id is not None else None
    except Exception as error:
        logger.warning("Bitrix24 lead create failed: %s", error)
        status["errors"].append("lead")
        return status

    try:
        status["task_id"] = _create_task(
            webhook,
            manager_id,
            status["lead_id"] or 0,
            contacts,
            result,
            comments,
        )
    except Exception as error:
        logger.warning("Bitrix24 task create failed: %s", error)
        status["errors"].append("task")

    try:
        status["notification_id"] = _notify(
            webhook,
            manager_id,
            status["lead_id"],
            status["task_id"],
            contacts,
            result,
        )
    except Exception as error:
        logger.warning("Bitrix24 notification failed: %s", error)
        status["errors"].append("notification")

    return status
