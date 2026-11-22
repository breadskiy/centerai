from datetime import datetime

import httpx
import pytest
from sqlalchemy import select

from backend import api, repository_watches
from backend.db import Account, Credential, RepositoryWatch, Run, Session, cipher
from backend.graph import default_graph
from backend.worker import execute
from .test_workflow import create_flow


PATH = "/api/v1/github-repositories"


def test_watches_scan_each_new_head_and_stop_when_disabled(client, monkeypatch):
    assert client.get(PATH).status_code == 403
    with Session() as db:
        account = db.scalar(select(Account))
        account.github_id, account.github_login = "42", "owner"
        db.commit()
        key = (account.id, "123")

    repo = {
        "id": 123,
        "owner": {"id": 42},
        "full_name": "owner/demo",
        "default_branch": "main",
        "archived": False,
        "private": False,
    }
    head = None
    committed_at = "2026-11-21T12:00:00Z"

    def github(path, **params):
        if path == "/users/owner/repos":
            assert params["type"] == "owner"
            return [repo]
        if path == "/repositories/123":
            return repo
        if path == "/repositories/999":
            return {**repo, "owner": {"id": 43}}
        assert path == f"/repos/{repo['full_name']}/commits"
        assert params == {"sha": repo["default_branch"], "per_page": 1}
        return (
            [{"sha": head, "commit": {"committer": {"date": committed_at}}}]
            if head
            else []
        )

    snapshots = []

    def fetch(url, *, public, commit):
        assert url == f"https://github.com/{repo['full_name']}" and public
        snapshots.append(commit)
        return {
            "build.gradle.kts": "",
            "src/App.kt": 'val labPassword = "synthetic_fixture_21"'
            if len(snapshots) == 2
            else "",
        }

    def tick():
        with Session() as db:
            db.get(RepositoryWatch, key).due = 0
            db.commit()
        repository_watches.inspect_repository(key, api.prepare_repository_scan)
        return client.get(PATH + "/watches").json()["123"]

    monkeypatch.setattr(repository_watches, "github", github)
    monkeypatch.setattr(api, "fetch_repository", fetch)
    assert client.get(PATH).json()["items"][0]["id"] == "123"
    assert client.put(PATH + "/999/watch", json={"enabled": True}).status_code == 404
    assert client.get(PATH + "/999/scenario").status_code == 404
    scenario_path = PATH + "/123/scenario"
    starter = client.get(scenario_path).json()
    assert starter["repository"] == "owner/demo" and starter["revision"] == 0
    assert client.get(PATH + "/watches").json() == {}
    assert (
        client.put(
            scenario_path, json={**starter, "graph": {"nodes": [], "edges": []}}
        ).status_code
        == 422
    )
    assert client.put(scenario_path, json=starter).json()["revision"] == 1
    assert client.get(PATH + "/watches").json()["123"]["enabled"] is False
    assert client.put(PATH + "/123/watch", json={"enabled": True}).is_success
    empty = tick()
    assert empty["error"] == repository_watches.EMPTY_REPOSITORY
    assert empty["enabled"] and empty["run_id"] is None
    assert snapshots == []

    head = "a" * 40
    first = tick()
    assert first["sha"] == head and first["status"] == "queued"
    assert first["head_sha"] == head
    assert (
        first["head_committed_at"] == datetime.fromisoformat(committed_at).timestamp()
    )
    assert first["error"] is None
    execute(first["run_id"])
    assert tick()["run_id"] == first["run_id"]
    assert snapshots == ["a" * 40]

    head = "b" * 40
    committed_at = "2026-11-22T10:30:00Z"
    second = tick()
    assert second["sha"] == head and second["run_id"] != first["run_id"]
    execute(second["run_id"])
    completed = tick()
    assert completed["count"] == 1
    assert (
        completed["head_committed_at"]
        == datetime.fromisoformat(committed_at).timestamp()
    )
    assert completed["delta"] == {"new": 1, "fixed": 0}
    assert snapshots == ["a" * 40, "b" * 40]

    repo.update(full_name="owner/renamed", default_branch="develop")
    renamed = tick()
    assert renamed["branch"] == "develop"
    assert renamed["run_id"] == second["run_id"]

    head = "c" * 40
    committed_at = "2026-11-22T11:00:00Z"

    def unavailable(*args, **kwargs):
        raise ValueError("Архив недоступен")

    monkeypatch.setattr(api, "fetch_repository", unavailable)
    failed = tick()
    assert failed["head_sha"] == head and failed["sha"] == "b" * 40
    assert (
        failed["head_committed_at"] == datetime.fromisoformat(committed_at).timestamp()
    )
    assert failed["error"] == "Архив недоступен"
    repo["archived"] = True
    assert tick()["error"] == repository_watches.REPOSITORY_ACCESS
    assert client.put(PATH + "/123/watch", json={"enabled": False}).is_success
    head = "d" * 40
    assert tick()["run_id"] == second["run_id"]


