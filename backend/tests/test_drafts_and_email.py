import json
from unittest.mock import MagicMock

from backend import notifications, workflow_draft
from backend.worker import tick
from .test_workflow import API, create_flow


def test_generated_graph_and_email_delivery(client, project, monkeypatch):
    plan = {
        "scanners": ["sca"],
        "levels": [],
        "cron": "0 9 * * 1-5",
        "timezone": "Europe/Moscow",
        "path_regex": "",
        "explanations": False,
        "notify": ["email"],
        "only_if_findings": True,
    }
    provider = MagicMock()
    provider.complete.side_effect = ["{}", json.dumps(plan)]
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    graph = client.post(
        API + "/workflow-drafts",
        json={"description": "Проверяй зависимости по будням и пришли письмо"},
    ).json()
    assert provider.complete.call_count == 2
    assert graph["nodes"][0]["config"]["enabled"] is False
    assert client.get(API + "/workflows").json() == []
    flow = create_flow(client, project, graph)
    address = API + "/integrations/email"
    assert (
        client.put(
            address, json={"recipient": "a@test.local\r\nCc:b@test.local"}
        ).status_code
        == 422
    )
    assert (
        client.put(address, json={"recipient": "qa@example.test"}).json()[
            "email_recipient"
        ]
        == "qa@example.test"
    )
    monkeypatch.setenv("SMTP_HOST", "mail.example.test")
    monkeypatch.setenv("SMTP_SECURITY", "starttls")
    monkeypatch.setenv("SMTP_USER", "test-user")
    monkeypatch.setenv("SMTP_PASSWORD", "fixture")
    smtp = MagicMock()
    monkeypatch.setattr(notifications.smtplib, "SMTP", lambda *a, **kw: smtp)
    run = client.post(f"{API}/workflows/{flow['id']}/runs").json()
    tick()
    path = f"{API}/runs/{run['id']}"
    assert client.get(path).json()["status"] == "success"
    assert client.get(path + "/nodes/email_notification").json()["output"]["receipt"][
        "accepted"
    ]
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("test-user", "fixture")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "qa@example.test" and run["id"] in message.get_content()
    smtp.send_message.side_effect = OSError("private diagnostic")
    response = client.post(address + "/test")
    assert response.status_code == 422 and "private diagnostic" not in response.text


def test_failed_draft_creates_nothing(client, monkeypatch):
    provider = MagicMock()
    provider.complete.side_effect = OSError()
    monkeypatch.setattr(workflow_draft, "configured_provider", lambda: provider)
    response = client.post(
        API + "/workflow-drafts", json={"description": "Проверить проект"}
    )
    assert response.status_code == 422
    assert client.get(API + "/workflows").json() == []
