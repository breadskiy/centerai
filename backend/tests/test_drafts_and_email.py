import json
import time
from unittest.mock import MagicMock

from sqlalchemy import select

from backend import auth, notifications, workflow_draft
from backend.db import Account, ReportEmail, Session
from backend.graph import default_graph
from backend.report_email import process_report_emails
from backend.worker import execute
from .test_workflow import API


def smtp_fixture(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.com")
    monkeypatch.setenv("SMTP_SECURITY", "local")
    monkeypatch.delenv("SMTP_USER", raising=False)
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value = smtp.return_value
    monkeypatch.setattr(notifications.smtplib, "SMTP", smtp)
    return smtp.return_value.send_message


def request_token(client, mail, **body):
    response = client.post(API + "/auth/email/verification", json=body)
    assert response.status_code == 202, response.text
    message = mail.call_args.args[0]
    assert str(message["From"]) == "noreply@example.com"
    recipient = body.get("email") or client.get(API + "/auth/session").json()["email"]
    assert str(message["To"]) == recipient
    return message.get_content().split("#verify-email=", 1)[1].split()[0]


def confirm(client, token):
    return client.post(API + "/auth/email/verify", json={"token": token})


def test_generated_graph_preserves_explicit_telegram_delivery(client, monkeypatch):
    plan = {
        "scanners": ["sca"],
        "levels": [],
        "cron": "0 9 * * 1-5",
        "timezone": "Europe/Moscow",
        "path_regex": "",
        "explanations": False,
        "notify": ["telegram"],
        "only_if_findings": True,
    }
    provider = MagicMock()
    provider.complete.side_effect = ["{}", json.dumps(plan), json.dumps(plan)]
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    response = client.post(
        API + "/workflow-drafts",
        json={
            "description": "Проверяй зависимости по будням. Только если есть находки, отправь отчёт в Telegram."
        },
    )
    assert response.status_code == 200
    graph = response.json()
    assert provider.complete.call_count == 2
    assert graph["nodes"][0]["config"]["enabled"] is False
    assert any(n["type"] == "notification" for n in graph["nodes"])
    response = client.post(
        API + "/workflow-drafts",
        json={"description": "Проверяй зависимости и сформируй отчёт."},
    )
    assert response.status_code == 200
    assert not any(
        n["type"] in ("notification", "if_else") for n in response.json()["nodes"]
    )
    assert client.get(API + "/workflows").json() == []
    monkeypatch.delenv("SMTP_HOST", raising=False)
    assert client.post(API + "/integrations/email/test").status_code == 503


def test_failed_draft_creates_nothing(client, monkeypatch):
    provider = MagicMock()
    provider.complete.side_effect = OSError()
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    response = client.post(
        API + "/workflow-drafts", json={"description": "Проверить проект"}
    )
    assert response.status_code == 422
    assert client.get(API + "/workflows").json() == []


def test_full_project_prompt_adds_all_scanners_even_if_model_returns_one(client, monkeypatch):
    provider = MagicMock()
    provider.complete.return_value = json.dumps(dict(
        scanners=["sast"], levels=[], cron="", timezone="Europe/Moscow",
        path_regex="", explanations=False, notify=[], only_if_findings=False,
    ))
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    for description, expected in (
        ("Проверь полностью проект", ["secrets_scanner", "sca_scanner", "sast_scanner"]),
        ("Проверь полность проект", ["secrets_scanner", "sca_scanner", "sast_scanner"]),
        ("Сделай полную проверку проекта без уведомлений", ["secrets_scanner", "sca_scanner", "sast_scanner"]),
        ("Используй все три анализатора", ["secrets_scanner", "sca_scanner", "sast_scanner"]),
        ("Проверь полностью проект, но только на секреты", ["secrets_scanner"]),
    ):
        response = client.post(API + "/workflow-drafts", json={"description": description})
        assert response.is_success, response.text
        graph = response.json()
        assert [node["type"] for node in graph["nodes"] if node["type"].endswith("_scanner")] == expected


def test_full_ai_prompt_connects_ai_before_email(monkeypatch):
    provider = MagicMock()
    plan = dict(
        scanners=["sast"], levels=[], cron="", timezone="Europe/Moscow",
        path_regex="", explanations=False, notify=[], only_if_findings=False,
    )
    provider.complete.return_value = json.dumps(plan)
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    graph = workflow_draft.draft(
        "Сделай полную проверку с AI и отчет пришли мне по почте",
        account_email="developer@example.com",
    )
    assert {node["type"] for node in graph["nodes"]} == {
        "manual_trigger", "repository_source", "secrets_scanner", "sca_scanner",
        "sast_scanner", "ai_analysis", "report_generator", "email_notification",
    }
    links = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert {(scanner, "ai_analysis") for scanner in ("secrets_scanner", "sca_scanner", "sast_scanner")} <= links
    assert {("ai_analysis", "report_generator"), ("report_generator", "email_notification")} <= links

    provider.complete.return_value = json.dumps({**plan, "explanations": True})
    graph = workflow_draft.draft("Сделай полную проверку без AI")
    assert not any(node["type"] == "ai_analysis" for node in graph["nodes"])


def test_draft_preserves_combined_request_when_qwen_omits_parts(monkeypatch):
    provider = MagicMock()
    provider.complete.return_value = json.dumps(dict(
        scanners=["sast"], levels=[], cron="", timezone="Europe/Moscow",
        path_regex="", explanations=False, notify=[], only_if_findings=False,
    ))
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    graph = workflow_draft.draft(
        "По будням в 9 утра сделай полную проверку без SAST. "
        "Покажи только критические и высокие находки, объясни их. "
        "При наличии находок отправь отчёт в Telegram и по почте.",
        account_email="developer@example.com", telegram_enabled=True,
    )
    nodes = {node["type"]: node["config"] for node in graph["nodes"]}
    assert set(nodes) == {
        "schedule_trigger", "repository_source", "secrets_scanner", "sca_scanner",
        "severity_filter", "ai_analysis", "if_else", "report_generator",
        "email_notification", "notification",
    }
    assert nodes["schedule_trigger"]["cron"] == "0 9 * * 1-5"
    assert nodes["severity_filter"]["levels"] == ["CRITICAL", "HIGH"]
    links = {(edge["source"], edge["target"], edge["branch"]) for edge in graph["edges"]}
    assert ("if_else", "report_generator", "true") in links
    assert ("if_else", "empty_report", "false") in links
    assert ("report_generator", "email_notification", "") in links
    assert ("report_generator", "notification", "") in links
    assert not any(source == "empty_report" for source, _, _ in links)


def test_daily_secret_scan_with_email_generates_runnable_graph(
    client, project, monkeypatch
):
    planned = dict(
        scanners=["secrets", "sast"],
        levels=["HIGH"],
        cron="",
        timezone="Europe/Moscow",
        path_regex="",
        explanations=False,
        notify=["email"],
        only_if_findings=False,
    )
    provider = MagicMock()
    provider.complete.return_value = json.dumps(planned)
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    prompt = {
        "description": "Каждый день в 14:00 проверяй код из репозитория на наличие секретов и отправляй отчёт на мою подтверждённую почту"
    }
    graph = client.post(API + "/workflow-drafts", json=prompt).json()
    assert graph["warnings"] and "Почта не настроена" in graph["warnings"][0]
    assert not any(node["type"] == "email_notification" for node in graph["nodes"])

    mail = smtp_fixture(monkeypatch)
    assert not client.get(API + "/registry").json()["email_available"]
    assert client.post(API + "/integrations/email/test").status_code == 403
    token = request_token(client, mail)
    assert confirm(client, token).json()["email_verified"] is True
    assert confirm(client, token).status_code == 422
    assert client.get(API + "/registry").json()["email_available"]
    graph = client.post(API + "/workflow-drafts", json=prompt).json()
    assert graph["warnings"] == []
    assert [node["type"] for node in graph["nodes"]] == [
        "schedule_trigger",
        "repository_source",
        "secrets_scanner",
        "report_generator",
        "email_notification",
    ]
    assert graph["nodes"][0]["config"] == {
        "cron": "0 14 * * *",
        "timezone": "Europe/Moscow",
        "enabled": False,
    }
    flow = client.post(
        API + "/workflows",
        json={
            "name": "Daily secrets",
            "project_id": project["id"],
            "graph": graph,
        },
    )
    assert flow.status_code == 201, flow.text
    assert flow.json()["next_due"] is None
    run = client.post(API + f"/workflows/{flow.json()['id']}/runs").json()
    mail.reset_mock()
    execute(run["id"])
    details = client.get(API + f"/runs/{run['id']}").json()
    assert details["status"] == "success"
    assert details["report_email"]["status"] == "queued"
    mail.assert_not_called()
    process_report_emails()
    process_report_emails()
    mail.assert_called_once()
    message = mail.call_args.args[0]
    assert str(message["To"]) == "developer@example.com"
    assert f"/runs/{run['id']}" in message.get_content()
    assert "HIGH:" in message.get_content()
    assert "synthetic_fixture" not in message.get_content()
    assert (
        client.get(API + f"/runs/{run['id']}").json()["report_email"]["status"]
        == "accepted"
    )


def test_verification_expiry_and_email_change_are_account_scoped(client, monkeypatch):
    mail = smtp_fixture(monkeypatch)
    token = request_token(client, mail)
    assert client.post(API + "/auth/email/verification", json={}).status_code == 429
    with Session() as db:
        account = db.scalar(select(Account))
        account.email_verification_sent_at = time.time() - auth.EMAIL_TTL - 1
        db.commit()
    assert confirm(client, token).status_code == 422
    token = request_token(client, mail)

    client.post(API + "/auth/logout")
    assert client.post(API + "/auth/guest").status_code == 201
    assert client.post(API + "/auth/email/verification", json={}).status_code == 403
    password = "Cedar-Morning62!"
    assert (
        client.post(
            API + "/auth/register",
            json={"email": "another@example.com", "password": password},
        ).status_code
        == 201
    )
    assert confirm(client, token).status_code == 422

    body = {"email": "changed@example.com", "password": "wrong-password"}
    assert client.post(API + "/auth/email/verification", json=body).status_code == 403
    body["password"] = password
    changed_token = request_token(client, mail, **body)
    assert client.get(API + "/auth/session").json()["email"] == "another@example.com"
    changed = confirm(client, changed_token).json()
    assert changed["email"] == "changed@example.com" and changed["email_verified"]


def test_smtp_retry_and_uncertainty_do_not_change_scan_result(
    client, project, monkeypatch
):
    mail = smtp_fixture(monkeypatch)
    assert confirm(client, request_token(client, mail)).is_success
    graph = default_graph()
    report = next(
        node["id"] for node in graph["nodes"] if node["type"] == "report_generator"
    )
    graph["nodes"].append({"id": "email", "type": "email_notification"})
    graph["edges"].append({"source": report, "target": "email"})
    flow = client.post(
        API + "/workflows",
        json={
            "name": "Delivery test",
            "project_id": project["id"],
            "graph": graph,
        },
    ).json()
    run = client.post(API + f"/workflows/{flow['id']}/runs").json()
    execute(run["id"])
    mail.reset_mock()
    mail.side_effect = [
        notifications.smtplib.SMTPDataError(451, b"try later"),
        TimeoutError(),
    ]
    process_report_emails()
    path = API + f"/runs/{run['id']}"
    details = client.get(path).json()
    assert details["report_email"]["status"] == "queued"
    assert details["report_email"]["attempts"] == 1
    with Session() as db:
        db.get(ReportEmail, run["id"]).due = 0
        db.commit()
    process_report_emails()
    process_report_emails()
    assert mail.call_count == 2
    assert (
        mail.call_args_list[0].args[0]["Message-ID"]
        == mail.call_args_list[1].args[0]["Message-ID"]
    )
    details = client.get(path).json()
    assert details["status"] == "success"
    assert details["report_email"]["status"] == "uncertain"
    assert client.get(path + "/report").is_success

    new_run = client.post(API + f"/workflows/{flow['id']}/runs").json()
    execute(new_run["id"])
    mail.reset_mock(side_effect=True)
    new_token = request_token(
        client, mail, email="new-owner@example.com", password="Tangerine-River42!"
    )
    assert confirm(client, new_token).is_success
    process_report_emails()
    mail.assert_called_once()  # Only the verification request, no old-address report.
    assert (
        client.get(API + f"/runs/{new_run['id']}").json()["report_email"]["status"]
        == "skipped"
    )


def test_prompt_recipient_must_be_confirmed_and_can_be_revoked(
    client, project, monkeypatch
):
    mail = smtp_fixture(monkeypatch)
    provider = MagicMock()
    provider.complete.return_value = json.dumps(
        dict(
            scanners=["sca"],
            levels=[],
            cron="",
            timezone="Europe/Moscow",
            path_regex="",
            explanations=False,
            notify=[],
            only_if_findings=False,
        )
    )
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    address = "reports@example.com"
    description = f"Проверь зависимости и отправь отчёт на {address}."

    def draft(text):
        response = client.post(API + "/workflow-drafts", json={"description": text})
        assert response.is_success, response.text
        return response.json()

    def email_node(graph):
        return next(
            (node for node in graph["nodes"] if node["type"] == "email_notification"),
            None,
        )

    token = request_token(
        client, mail, email=address, password="Tangerine-River42!", reports_only=True
    )
    before = draft(description)
    assert email_node(before) is None and before["warnings"]
    viewer = confirm(client, token).json()
    assert viewer["email"] == "developer@example.com"
    assert viewer["email_verified"] is False
    assert viewer["report_recipient"] == address

    for destination in (address, f"почту {address}", f"мою подтверждённую почту: {address}"):
        graph = draft(f"Проверь зависимости и отправь отчёт на {destination}.")
        assert email_node(graph)["config"] == {"recipient": address}
        assert address not in provider.complete.call_args.args[0][-1]["content"]
    assert email_node(draft("Проверь зависимости и отправь отчёт на почту")) is None
    assert email_node(draft(description.rstrip(".") + ", other@example.com")) is None
    workflow = client.post(
        API + "/workflows",
        json={
            "name": "Recipient selected in prompt",
            "project_id": project["id"],
            "graph": {"nodes": graph["nodes"], "edges": graph["edges"]},
        },
    ).json()

    def queue():
        scan = client.post(API + f"/workflows/{workflow['id']}/runs").json()
        execute(scan["id"])
        return API + "/runs/" + scan["id"]

    mail.reset_mock()
    path = queue()
    process_report_emails()
    mail.assert_called_once()
    assert str(mail.call_args.args[0]["To"]) == address
    assert client.get(path).json()["report_email"]["status"] == "accepted"

    path = queue()
    assert client.delete(API + "/auth/email/report-recipient").is_success
    process_report_emails()
    mail.assert_called_once()
    assert client.get(path).json()["report_email"]["status"] == "skipped"
