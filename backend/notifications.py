import json
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import urlsplit

import httpx

from .db import Credential, Project, cipher


class TelegramLogFilter(logging.Filter):
    def filter(self, record):
        if "api.telegram.org/bot" in record.getMessage():
            record.msg = "Telegram Bot API request"
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(TelegramLogFilter())


class MailError(Exception):
    def __init__(self, message, *, retry=False, uncertain=False):
        super().__init__(message)
        self.retry = retry
        self.uncertain = uncertain


def public_url():
    base = (os.getenv("PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")
    try:
        url = urlsplit(base)
    except ValueError:
        raise MailError("Укажите доступный адрес приложения в PUBLIC_URL.") from None
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username is not None
        or url.query
        or url.fragment
        or url.path
    ):
        raise MailError("Укажите доступный адрес приложения в PUBLIC_URL.")
    return base


def mail_configured():
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def verified_report_addresses(account):
    if not account or not account.email:
        return ()
    return tuple(
        dict.fromkeys(
            address
            for address in (
                account.email if account.email_verified_at else None,
                account.report_recipient,
            )
            if address
        )
    )


def report_email_enabled(account):
    return bool(mail_configured() and verified_report_addresses(account))


def send_email(recipient, subject, text, *, message_id=None):
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        raise MailError("Почтовый сервер не настроен.")
    mode = os.getenv("SMTP_SECURITY", "starttls")
    if mode not in ("ssl", "starttls", "local") or (
        mode == "local"
        and (host not in ("localhost", "127.0.0.1", "::1") or os.getenv("SMTP_USER"))
    ):
        raise MailError("Проверьте режим защиты SMTP.")
    try:
        port = int(
            os.getenv("SMTP_PORT") or {"ssl": 465, "starttls": 587, "local": 1025}[mode]
        )
        if not 1 <= port <= 65535:
            raise ValueError
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
        msg["Message-ID"] = message_id or make_msgid()
        msg.set_content(text)
    except (ValueError, TypeError):
        raise MailError("Проверьте параметры SMTP и адрес отправителя.") from None

    submitting = accepted = False
    try:
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
            submitting = True
            smtp.send_message(msg)
            accepted = True
    except smtplib.SMTPRecipientsRefused as exc:
        code = next(iter(exc.recipients.values()), (550, b""))[0]
        raise MailError(
            "SMTP-сервер отклонил адрес получателя.", retry=400 <= code < 500
        ) from None
    except smtplib.SMTPResponseException as exc:
        if not accepted:
            raise MailError(
                "SMTP-сервер отклонил письмо.", retry=400 <= exc.smtp_code < 500
            ) from None
    except (ssl.SSLCertVerificationError, smtplib.SMTPNotSupportedError):
        raise MailError("Не удалось установить защищённое SMTP-соединение.") from None
    except (OSError, smtplib.SMTPException):
        if not accepted:
            raise MailError(
                "SMTP-сервер не подтвердил приём письма.",
                retry=not submitting,
                uncertain=submitting,
            ) from None


def telegram_connected(session, owner_id):
    return session.get(Credential, f"telegram:{owner_id}") is not None


def disconnect_telegram(session, owner_id):
    row = session.get(Credential, f"telegram:{owner_id}")
    if row:
        session.delete(row)
        session.commit()


def configure(session, token, chat, owner_id):
    provider = f"telegram:{owner_id}"
    previous = session.get(Credential, provider)
    if not token and previous:
        token = json.loads(cipher().decrypt(previous.encrypted))["token"]
    if not re.fullmatch(
        r"\d{5,20}:[A-Za-z0-9_-]{20,100}", token or ""
    ) or not re.fullmatch(r"-?\d{1,22}|@[A-Za-z0-9_]{5,32}", chat):
        raise ValueError("Проверьте токен бота и идентификатор чата")
    session.merge(
        Credential(
            provider=provider,
            encrypted=cipher().encrypt(
                json.dumps({"token": token, "chat": chat}).encode()
            ),
        )
    )
    session.commit()


def telegram(session, run=None, count=0, *, owner_id=None):
    if run:
        owner_id = session.get(Project, run.project_id).owner_id
    row = session.get(Credential, f"telegram:{owner_id}") if owner_id else None
    if not row:
        raise ValueError("Настройте Telegram через API")
    config = json.loads(cipher().decrypt(row.encrypted))
    text = "CenTRap · Проверка подключения"
    if run:
        base = os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/")
        text = f"{run.project_name} · {run.workflow_name}\nОбнаружено в отчёте: {count}\n{base}/runs/{run.id}"
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
