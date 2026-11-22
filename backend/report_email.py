"""Persistent, per-run report delivery using the workspace worker."""

import time
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from .db import Account, Finding, Project, ReportEmail, Run, Session
from .graph import LEVELS
from .notifications import (
    MailError,
    mail_configured,
    public_url,
    send_email,
    verified_report_addresses,
)

RETRY_DELAYS = (30, 120)
SEND_LEASE = 300
UNCONFIRMED = "Почтовый сервер не подтвердил приём письма."


def queue_report_email(db, run, requested):
    account = db.get(Account, db.get(Project, run.project_id).owner_id)
    error = None
    primary = account.email if account else None
    recipients = {address or primary for address in requested}
    recipient = next(iter(recipients))
    if len(recipients) > 1:
        error = "В запуске указано несколько адресов для отчёта."
    elif recipient not in verified_report_addresses(account):
        error = "Подтвердите адрес для отчётов в личном кабинете."
    elif not mail_configured():
        error = "Почтовый сервер не настроен."
    db.add(
        ReportEmail(
            run_id=run.id,
            recipient=recipient if not error else None,
            status="skipped" if error else "queued",
            due=time.time(),
            error=error,
        )
    )


def send_report_email(run_id):
    now = time.time()
    with Session() as db:
        claimed = db.execute(
            update(ReportEmail)
            .where(
                ReportEmail.run_id == run_id,
                ReportEmail.status == "queued",
                ReportEmail.due <= now,
            )
            .values(
                status="sending",
                due=now + SEND_LEASE,
                attempts=ReportEmail.attempts + 1,
            )
        )
        db.commit()
        if not claimed.rowcount:
            return
        job = db.get(ReportEmail, run_id)
        if job is None:
            return
        run = db.get(Run, run_id)
        if run is None:
            return
        account = db.get(Account, db.get(Project, run.project_id).owner_id)
        recipient, attempts = job.recipient, job.attempts
        if recipient not in verified_report_addresses(account):
            job.status = "skipped"
            job.error = "Адрес владельца изменился или не подтверждён."
            job.recipient = None
            db.commit()
            return
        counts = dict(
            db.execute(
                select(Finding.severity, func.count())
                .where(Finding.run_id == run_id)
                .group_by(Finding.severity)
            ).all()
        )
        title = " ".join(run.project_name.split())[:120]
        scan_name = " ".join(run.workflow_name.split())[:120]
        date = datetime.fromtimestamp(run.finished, timezone.utc).strftime(
            "%Y-%m-%d %H:%M UTC"
        )
        total = run.count
        db.rollback()  # Release the DB connection before doing SMTP.

    status, error, due = "accepted", None, now
    try:
        text = "\n".join(
            [
                f"Сессия: {title}",
                f"Сценарий: {scan_name}",
                f"Завершено: {date}",
                f"Обнаружено: {total}",
                *(f"{level}: {counts.get(level, 0)}" for level in LEVELS),
                "",
                f"Открыть отчёт: {public_url()}/runs/{run_id}",
                "",
                "Письмо отправлено автоматически. Ответы не обрабатываются.",
            ]
        )
        send_email(
            recipient,
            f"CenterAI · Проверка завершена · {title}",
            text,
            message_id=f"<report-{run_id}@centerai>",
        )
    except MailError as exc:
        error = str(exc)
        if exc.retry and attempts <= len(RETRY_DELAYS):
            status, due = "queued", time.time() + RETRY_DELAYS[attempts - 1]
        else:
            status = "uncertain" if exc.uncertain else "failed"
    with Session() as db:
        db.execute(
            update(ReportEmail)
            .where(
                ReportEmail.run_id == run_id,
                ReportEmail.status == "sending",
                ReportEmail.attempts == attempts,
            )
            .values(
                status=status,
                due=due,
                error=error,
                recipient=recipient if status == "queued" else None,
            )
        )
        db.commit()


def process_report_emails():
    now = time.time()
    with Session() as db:
        db.execute(
            update(ReportEmail)
            .where(ReportEmail.status == "sending", ReportEmail.due <= now)
            .values(status="uncertain", error=UNCONFIRMED, recipient=None)
        )
        ids = db.scalars(
            select(ReportEmail.run_id)
            .where(ReportEmail.status == "queued", ReportEmail.due <= now)
            .order_by(ReportEmail.due)
            .limit(4)
        ).all()
        db.commit()
    for run_id in ids:
        send_report_email(run_id)
