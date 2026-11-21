import json
import logging
from threading import Event, Thread
from unittest.mock import Mock

import pytest
from backend.analyzers import SCANNERS, secrets, sca
from backend.analyzers.common import SubmissionReportExporter
from backend.graph import default_graph
from backend.worker import execute, tick
from .test_workflow import API, create_flow


def test_validate_schema_and_draft(client, project):
    registry = client.get(API + "/registry").json()["types"]
    assert set(registry["if_else"]["config_schema"]["required"]) == {
        "operator",
        "count",
    }
    graph = default_graph()
    flow = create_flow(client, project, graph)
    path = API + "/workflows/" + flow["id"]
    graph["nodes"][0].update(
        type="schedule_trigger",
        config={"cron": "* * * * *", "timezone": "Unknown/Zone", "enabled": False},
    )
    assert client.post(path + "/validate", json=graph).status_code == 422
    graph["nodes"][0]["type"] = "missing_kind"
    assert client.put(path, json={**flow, "graph": graph}).status_code == 422
    assert client.get(path).json()["revision"] == 1


def test_published_snapshot_survives_changes(client, project):
    flow = create_flow(client, project)
    path = API + "/workflows/" + flow["id"]
    assert client.get(API + "/templates").json() == []
    assert client.post(path + "/versions/1/publish").status_code == 200
    assert client.post(path + "/versions/1/publish").status_code == 200
    graph = flow["graph"]
    graph["nodes"][0].update(
        type="schedule_trigger",
        config={"cron": "0 9 * * *", "timezone": "Europe/Moscow", "enabled": True},
    )
    assert (
        client.put(path, json={**flow, "graph": graph, "name": "Scheduled"}).status_code
        == 200
    )
    assert client.post(path + "/versions/2/publish").status_code == 200
    client.delete(path).raise_for_status()
    templates = client.get(API + "/templates").json()
    assert [v["name"] for v in templates] == ["Scheduled", "Pipeline"]
    copy = client.post(
        API + f"/templates/{flow['id']}/2/copies",
        json={"name": "Reusable", "project_id": project["id"]},
    ).json()
    assert (
        copy["next_due"] is None
        and copy["graph"]["nodes"][0]["config"]["enabled"] is False
    )
    assert templates[0]["graph"]["nodes"][0]["config"]["enabled"] is True
    assert copy["id"] != flow["id"] and copy["revision"] == 1
    assert client.post(API + "/workflows/" + copy["id"] + "/runs").status_code == 202
    tick()
    assert client.get(API + "/runs").json()[0]["count"] == 2


def test_cancel_queued_and_idempotent(client, project):
    flow = create_flow(client, project)
    run = client.post(API + "/workflows/" + flow["id"] + "/runs").json()
    path = API + "/runs/" + run["id"]
    for _ in range(2):
        assert client.post(path + "/cancel").json()["status"] == "cancelled"
    tick()
    details = client.get(path).json()
    assert all(n["status"] == "cancelled" for n in details["nodes"])
    assert details["started"] is None
    assert sum(e["status"] == "cancelled" for e in details["events"]) == 1
    assert client.get(path + "/report/preview").json()["partial"] is True


def test_cancel_during_analysis(client, project, monkeypatch):
    entered, release = Event(), Event()
    real = SCANNERS["secrets_scanner"]

    def paused(files):
        entered.set()
        assert release.wait(5)
        return real(files)

    monkeypatch.setitem(SCANNERS, "secrets_scanner", paused)
    flow = create_flow(client, project)
    run = client.post(API + "/workflows/" + flow["id"] + "/runs").json()
    path = API + "/runs/" + run["id"]
    thread = Thread(target=execute, args=(run["id"],))
    thread.start()
    try:
        assert entered.wait(5)
        assert client.post(path + "/cancel").json()["cancel_requested"]
    finally:
        release.set()
        thread.join(8)
    assert not thread.is_alive()
    details = client.get(path).json()
    assert details["status"] == "cancelled"
    statuses = {n["node_id"]: n["status"] for n in details["nodes"]}
    assert (
        statuses["secrets_scanner"] == "success"
        and statuses["report_generator"] == "cancelled"
    )


def test_notification_receipt_and_report(client, project, monkeypatch, caplog):
    graph = default_graph()
    graph["nodes"].append({"id": "send", "type": "notification", "config": {}})
    graph["edges"].append(
        {"source": "report_generator", "target": "send", "branch": ""}
    )
    flow = create_flow(client, project, graph)
    token = "123456:" + ("x" * 30)
    settings = client.put(
        API + "/integrations/telegram", json={"token": token, "chat": "1234"}
    )
    assert settings.status_code == 200

    def accept(url, **kwargs):
        logging.getLogger("httpx").info("POST %s", url)
        return Mock(
            is_success=True, json=lambda: {"ok": True, "result": {"message_id": 42}}
        )

    monkeypatch.setattr("backend.notifications.httpx.post", accept)
    caplog.set_level(logging.INFO, logger="httpx")
    run = client.post(API + "/workflows/" + flow["id"] + "/runs").json()
    tick()
    path = API + "/runs/" + run["id"]
    receipt = client.get(path + "/nodes/send").json()["output"]["receipt"]
    assert receipt == {"provider": "telegram", "delivered": True, "message_id": 42}
    preview = client.get(path + "/report/preview").json()
    assert preview["valid"] and not preview["partial"]
    assert preview["count"] == len(client.get(path + "/report").json()["findings"]) == 2
    assert token not in caplog.text + json.dumps(preview)
    assert (
        client.get(path + "/events", headers={"last-event-id": "bad"}).status_code
        == 422
    )


def test_secret_variations():
    lines = [
        'val first = "training_part_"',
        'val second = "fixture42"',
        "val joined = first +",
        "    second",
        "fun headers(h: Headers) { h.setBearerAuth(joined) }",
    ]
    assert [r["class"] for r in secrets({"renamed.kt": "\n".join(lines)})] == [
        "recoverable-token"
    ]
    assert (
        secrets(
            {
                "other.kt": 'class Demo { val sharedPassword = "synthetic_local_password" }'
            }
        )[0]["class"]
        == "password"
    )
    assert [
        r["class"]
        for r in secrets(
            {"settings.yml": "token: ${TOKEN:training_fixture}\nnextToken: ${TOKEN}"}
        )
    ] == ["secret-fallback"]


def test_gradle_short_catalog_and_multiline_add():
    files = {
        "build.gradle.kts": "dependencies { implementation(libs.parser) }",
        "gradle/libs.versions.toml": '[libraries]\nparser="org.jsoup:jsoup:1.14.1"',
    }
    assert sca(files)[0]["artifact"] == "jsoup"
    files["build.gradle.kts"] = (
        'dependencies { add(\n"runtimeOnly",\n"org.jsoup:jsoup:1.14.2") }'
    )
    assert sca(files) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("path", "/absolute.kt"),
        ("path", "../X.kt"),
        ("line", False),
        ("line", 0),
        ("endLine", 18),
    ],
)
def test_invalid_submission(field, value):
    row = {
        "category": "SECRET",
        "class": "password",
        "path": "A.kt",
        "line": 2,
        "severity": "HIGH",
        "description": "sample",
        "remediation": "rotate",
        field: value,
    }
    with pytest.raises(ValueError):
        SubmissionReportExporter.export([row])
