import json
import logging
import os
import time
from collections import Counter

from celery import Celery
from sqlalchemy import select, update

from .analyzers import SCANNERS
from .auth import cleanup_sessions
from .db import (
    Account,
    Event,
    Finding,
    NodeRun,
    Project,
    Run,
    Session,
    Workflow,
    cipher,
)
from .graph import REGISTRY, Context, Packet, next_due, validate
from .node_config import EmailConfig
from .report_email import process_report_emails, queue_report_email

log = logging.getLogger(__name__)
celery = Celery("centerai", broker=os.getenv("REDIS_URL", "redis://redis:6379/0"))
celery.conf.update(
    beat_schedule={"process-workspace": {"task": "centerai.tick", "schedule": 2.0}},
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
)


def record(session, run, status, message, node=None):
    session.add(Event(run_id=run.id, status=status, message=message, node_id=node))


def enqueue(session, workflow, trigger):
    validate(workflow.graph)
    project = session.get(Project, workflow.project_id)
    run = Run(
        workflow_id=workflow.id,
        project_id=project.id,
        workflow_name=workflow.name,
        project_name=project.name,
        revision=workflow.revision,
        graph=workflow.graph,
        trigger=trigger,
    )
    session.add(run)
    session.flush()
    session.add_all(
        [
            NodeRun(run_id=run.id, node_id=n["id"], status="pending")
            for n in run.graph["nodes"]
        ]
    )
    record(session, run, "queued", "Запуск поставлен в очередь")
    return run


def complete_cancellation(db, run):
    run.status, run.finished = "cancelled", time.time()
    db.execute(
        update(NodeRun)
        .where(NodeRun.run_id == run.id, NodeRun.status == "pending")
        .values(status="cancelled", finished=run.finished)
    )
    record(db, run, "cancelled", "Проверка отменена оператором")
    db.commit()


def request_cancellation(db, run):
    # Serialize cancellation with claiming a queued run. The worker checks the
    # same flag between nodes, allowing an in-flight external call to finish.
    queued = db.execute(
        update(Run)
        .where(Run.id == run.id, Run.status == "queued")
        .values(cancel_requested=True, status="cancelled")
    )
    if queued.rowcount:
        complete_cancellation(db, run)
        return
    db.execute(
        update(Run)
        .where(Run.id == run.id, Run.status == "running")
        .values(cancel_requested=True)
    )
    db.commit()
    db.refresh(run)


