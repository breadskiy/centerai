import json
import logging
import os
import re

import httpx
from .db import Credential, cipher


class TelegramLogFilter(logging.Filter):
    def filter(self, record):
        if "api.telegram.org/bot" in record.getMessage():
            record.msg = "Telegram Bot API request"
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(TelegramLogFilter())


def configure(session, token, chat):
    previous = session.get(Credential, "telegram")
    if not token and previous:
        token = json.loads(cipher().decrypt(previous.encrypted))["token"]
    if not re.fullmatch(
        r"\d{5,20}:[A-Za-z0-9_-]{20,100}", token or ""
    ) or not re.fullmatch(r"-?\d{1,22}|@[A-Za-z0-9_]{5,32}", chat):
        raise ValueError("Проверьте токен бота и идентификатор чата")
    session.merge(
        Credential(
            provider="telegram",
            encrypted=cipher().encrypt(
                json.dumps({"token": token, "chat": chat}).encode()
            ),
        )
    )
    session.commit()


def telegram(session, run=None, count=0):
    row = session.get(Credential, "telegram")
    if not row:
        raise ValueError("Настройте Telegram в разделе настроек")
    config = json.loads(cipher().decrypt(row.encrypted))
    text = "CenterAI · Проверка подключения"
    if run:
        base = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
        text = f"{run.project_name} · {run.workflow_name}\nНаходок в отчёте: {count}\n{base}/runs/{run.id}"
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{config['token']}/sendMessage",
            json={"chat_id": config["chat"], "text": text},
            timeout=10,
        )
        if response.is_success:
            body = response.json()
            if isinstance(body, dict) and body.get("ok") is True:
                return {
                    "provider": "telegram",
                    "delivered": True,
                    "message_id": (body.get("result") or {}).get("message_id"),
                }
    except (httpx.HTTPError, ValueError):
        pass
    raise ValueError(
        "Telegram не подтвердил доставку. Проверьте настройки бота и чата."
    )
