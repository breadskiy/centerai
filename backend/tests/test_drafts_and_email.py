import json
from unittest.mock import MagicMock

from backend import notifications, workflow_draft
from backend.worker import execute
from .test_workflow import API


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
        json={"description": "Проверяй зависимости по будням. Только если есть находки, отправь отчёт в Telegram."},
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
    assert not any(n["type"] in ("notification", "if_else") for n in response.json()["nodes"])
    assert client.get(API + "/workflows").json() == []
    assert client.post(API + "/integrations/email/test").status_code == 410


def test_failed_draft_creates_nothing(client, monkeypatch):
    provider = MagicMock()
    provider.complete.side_effect = OSError()
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    response = client.post(
        API + "/workflow-drafts", json={"description": "Проверить проект"}
    )
    assert response.status_code == 422
    assert client.get(API + "/workflows").json() == []


def test_daily_secret_scan_with_email_generates_runnable_graph(client, project, monkeypatch):
    planned = dict(
        scanners=["secrets", "sast"], levels=["HIGH"], cron="", timezone="Europe/Moscow",
        path_regex="", explanations=False, notify=["email"], only_if_findings=False,
    )
    provider = MagicMock()
    provider.complete.return_value = json.dumps(planned)
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    monkeypatch.delenv("SMTP_REPORT_RECIPIENT", raising=False)
    prompt = {"description": "Каждый день в 14:00 проверяй код из репозитория на наличие секретов и отправляй отчёт на почту"}
    graph = client.post(API + "/workflow-drafts", json=prompt).json()
    assert graph["warnings"] and "Почта не настроена" in graph["warnings"][0]
    assert not any(node["type"] == "email_notification" for node in graph["nodes"])

    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_REPORT_RECIPIENT", "developer@example.com")
    monkeypatch.setenv("SMTP_SECURITY", "local")
    monkeypatch.delenv("SMTP_USER", raising=False)
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value = smtp.return_value
    monkeypatch.setattr(notifications.smtplib, "SMTP", smtp)
    assert client.get(API + "/registry").json()["email_available"]
    assert not notifications.report_email_enabled("another@example.com")
    graph = client.post(API + "/workflow-drafts", json=prompt).json()
    assert graph["warnings"] == []
    assert [node["type"] for node in graph["nodes"]] == [
        "schedule_trigger", "repository_source", "secrets_scanner",
        "report_generator", "email_notification",
    ]
    assert graph["nodes"][0]["config"] == {
        "cron": "0 14 * * *", "timezone": "Europe/Moscow", "enabled": False,
    }
    flow = client.post(API + "/workflows", json={
        "name": "Daily secrets", "project_id": project["id"], "graph": graph,
    })
    assert flow.status_code == 201, flow.text
    assert flow.json()["next_due"] is None
    run = client.post(API + f"/workflows/{flow.json()['id']}/runs").json()
    execute(run["id"])
    assert client.get(API + f"/runs/{run['id']}").json()["status"] == "success"
    message = smtp.return_value.send_message.call_args.args[0]
    assert str(message["To"]) == "developer@example.com"
    assert f"/runs/{run['id']}" in message.get_content()
