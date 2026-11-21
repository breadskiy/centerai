"""GitHub identity flow. Provider tokens exist only during the callback."""

import base64
import hashlib
import hmac
import json
import os
import secrets
from urllib.parse import urlencode

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .auth import (
    DB,
    member,
    open_session,
    retire_session,
    throttle,
    token_digest,
    viewer,
)
from .db import Account, Session, cipher

router = APIRouter(prefix="/api/v1/auth/github", tags=["account"])
COOKIE = "centerai_github_flow"
PATH = "/api/v1/auth/github"
TTL = 600


def configuration():
    return (
        os.getenv("GITHUB_CLIENT_ID"),
        os.getenv("GITHUB_CLIENT_SECRET"),
        os.getenv(
            "GITHUB_OAUTH_CALLBACK_URL", "http://127.0.0.1:8000" + PATH + "/callback"
        ),
    )


@router.get("/status")
def status():
    return {"available": all(configuration())}


def start_flow(request, response, intent):
    client_id, secret, callback = configuration()
    if not client_id or not secret:
        raise HTTPException(503, "Подключение GitHub пока не настроено")
    throttle(request, "github", 30)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    payload = {
        "state": state,
        "verifier": verifier,
        "session": token_digest(request),
        "intent": intent,
    }
    response.set_cookie(
        COOKIE,
        cipher().encrypt(json.dumps(payload).encode()).decode(),
        path=PATH,
        max_age=TTL,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": callback,
            "scope": "read:user",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return {"url": "https://github.com/login/oauth/authorize?" + params}


@router.post("/link")
def link(request: Request, response: Response, db: DB):
    member(db)
    return start_flow(request, response, "link")


@router.post("/login")
def login_with_github(request: Request, response: Response):
    return start_flow(request, response, "login")


@router.delete("/link")
def unlink(db: DB):
    account = member(db)
    account.github_id = account.github_login = None
    db.commit()
    return {"ok": True}


def get_identity(code, verifier):
    client_id, secret, callback = configuration()
    if not client_id or not secret:
        raise ValueError
    with httpx.Client(timeout=10, follow_redirects=False) as client:
        token = (
            client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": client_id,
                    "client_secret": secret,
                    "redirect_uri": callback,
                    "code": code,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
            )
            .raise_for_status()
            .json()["access_token"]
        )
        user = (
            client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
            .raise_for_status()
            .json()
        )
        user_id, login = user["id"], user["login"]
        if (
            type(user_id) is not int
            or not 0 < user_id < 10**32
            or not isinstance(login, str)
            or not 0 < len(login) <= 100
        ):
            raise ValueError
        return str(user_id), login


def complete_flow(db, request, response, intent, github_id, login):
    if intent == "login":
        account = db.scalar(
            select(Account).where(Account.github_id == github_id).with_for_update()
        )
        if account is None or account.email is None:
            return "unlinked"
        account.github_login = login
        retire_session(db, token_digest(request))
        open_session(db, account, request, response)
        return "signed-in"
    account = viewer(db, token_digest(request))
    if intent != "link" or account is None or account.email is None:
        return "failed"
    updated = db.execute(
        update(Account)
        .where(
            Account.id == account.id,
            Account.github_id.is_(None) | (Account.github_id == github_id),
        )
        .values(github_id=github_id, github_login=login)
    )
    if not updated.rowcount:
        return "conflict"
    db.commit()
    return "linked"


@router.get("/callback")
def oauth_callback(request: Request, code: str = "", state: str = ""):
    response = RedirectResponse(
        "/account", status_code=303, headers={"Referrer-Policy": "no-referrer"}
    )
    response.delete_cookie(
        COOKIE,
        path=PATH,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    destination, result = "/account", "failed"
    try:
        flow = json.loads(
            cipher().decrypt(request.cookies.get(COOKIE, "").encode(), ttl=TTL)
        )
        intent = flow["intent"]
        if intent == "login":
            destination = "/"
        if (
            code
            and state.isascii()
            and hmac.compare_digest(flow["state"], state)
            and flow["session"] == token_digest(request)
        ):
            github_id, login = get_identity(code, flow["verifier"])
            with Session() as db:
                result = complete_flow(db, request, response, intent, github_id, login)
    except IntegrityError:
        result = "conflict"
    except (InvalidToken, httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    response.headers["Location"] = (
        "/" if result == "signed-in" else f"{destination}?github={result}"
    )
    return response
