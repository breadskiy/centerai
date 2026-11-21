from urllib.parse import parse_qs, urlparse

import httpx

from backend import github_oauth

PATH = "/api/v1/auth/github"


def state(client, intent="link"):
    response = client.post(PATH + "/" + intent)
    assert response.status_code == 200, response.text
    query = parse_qs(urlparse(response.json()["url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["read:user user:email" if intent == "register" else "read:user"]
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
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("42", "example-user", None))
    assert callback(client, state(client) + "wrong") == "/account?github=failed"
    assert client.get("/api/v1/auth/session").json()["github_login"] is None
    assert callback(client, state(client)) == "/account?github=linked"
    assert client.get("/api/v1/auth/session").json()["github_login"] == "example-user"
    assert client.delete(PATH + "/link").status_code == 200
    assert client.get("/api/v1/auth/session").json()["github_login"] is None


def test_github_sign_in_restores_only_linked_account(client, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("42", "original", None))
    owner = client.patch(
        "/api/v1/auth/profile", json={"nickname": "Saved", "telegram_username": ""}
    ).json()
    assert callback(client, state(client)) == "/account?github=linked"
    assert client.post("/api/v1/auth/logout").status_code == 200
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("43", "original", None))
    assert callback(client, state(client, "login")) == "/?github=unlinked"
    assert client.get("/api/v1/auth/session").json() is None
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("42", "renamed", None))
    assert callback(client, state(client, "login")) == "/"
    restored = client.get("/api/v1/auth/session").json()
    assert restored["id"] == owner["id"]
    assert restored["nickname"] == "Saved"
    assert restored["github_login"] == "renamed"


def test_signup_with_verified_github_email(anonymous, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(
        github_oauth, "get_identity",
        lambda _, __, need_email: ("89", "new-owner", "oauth@example.com" if need_email else None),
    )
    assert callback(anonymous, state(anonymous, "register")) == "/"
    user = anonymous.get("/api/v1/auth/session").json()
    assert user["email"] == "oauth@example.com"
    assert user["github_login"] == "new-owner"
    assert not user["github_can_unlink"]
    assert anonymous.delete(PATH + "/link").status_code == 409
    assert anonymous.post("/api/v1/auth/logout").is_success
    assert callback(anonymous, state(anonymous, "login")) == "/"
    assert anonymous.get("/api/v1/auth/session").json()["id"] == user["id"]


def test_signup_rejects_missing_email_or_existing_password_account(client, monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    assert client.post("/api/v1/auth/logout").is_success
    monkeypatch.setattr(github_oauth, "get_identity", lambda *_: ("400", "other", None))
    assert callback(client, state(client, "register")) == "/?github=email-unavailable&mode=register"
    assert client.get("/api/v1/auth/session").json() is None
    monkeypatch.setattr(
        github_oauth, "get_identity", lambda *_: ("400", "other", "developer@example.com")
    )
    assert callback(client, state(client, "register")) == "/?github=existing-email&mode=register"
    assert client.get("/api/v1/auth/session").json() is None


def test_signup_reads_only_verified_primary_email(monkeypatch):
    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-secret")
    original_client = httpx.Client
    paths = []

    def provider(request):
        paths.append(request.url.path)
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "fixture-token"})
        assert request.headers["authorization"] == "Bearer fixture-token"
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 42, "login": "profile"})
        assert request.url.path == "/user/emails"
        return httpx.Response(200, json=[
            {"primary": True, "verified": False, "email": "unverified@example.com"},
            {"primary": False, "verified": True, "email": "secondary@example.com"},
            {"primary": True, "verified": True, "email": "Primary@example.com"},
        ])

    monkeypatch.setattr(
        github_oauth.httpx, "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs),
    )
    assert github_oauth.get_identity("code", "verifier", True) == (
        "42", "profile", "primary@example.com",
    )
    assert paths == ["/login/oauth/access_token", "/user", "/user/emails"]
    paths.clear()
    assert github_oauth.get_identity("code", "verifier") == ("42", "profile", None)
    assert paths == ["/login/oauth/access_token", "/user"]