def execute(run_id):
    now = time.time()
    with Session() as db:
        claimed = db.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "queued")
            .values(status="running", started=now, heartbeat=now)
        )
        if not claimed.rowcount:
            return
        run = db.get(Run, run_id)
        record(db, run, "running", "Проверка началась")
        db.commit()
        current = None
        try:
            nodes, parents, order = validate(run.graph)
            files = json.loads(
                cipher().decrypt(db.get(Project, run.project_id).snapshot)
            )
            ctx = Context(db, run, files)
            packets, reports = {}, {}
            email_recipients = set()
            for node_id in order:
                db.refresh(run, attribute_names=["cancel_requested"])
                if run.cancel_requested:
                    complete_cancellation(db, run)
                    return
                node = nodes[node_id]
                current = db.get(NodeRun, (run.id, node_id))
                links = parents[node_id]
                active = [
                    packets[e.source]
                    for e in links
                    if e.source in packets
                    and (not e.branch or packets[e.source].branch == e.branch)
                ]
                if links and not active:
                    current.status, current.finished = "skipped", time.time()
                    record(db, run, "skipped", "Условие ветви не выполнено", node_id)
                    db.commit()
                    continue
                current.status, current.started = "running", time.time()
                run.heartbeat = time.time()
                record(db, run, "running", REGISTRY[node.type].title, node_id)
                db.commit()
                merged = {}
                for packet in active:
                    for key, finding in packet.findings.items():
                        if key not in merged or "ai" in finding:
                            merged[key] = finding
                data = Packet(
                    merged,
                    files=next((p.files for p in active if p.files is not None), None),
                )
                output = REGISTRY[node.type].execute(ctx, node.config, data)
                if node.type == "email_notification":
                    email_recipients.add(EmailConfig.model_validate(node.config).recipient)
                packets[node_id] = output
                current.output = {
                    "count": len(output.findings),
                    "ids": list(output.findings),
                    "branch": output.branch,
                }
                if output.receipt:
                    current.output["receipt"] = output.receipt
                if node.type == "ai_analysis":
                    current.output["ai"] = output.ai
                if node.type in SCANNERS:
                    current.output["findings"] = [
                        row
                        for key, row in output.findings.items()
                        if key not in data.findings
                    ]
                if node.type in SCANNERS or node.type == "report_generator":
                    rows = current.output.get("findings", output.findings.values())
                    current.output["levels"] = dict(
                        Counter(row["severity"] for row in rows)
                    )
                if node.type == "repository_source":
                    current.output = {"files": len(files)}
                if node.type == "report_generator":
                    for key, row in output.findings.items():
                        if key not in reports:
                            db.add(
                                Finding(
                                    run_id=run.id,
                                    fingerprint=key,
                                    severity=row["severity"],
                                    category=row["category"],
                                    detail=row,
                                )
                            )
                        elif "ai" in row and "ai" not in reports[key]:
                            db.execute(
                                update(Finding)
                                .where(
                                    Finding.run_id == run.id, Finding.fingerprint == key
                                )
                                .values(detail=row)
                            )
                        elif "ai" in reports[key]:
                            continue
                        reports[key] = row
                    run.count = len(reports)
                current.status, current.finished = "success", time.time()
                record(
                    db,
                    run,
                    "success",
                    f"Завершено · находок {len(output.findings)}",
                    node_id,
                )
                db.commit()
            db.refresh(run, attribute_names=["cancel_requested"], with_for_update=True)
            if run.cancel_requested:
                complete_cancellation(db, run)
                return
            run.status = "success"
            if email_recipients:
                queue_report_email(db, run, email_recipients)
            record(db, run, "success", "Проверка завершена")
        except Exception as exc:
            db.rollback()
            run.status = "failed"
            run.error = (
                str(exc)
                if type(exc) is ValueError
                else "Ошибка обработки данных на этапе проверки"
            )
            if current:
                current.status, current.finished = "failed", time.time()
            db.execute(
                update(NodeRun)
                .where(NodeRun.run_id == run.id, NodeRun.status == "pending")
                .values(status="skipped")
            )
            record(db, run, "failed", run.error, current.node_id if current else None)
        run.finished = time.time()
        db.commit()


@celery.task(name="centerai.tick", expires=10)
def tick():
    now = time.time()
    with Session() as db:
        for flow in db.scalars(
            select(Workflow)
            .join(Project, Workflow.project_id == Project.id)
            .join(Account, Project.owner_id == Account.id)
            .where(
                Account.email.is_not(None),
                Workflow.archived.is_(False),
                Workflow.next_due <= now,
            )
        ):
            cfg = next(
                n["config"]
                for n in flow.graph["nodes"]
                if n["type"] == "schedule_trigger"
            )
            claimed = db.execute(
                update(Workflow)
                .where(
                    Workflow.id == flow.id,
                    Workflow.next_due == flow.next_due,
                    Workflow.revision == flow.revision,
                )
                .values(next_due=next_due(cfg, now))
            )
            if claimed.rowcount:
                enqueue(db, flow, "schedule")
        # A lost worker must not replay external notification side effects.
        for run in db.scalars(
            select(Run).where(Run.status == "running", Run.heartbeat < now - 900)
        ):
            run.status, run.finished, run.error = (
                "failed",
                now,
                "Выполнение прервано после остановки обработчика",
            )
            db.execute(
                update(NodeRun)
                .where(NodeRun.run_id == run.id, NodeRun.status == "running")
                .values(status="failed", finished=now)
            )
            db.execute(
                update(NodeRun)
                .where(NodeRun.run_id == run.id, NodeRun.status == "pending")
                .values(status="skipped")
            )
            record(db, run, "failed", run.error)
        db.commit()
        cleanup_sessions(db, now)
        db.commit()
        queued = db.scalars(
            select(Run.id)
            .join(Project, Run.project_id == Project.id)
            .join(Account, Project.owner_id == Account.id)
            .where(
                Run.status == "queued",
                (Account.guest_until.is_(None) | (Account.guest_until > now)),
            )
            .order_by(Run.created)
            .limit(4)
        ).all()
    for run_id in queued:
        execute(run_id)
    process_report_emails()


def local_worker(stop):
    while not stop.is_set():
        try:
            tick()
        except Exception:
            log.error("Worker cycle failed; retrying")
        stop.wait(0.5)
