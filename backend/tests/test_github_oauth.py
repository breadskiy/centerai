from urllib.parse import parse_qs, urlparse

from backend import github_oauth

PATH = "/api/v1/auth/github"


def state(client, intent="link"):
    response = client.post(PATH + "/" + intent)
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["read:user"]
    return query["state"][0]


def callback(client, state):
    return client.get(
        PATH + "/callback",
        params={"code": "test-code", "state": state},
        follow_redirects=False,
    ).headers["location"]


def test_link_and_unlink_github(client, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("42", "example-user"))
    assert callback(client, state(client) + "wrong") == "/account?github=failed"
    assert client.get("/api/v1/auth/session").json()["github_login"] is None
    assert callback(client, state(client)) == "/account?github=linked"
    assert client.get("/api/v1/auth/session").json()["github_login"] == "example-user"
    assert client.delete(PATH + "/link").status_code == 200
    assert client.get("/api/v1/auth/session").json()["github_login"] is None


def test_github_sign_in_restores_only_linked_account(client, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("42", "original"))
    owner = client.patch(
        "/api/v1/auth/profile", json={"nickname": "Saved", "telegram_username": ""}
    ).json()
    assert callback(client, state(client)) == "/account?github=linked"
    assert client.post("/api/v1/auth/logout").status_code == 200
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("43", "original"))
    assert callback(client, state(client, "login")) == "/?github=unlinked"
    assert client.get("/api/v1/auth/session").json() is None
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("42", "renamed"))
    assert callback(client, state(client, "login")) == "/"
    restored = client.get("/api/v1/auth/session").json()
    assert restored["id"] == owner["id"]
    assert restored["nickname"] == "Saved"
    assert restored["github_login"] == "renamed"