@pytest.mark.parametrize("status_code", [403, 429])
def test_github_rate_limit_with_no_retry_after(monkeypatch, status_code):
    monkeypatch.setattr(
        repository_watches.httpx,
        "get",
        lambda *a, **kw: httpx.Response(
            status_code,
            headers={"x-ratelimit-remaining": "1", "x-ratelimit-reset": "4000000000"},
            json={"message": "You have exceeded a secondary rate limit."},
        ),
    )
    with pytest.raises(repository_watches.GitHubRateLimit) as caught:
        repository_watches.github("/repositories/123")
    assert caught.value.retry_after == repository_watches.INTERVAL


def test_github_empty_repository_response(monkeypatch):
    def request(url, **kwargs):
        return httpx.Response(409, json={"message": "Git Repository is empty."})

    monkeypatch.setattr(repository_watches.httpx, "get", request)
    with pytest.raises(
        repository_watches.GitHubUnavailable, match=repository_watches.EMPTY_REPOSITORY
    ):
        repository_watches.github("/repos/owner/demo/commits", sha="main", per_page=1)


def test_collaborator_repositories_use_account_token_and_allow_watching(
    client, monkeypatch
):
    with Session() as db:
        account = db.scalar(select(Account))
        account.github_id, account.github_login = "42", "owner"
        db.add(
            Credential(
                provider=f"github:{account.id}",
                encrypted=cipher().encrypt(b"fixture-token"),
            )
        )
        db.commit()
    shared = {
        "id": 12,
        "owner": {"id": 17},
        "full_name": "friend/shared",
        "default_branch": "main",
        "archived": False,
        "private": False,
    }
    private = {**shared, "id": 13, "private": True}
    stranger = {**shared, "id": 14, "full_name": "friend/unshared"}
    own = {**shared, "id": 15, "owner": {"id": 42}, "full_name": "owner/demo"}
    expired = False

    def github(path, *, token=None, **params):
        if path == "/user/repos":
            assert token == "fixture-token"
            assert params["visibility"] == "public"
            assert params["affiliation"] == "owner,collaborator"
            if expired:
                raise repository_watches.GitHubLoginExpired("expired")
            return [shared, private, own] if params["page"] == 2 else []
        if path == "/users/owner/repos":
            assert token is None
            return [own]
        assert token is None
        return {
            "/repositories/12": shared,
            "/repositories/13": private,
            "/repositories/14": stranger,
        }[path]

    monkeypatch.setattr(repository_watches, "github", github)
    listing = client.get(PATH + "?page=2").json()
    assert [(repo["id"], repo["owner"]) for repo in listing["items"]] == [
        ("12", False),
        ("15", True),
    ]
    assert listing["needs_github_login"] is False
    for repo_id, status in [(12, 200), (13, 404), (14, 404)]:
        assert (
            client.put(
                f"{PATH}/{repo_id}/watch", json={"enabled": True, "page": 2}
            ).status_code
            == status
        )
    expired = True
    assert client.get(PATH).json()["needs_github_login"] is True


