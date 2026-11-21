import json
from unittest.mock import MagicMock

from backend import workflow_draft
from .test_workflow import API


def test_generated_graph_uses_telegram_and_rejects_email(client, project, monkeypatch):
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
