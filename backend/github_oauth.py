"""GitHub identity flow and encrypted access to the public repository list."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
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
    normalize_email,
    open_session,
    retire_session,
    throttle,
    token_digest,
    viewer,
)
from .db import Account, Credential, RepositoryWatch, Session, cipher

router = APIRouter(prefix="/api/v1/auth/github", tags=["account"])
COOKIE = "centerai_github_flow"
PATH = "/api/v1/auth/github"
TTL = 600


def repository_token(db, account_id):
    credential = db.get(Credential, f"github:{account_id}")
    if credential is not None:
        try:
            return cipher().decrypt(credential.encrypted).decode()
        except (InvalidToken, UnicodeDecodeError):
            return None


def save_repository_token(db, account, token):
    db.merge(
        Credential(
            provider=f"github:{account.id}",
            encrypted=cipher().encrypt(token.encode()),
        )
    )


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


def start_flow(request, response, intent, *, return_to_repositories=False):
    client_id, secret, callback = configuration()
    if not all((client_id, secret, callback)):
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
        "return_to_repositories": return_to_repositories,
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
            "scope": "read:user user:email" if intent == "register" else "read:user",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return {"url": "https://github.com/login/oauth/authorize?" + params}


@router.post("/link")
def link(
    request: Request, response: Response, db: DB, return_to_repositories: bool = False
):
    account = member(db)
    if return_to_repositories and not account.github_id:
        raise HTTPException(403, "Привяжите GitHub в личном кабинете")
    return start_flow(
        request, response, "link", return_to_repositories=return_to_repositories
    )


@router.post("/login")
def login_with_github(request: Request, response: Response):
    return start_flow(request, response, "login")


@router.post("/register")
def register_with_github(request: Request, response: Response):
    return start_flow(request, response, "register")


@router.delete("/link")
def unlink(db: DB):
    account = member(db)
    if account.github_id is not None and not account.password_hash:
        raise HTTPException(409, "GitHub используется как единственный способ входа")
    db.execute(
        update(RepositoryWatch)
        .where(RepositoryWatch.account_id == account.id)
        .values(enabled=False)
    )
    credential = db.get(Credential, f"github:{account.id}")
    if credential is not None:
        db.delete(credential)
    account.github_id = account.github_login = None
    db.commit()
    return {"ok": True}


def get_identity(code, verifier, need_email=False):
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
        if not isinstance(token, str) or not token:
            raise ValueError
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        user = (
            client.get(
                "https://api.github.com/user",
                headers=headers,
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
        email = None
        if need_email:
            addresses = (
                client.get("https://api.github.com/user/emails", headers=headers)
                .raise_for_status()
                .json()
            )
            raw = next(
                (
                    row.get("email")
                    for row in addresses
                    if isinstance(row, dict)
                    and row.get("primary") is True
                    and row.get("verified") is True
                ),
                None,
            )
            if isinstance(raw, str) and len(raw) <= 254:
                try:
                    email = normalize_email(raw)
                except HTTPException:
                    pass
        return str(user_id), login, email, token


def complete_flow(db, request, response, intent, github_id, login, email, token):
    if intent in ("login", "register"):
        account = db.scalar(
            select(Account).where(Account.github_id == github_id).with_for_update()
        )
        if account is None:
            if intent == "login":
                return "unlinked"
            if email is None:
                return "email-unavailable"
            if db.scalar(select(Account.id).where(Account.email == email)) is not None:
                return "existing-email"
            account = Account(
                email=email,
                github_id=github_id,
                github_login=login,
                email_verified_at=time.time(),
            )
            db.add(account)
            db.flush()
        if account.email is None:
            return "unlinked"
        account.github_login = login
        save_repository_token(db, account, token)
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
    save_repository_token(db, account, token)
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
    intent = None
    try:
        flow = json.loads(
            cipher().decrypt(request.cookies.get(COOKIE, "").encode(), ttl=TTL)
        )
        intent = flow["intent"]
        if intent in ("login", "register"):
            destination = "/"
        if (
            code
            and state.isascii()
            and hmac.compare_digest(flow["state"], state)
            and flow["session"] == token_digest(request)
        ):
            identity = get_identity(code, flow["verifier"], intent == "register")
            with Session() as db:
                result = complete_flow(db, request, response, intent, *identity)
    except IntegrityError:
        result = "conflict"
    except (InvalidToken, httpx.HTTPError, ValueError, KeyError, TypeError):
        pass
    if result == "signed-in":
        response.headers["Location"] = "/"
    elif result == "linked" and flow.get("return_to_repositories"):
        response.headers["Location"] = "/repositories"
    else:
        mode = "&mode=register" if intent == "register" else ""
        response.headers["Location"] = f"{destination}?github={result}{mode}"
    return response