def test_repo_uses_saved_profile_and_rechecks_head_when_profile_changes(
    client, project, monkeypatch
):
    graph = default_graph()
    graph["nodes"][0].update(
        type="schedule_trigger",
        config={"cron": "0 9 * * *", "timezone": "Europe/Moscow", "enabled": True},
    )
    flow = create_flow(client, project, graph)
    flow_path = "/api/v1/workflows/" + flow["id"]
    template = flow["id"] + ":1"
    watch_path = PATH + "/321/watch"
    sha = "a" * 40
    with Session() as db:
        account = db.scalar(select(Account))
        account.github_id, account.github_login = "42", "owner"
        db.commit()
        key = (account.id, "321")

    def github(path, **params):
        if path == "/repositories/321":
            return {
                "id": 321,
                "owner": {"id": 42},
                "full_name": "owner/demo",
                "default_branch": "main",
                "archived": False,
                "private": False,
            }
        assert path == "/repos/owner/demo/commits"
        return [{"sha": sha}]

    monkeypatch.setattr(repository_watches, "github", github)
    monkeypatch.setattr(
        api, "fetch_repository", lambda *args, **kwargs: {"build.gradle.kts": ""}
    )

    def settings(**body):
        return client.put(watch_path, json=body)

    def poll():
        with Session() as db:
            db.get(RepositoryWatch, key).due = 0
            db.commit()
        repository_watches.inspect_repository(key, api.prepare_repository_scan)
        return client.get(PATH + "/watches").json()["321"]

    assert settings(enabled=False, profile=template).status_code == 404
    assert settings(enabled=False, profile="secrets").json() == {
        "enabled": False,
        "profile": "secrets",
    }
    assert poll()["run_id"] is None
    assert settings(enabled=True).json()["profile"] == "secrets"
    first = poll()
    with Session() as db:
        types = {node["type"] for node in db.get(Run, first["run_id"]).graph["nodes"]}
        assert "secrets_scanner" in types
        assert types.isdisjoint({"sca_scanner", "sast_scanner"})
    execute(first["run_id"])
    assert poll()["run_id"] == first["run_id"]

    assert client.post(flow_path + "/versions/1/publish").is_success
    assert client.put(flow_path, json={**flow, "name": "Version 2"}).is_success
    assert settings(enabled=True, profile=template).json()["profile"] == template
    second = poll()
    assert second["sha"] == sha and second["run_id"] != first["run_id"]
    assert second["scan_profile"] == template
    with Session() as db:
        run = db.get(Run, second["run_id"])
        assert run.workflow_name.endswith("Pipeline")
        assert run.graph["nodes"][0]["config"]["enabled"] is False
    execute(second["run_id"])
    assert poll()["run_id"] == second["run_id"]

    scenario_path = PATH + "/321/scenario"
    scenario = client.get(scenario_path).json()
    assert scenario["name"] == "Pipeline"
    revision = scenario["revision"] + 1
    graph = scenario["graph"]
    omitted = {"sca_scanner", "sast_scanner"}
    graph["nodes"] = [node for node in graph["nodes"] if node["id"] not in omitted]
    graph["edges"] = [
        edge
        for edge in graph["edges"]
        if edge["source"] not in omitted and edge["target"] not in omitted
    ]
    body = {**scenario, "name": "Custom repository graph", "graph": graph}
    assert client.post(scenario_path + "/validate", json=graph).is_success
    assert client.put(scenario_path, json=body).json()["revision"] == revision
    assert client.put(scenario_path, json=body).status_code == 409
    edited = poll()
    assert (
        edited["run_id"] != second["run_id"]
        and edited["scan_scenario_revision"] == revision
    )
    with Session() as db:
        run = db.get(Run, edited["run_id"])
        assert run.workflow_name.endswith("Custom repository graph")
        assert run.graph == graph
    execute(edited["run_id"])
    assert poll()["run_id"] == edited["run_id"]
