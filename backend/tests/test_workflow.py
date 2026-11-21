import io
import stat
import time
import zipfile
from unittest.mock import Mock
import pytest

from backend.db import Credential, Session, Workflow
from backend.graph import default_graph, validate
from backend.sources import fetch_repository, unpack
from backend.worker import tick
from .conftest import zip_bytes

API = "/api/v1"


def create_flow(client, project, graph=None):
    response = client.post(
        API + "/workflows",
        json={
            "name": "Pipeline",
            "project_id": project["id"],
            "graph": graph or default_graph(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pipeline(client, project):
    flow = create_flow(client, project)
    url = API + "/workflows/" + flow["id"]
    assert client.post(url + "/validate").status_code == 200
    assert client.put(url, json={**flow, "name": "Second"}).status_code == 200
    assert client.put(url, json=flow).status_code == 409
    assert len(client.get(url + "/versions").json()) == 2
    run = client.post(url + "/runs").json()
    tick()
    detail = client.get(API + "/runs/" + run["id"]).json()
    assert detail["status"] == "success" and detail["count"] == 2
    assert all(n["status"] == "success" for n in detail["nodes"])
    stages = [event for event in detail["events"] if event["stage"] is not None]
    assert [event["node_id"] for event in stages] == detail["stage_order"][2:5]
    assert [event["stage"]["count"] for event in stages] == [1, 1, 0]
    assert stages[0]["stage"]["preview"][0].keys() == {
        "id",
        "title",
        "severity",
        "path",
        "line",
    }
    result = client.get(API + "/runs/" + run["id"] + "/report").json()["findings"]
    assert {r["category"] for r in result} == {"SECRET", "SCA"}
    assert all("id" not in row and "evidence" not in row for row in result)
    replay = client.get(
        API + "/runs/" + run["id"] + "/events",
        headers={"Last-Event-ID": str(stages[0]["id"])},
    ).text
    assert "event: done" in replay and '"stage": {"count": 1' in replay
    assert f"id: {stages[0]['id']}\n" not in replay
    assert len(client.get(API + "/results?q=jsoup").json()) == 1
    assert (
        client.get(API + "/runs/" + run["id"] + "/report?format=txt").status_code == 200
    )
    assert (
        client.patch(
            API + "/projects/" + project["id"], json={"name": "Renamed"}
        ).status_code
        == 200
    )
    assert client.delete(API + "/projects/" + project["id"]).status_code == 200
    assert client.get(API + "/workflows").json() == []
    assert client.get(API + "/runs").json() == []
    assert client.get(API + "/runs/" + run["id"] + "/report").status_code == 404


def test_branches_schedule_and_filters(client, project):
    graph = default_graph()
    graph["nodes"][0].update(
        type="schedule_trigger",
        config={"enabled": True, "cron": "* * * * *", "timezone": "Europe/Moscow"},
    )

    def node(key, kind, **config):
        graph["nodes"].append({"id": key, "type": kind, "config": config})

    def edge(a, b, branch=""):
        graph["edges"].append({"source": a, "target": b, "branch": branch})

    graph["edges"] = [e for e in graph["edges"] if e["target"] != "report_generator"]
    node("level", "severity_filter", levels=["HIGH"])
    node("choose", "if_else", operator=">", count=0)
    node("path", "regex_filter", pattern=r"\.kt$")
    node("otherwise", "report_generator")
    for s in ["secrets_scanner", "sast_scanner", "sca_scanner"]:
        edge(s, "level")
    edge("level", "choose")
    edge("choose", "path", "true")
    edge("choose", "otherwise", "false")
    edge("path", "report_generator")
    flow = create_flow(client, project, graph)
    with Session() as db:
        db.get(Workflow, flow["id"]).next_due = time.time() - 1
        db.commit()
    tick()
    tick()
    runs = client.get(API + "/runs").json()
    assert len(runs) == 1 and runs[0]["trigger"] == "schedule" and runs[0]["count"] == 1
    nodes = client.get(API + "/runs/" + runs[0]["id"]).json()["nodes"]
    assert next(n for n in nodes if n["node_id"] == "otherwise")["status"] == "skipped"


@pytest.mark.parametrize("bad", ["cycle", "missing", "type", "start"])
def test_invalid_graph(bad):
    graph = default_graph()
    if bad == "cycle":
        graph["edges"] += [
            {"source": "sast_scanner", "target": "sca_scanner"},
            {"source": "sca_scanner", "target": "sast_scanner"},
        ]
    elif bad == "missing":
        graph["edges"][0]["target"] = "unknown"
    elif bad == "type":
        graph["edges"][0]["target"] = "report_generator"
    else:
        graph["nodes"].pop(0)
    with pytest.raises(ValueError):
        validate(graph)


def test_safe_sources():
    with pytest.raises(ValueError):
        unpack(zip_bytes({"../unsuitable.kt": "", "build.gradle.kts": ""}))
    with pytest.raises(ValueError):
        fetch_repository("https://127.0.0.1/private")
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as archive:
        link = zipfile.ZipInfo("link.kt")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "target")
    with pytest.raises(ValueError):
        unpack(blob.getvalue())


def test_notification_error_and_delivery(client, project, monkeypatch):
    graph = default_graph()
    graph["nodes"].append({"id": "send", "type": "notification", "config": {}})
    graph["edges"].append(
        {"source": "report_generator", "target": "send", "branch": ""}
    )
    flow = create_flow(client, project, graph)
    url = API + "/workflows/" + flow["id"] + "/runs"
    run = client.post(url).json()
    tick()
    detail = client.get(API + "/runs/" + run["id"]).json()
    assert detail["status"] == "failed" and detail["count"] == 2
    token = "123456:" + "x" * 32
    res = client.put(
        API + "/integrations/telegram", json={"token": token, "chat": "12345"}
    )
    assert res.status_code == 200 and token not in res.text
    owner = client.get(API + "/auth/session").json()["id"]
    with Session() as db:
        assert token.encode() not in db.get(Credential, f"telegram:{owner}").encrypted
    post = Mock(return_value=Mock(is_success=True, json=lambda: {"ok": True}))
    monkeypatch.setattr("backend.notifications.httpx.post", post)
    run = client.post(url).json()
    tick()
    assert client.get(API + "/runs/" + run["id"]).json()["status"] == "success"
    assert post.call_args.kwargs["json"]["text"].endswith(run["id"])
    assert token not in str(client.get(API + "/runs/" + run["id"]).json())
