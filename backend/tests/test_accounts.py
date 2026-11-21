from threading import Event as ThreadEvent
from threading import Thread

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from backend.analyzers import SCANNERS
from backend.api import app
from backend.auth import COOKIE
from backend.db import (
    Account,
    AuthSession,
    Event,
    Finding,
    NodeRun,
    Project,
    Run,
    Session,
    Version,
    Workflow,
)
from backend.worker import execute, tick

from .conftest import zip_bytes

API = "/api/v1"
CREDS = {"email": "owner@example.com", "password": "Quartz43"}


def test_registration_password_and_profile(anonymous):
    assert anonymous.get(API + "/dashboard").status_code == 401
    assert (
        anonymous.post(
            API + "/auth/register", json={**CREDS, "email": "bad"}
        ).status_code
        == 422
    )
    assert (
        anonymous.post(
            API + "/auth/register", json={**CREDS, "password": "abcdefg"}
        ).status_code
        == 422
    )
    created = anonymous.post(API + "/auth/register", json=CREDS)
    assert created.status_code == 201
    assert "httponly" in created.headers["set-cookie"].lower()
    assert created.headers["cache-control"] == "no-store"
    session_cookie = anonymous.cookies[COOKIE]
    with Session() as db:
        account = db.get(Account, created.json()["id"])
        assert account.password_hash.startswith("scrypt-v1$")
        assert CREDS["password"] not in account.password_hash
        assert db.scalar(select(AuthSession.digest)) != session_cookie
    assert (
        anonymous.patch(
            API + "/auth/profile",
            json={"nickname": "Quartz", "telegram_username": "bad!"},
        ).status_code
        == 422
    )
    profile = anonymous.patch(
        API + "/auth/profile",
        json={"nickname": "Quartz", "telegram_username": "@quartz_owner"},
    ).json()
    assert profile["nickname"] == "Quartz"
    assert profile["telegram_username"] == "quartz_owner"
    assert anonymous.post(API + "/auth/logout").status_code == 200
    assert (
        anonymous.get(
            API + "/dashboard", headers={"Cookie": f"{COOKIE}={session_cookie}"}
        ).status_code
        == 401
    )
    assert (
        anonymous.post(
            API + "/auth/login", json={**CREDS, "password": "wrong"}
        ).status_code
        == 401
    )
    assert (
        anonymous.post(
            API + "/auth/login", json={**CREDS, "email": CREDS["email"].upper()}
        ).json()
        == profile
    )
    assert anonymous.post(API + "/auth/register", json=CREDS).status_code == 409


def queue_scan(client):
    response = client.post(
        API + "/quick-scan",
        data={"profile": "sca"},
        files={
            "archive": (
                "sample.zip",
                zip_bytes(
                    {
                        "build.gradle.kts": 'dependencies { implementation("org.jsoup:jsoup:1.14.1") }',
                    }
                ),
            )
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_workspace_isolation_including_reports_and_templates(client):
    run = queue_scan(client)
    tick()
    project, workflow, run_id = (
        run[key] for key in ("project_id", "workflow_id", "id")
    )
    assert (
        client.post(API + f"/workflows/{workflow}/versions/1/publish").status_code
        == 200
    )
    assert (
        client.put(
            API + "/integrations/telegram",
            json={"token": "123456:" + "x" * 32, "chat": "12345"},
        ).status_code
        == 200
    )
    assert client.get(API + f"/runs/{run_id}/report").status_code == 200
    assert client.get(API + "/findings").json()
    with TestClient(app) as other:
        assert other.post(API + "/auth/register", json=CREDS).status_code == 201
        for collection in (
            "projects",
            "workflows",
            "runs",
            "findings",
            "findings/sessions",
            "templates",
        ):
            assert other.get(f"{API}/{collection}").json() == []
        assert other.get(API + "/dashboard").json()["findings"] == 0
        assert not other.get(API + "/integrations").json()["telegram"]
        for path in (
            f"/projects/{project}",
            f"/workflows/{workflow}",
            f"/workflows/{workflow}/versions",
            f"/runs/{run_id}",
            f"/runs/{run_id}/events",
            f"/runs/{run_id}/report",
            f"/runs/{run_id}/nodes/sca_scanner",
            f"/findings/sessions/{project}",
        ):
            assert other.get(API + path).status_code == 404, path
        assert other.post(API + f"/workflows/{workflow}/runs").status_code == 404
        assert other.post(API + f"/runs/{run_id}/cancel").status_code == 404
    assert client.post(API + "/auth/logout").status_code == 200
    assert (
        client.post(
            API + "/auth/login",
            json={"email": "developer@example.com", "password": "Tangerine-River42!"},
        ).status_code
        == 200
    )
    assert client.get(API + f"/runs/{run_id}/report").status_code == 200


def test_guest_logout_and_expiration_delete_workspace(anonymous):
    for ending in ("logout", "expiration"):
        guest = anonymous.post(API + "/auth/guest")
        assert guest.status_code == 201 and guest.json()["guest"]
        assert "max-age" not in guest.headers["set-cookie"].lower()
        guest_id = guest.json()["id"]
        assert (
            anonymous.patch(
                API + "/auth/profile",
                json={"nickname": "Guest", "telegram_username": ""},
            ).status_code
            == 403
        )
        run = queue_scan(anonymous)
        tick()
        assert anonymous.get(API + f"/runs/{run['id']}/report").status_code == 200
        assert anonymous.post(API + "/auth/keepalive").status_code == 200
        if ending == "logout":
            assert anonymous.post(API + "/auth/logout").status_code == 200
        else:
            with Session.begin() as db:
                db.execute(
                    update(Account).where(Account.id == guest_id).values(guest_until=0)
                )
            assert anonymous.get(API + "/auth/session").json() is None
            tick()
        assert anonymous.get(API + "/dashboard").status_code == 401
        with Session() as db:
            for table in (
                Account,
                AuthSession,
                Project,
                Workflow,
                Version,
                Run,
                Finding,
                Event,
                NodeRun,
            ):
                assert db.scalar(select(table)) is None, table


def test_guest_logout_while_worker_is_running(anonymous, monkeypatch):
    assert anonymous.post(API + "/auth/guest").status_code == 201
    run = queue_scan(anonymous)
    entered, release = ThreadEvent(), ThreadEvent()
    scanner = SCANNERS["sca_scanner"]

    def paused(files):
        entered.set()
        assert release.wait(5)
        return scanner(files)

    monkeypatch.setitem(SCANNERS, "sca_scanner", paused)
    worker = Thread(target=execute, args=(run["id"],))
    worker.start()
    try:
        assert entered.wait(5)
        assert anonymous.post(API + "/auth/logout").status_code == 200
        with Session() as db:
            assert db.get(Run, run["id"]).cancel_requested
        assert anonymous.get(API + "/runs/" + run["id"]).status_code == 401
    finally:
        release.set()
        worker.join(8)
    assert not worker.is_alive()
    tick()
    with Session() as db:
        assert db.get(Run, run["id"]) is None
        assert db.get(Project, run["project_id"]) is None
