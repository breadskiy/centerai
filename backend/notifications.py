import json
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

import httpx
from .db import Credential, cipher


class TelegramLogFilter(logging.Filter):
    def filter(self, record):
        if "api.telegram.org/bot" in record.getMessage():
            record.msg = "Telegram Bot API request"
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(TelegramLogFilter())


def email_recipient(session):
    row = session.get(Credential, "email")
    return cipher().decrypt(row.encrypted).decode() if row else ""


def configure_email(session, recipient):
    if not re.fullmatch(r"[\w.+%-]+@[\w.-]+\.[\w-]+", recipient, re.ASCII):
        raise ValueError("Введите один адрес получателя")
    session.merge(
        Credential(provider="email", encrypted=cipher().encrypt(recipient.encode()))
    )
    session.commit()


def send_email(session, run=None, count=0):
    host = os.getenv("SMTP_HOST")
    recipient = email_recipient(session)
    if not host or not recipient:
        raise ValueError("Настройте SMTP на сервере и сохраните адрес получателя")
    mode = os.getenv("SMTP_SECURITY", "starttls")
    if mode not in ("ssl", "starttls", "local") or (
        mode == "local"
        and (host not in ("localhost", "127.0.0.1", "::1") or os.getenv("SMTP_USER"))
    ):
        raise ValueError("Проверьте режим защиты SMTP")
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or "centerai@localhost"
    msg["To"] = recipient
    msg["Message-ID"] = make_msgid()
    msg["Subject"] = (
        "CenterAI · Результат проверки" if run else "CenterAI · Проверка почты"
    )
    text = "Почтовый канал CenterAI работает."
    if run:
        base = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
        text = f"{run.project_name} · {run.workflow_name}\nНаходок: {count}\n{base}/runs/{run.id}"
    msg.set_content(text)
    try:
        port = int(os.getenv("SMTP_PORT") or (465 if mode == "ssl" else 587))
        context = ssl.create_default_context()
        smtp = (
            smtplib.SMTP_SSL(host, port, timeout=12, context=context)
            if mode == "ssl"
            else smtplib.SMTP(host, port, timeout=12)
        )
        with smtp:
            if mode == "starttls":
                smtp.starttls(context=context)
            if os.getenv("SMTP_USER"):
                smtp.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
            smtp.send_message(msg)
    except (ValueError, OSError, smtplib.SMTPException):
        raise ValueError(
            "SMTP-сервер не подтвердил приём письма. Проверьте параметры подключения."
        ) from None
    return {"provider": "email", "accepted": True, "message_id": str(msg["Message-ID"])}


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
