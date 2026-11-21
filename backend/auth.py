"""Browser sessions, password verification and temporary workspace leases."""

import hashlib
import hmac
import re
import secrets
import time
from threading import BoundedSemaphore, Lock
from typing import Annotated

import regex
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .db import (
    Account,
    AuthSession,
    Credential,
    Event,
    Finding,
    NodeRun,
    Project,
    Run,
    Session,
    Version,
    Workflow,
)

COOKIE = "centerai_session"
GUEST_IDLE = 30 * 60
MEMBER_TTL = 30 * 24 * 60 * 60
router = APIRouter(prefix="/api/v1/auth", tags=["account"])
attempts = {}
attempt_lock = Lock()
password_slots = BoundedSemaphore(3)


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class Profile(BaseModel):
    nickname: str = Field(max_length=60)
    telegram_username: str = Field(max_length=33)


def normalize_email(email):
    try:
        return validate_email(
            email.strip(), check_deliverability=False, allow_smtputf8=False
        ).normalized.lower()
    except EmailNotValidError:
        raise HTTPException(422, "Введите корректный адрес электронной почты") from None


def password_strength(password):
    if len(password) < 8 or not password.strip():
        return 1
    if not regex.search(r"\p{L}", password) or not re.search(r"[0-9]", password):
        return 2
    return 4 if regex.search(r"[\p{P}\p{S}]", password) else 3


def derive(password, salt):
    if not password_slots.acquire(blocking=False):
        raise HTTPException(
            429,
            "Слишком много попыток. Попробуйте позже.",
            headers={"Retry-After": "2"},
        )
    try:
        return hashlib.scrypt(
            password.encode(), salt=salt, n=2**16, r=8, p=1, maxmem=96 * 1024**2
        )
    finally:
        password_slots.release()


def password_hash(password):
    salt = secrets.token_bytes(16)
    return f"scrypt-v1${salt.hex()}${derive(password, salt).hex()}"


def matches(password, encoded):
    if not encoded:
        derive(password, bytes(16))
        return False
    _, salt, expected = encoded.split("$")
    return hmac.compare_digest(
        derive(password, bytes.fromhex(salt)), bytes.fromhex(expected)
    )


def throttle(request, action, limit):
    now = time.monotonic()
    key = (request.client.host if request.client else "", action)
    with attempt_lock:
        for old in tuple(attempts):
            if attempts[old][0] <= now:
                del attempts[old]
        until, count = attempts.get(key, (now + 300, 0))
        if count >= limit or (key not in attempts and len(attempts) >= 4096):
            raise HTTPException(
                429,
                "Слишком много попыток. Попробуйте позже.",
                headers={"Retry-After": "300"},
            )
        attempts[key] = until, count + 1


def token_digest(request):
    token = request.cookies.get(COOKIE, "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    return hashlib.sha256(token.encode()).hexdigest()


def viewer(db, key):
    if not key:
        return None
    now = time.time()
    return db.scalar(
        select(Account)
        .join(AuthSession, AuthSession.account_id == Account.id)
        .where(
            AuthSession.digest == key,
            AuthSession.expires_at > now,
            (Account.guest_until.is_(None) | (Account.guest_until > now)),
        )
    )


def profile_out(account):
    if account is None:
        return None
    return {
        "id": account.id,
        "guest": account.email is None,
        "email": account.email,
        "nickname": account.nickname,
        "telegram_username": account.telegram_username,
        "telegram_connected": False,
    }


def account_out(db, account):
    data = profile_out(account)
    if data and not data["guest"]:
        data["telegram_connected"] = (
            db.get(Credential, f"telegram:{account.id}") is not None
        )
    return data


def session(request: Request):
    with Session() as db:
        account = viewer(db, token_digest(request))
        if account is None:
            raise HTTPException(401, "Войдите, чтобы продолжить")
        db.info["account"] = account
        yield db


DB = Annotated[Session, Depends(session)]


def member(db):
    account = db.info["account"]
    if account.email is None:
        raise HTTPException(403, "Эта функция доступна после регистрации")
    return account


def open_session(db, account, request, response):
    token = secrets.token_urlsafe(32)
    guest = account.email is None
    db.add(
        AuthSession(
            digest=hashlib.sha256(token.encode()).hexdigest(),
            account_id=account.id,
            expires_at=time.time() + (GUEST_IDLE if guest else MEMBER_TTL),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=None if guest else MEMBER_TTL,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
    )
    return account_out(db, account)


@router.get("/session")
def current(request: Request):
    with Session() as db:
        return account_out(db, viewer(db, token_digest(request)))


@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, response: Response):
    throttle(request, "register", 30)
    email = normalize_email(body.email)
    if password_strength(body.password) < 3:
        raise HTTPException(422, "Выберите более надёжный пароль")
    encoded = password_hash(body.password)
    with Session() as db:
        retire_session(db, token_digest(request))
        account = Account(email=email, password_hash=encoded)
        db.add(account)
        try:
            db.flush()
            return open_session(db, account, request, response)
        except IntegrityError:
            raise HTTPException(409, "Для этого адреса уже есть аккаунт") from None


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    throttle(request, "login", 20)
    email = normalize_email(body.email)
    with Session() as db:
        account = db.scalar(select(Account).where(Account.email == email))
        if not matches(body.password, account.password_hash if account else None):
            raise HTTPException(401, "Неверная почта или пароль")
        retire_session(db, token_digest(request))
        return open_session(db, account, request, response)


@router.post("/guest", status_code=201)
def guest(request: Request, response: Response):
    throttle(request, "guest", 60)
    with Session() as db:
        old = token_digest(request)
        existing = viewer(db, old)
        if existing is not None:
            return account_out(db, existing)
        retire_session(db, old)
        account = Account(guest_until=time.time() + GUEST_IDLE)
        db.add(account)
        db.flush()
        return open_session(db, account, request, response)


@router.post("/keepalive")
def keepalive(request: Request, db: DB):
    account = db.info["account"]
    if account.email is None:
        now = time.time()
        deadline = now + GUEST_IDLE
        renewed = db.execute(
            update(Account)
            .where(Account.id == account.id, Account.guest_until > now)
            .values(guest_until=deadline)
        )
        if not renewed.rowcount:
            raise HTTPException(401, "Гостевая сессия завершилась")
        db.execute(
            update(AuthSession)
            .where(AuthSession.digest == token_digest(request))
            .values(expires_at=deadline)
        )
        db.commit()
    return account_out(db, account)


@router.patch("/profile")
def edit_profile(body: Profile, db: DB):
    account = member(db)
    username = body.telegram_username.strip().removeprefix("@")
    if username and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", username):
        raise HTTPException(
            422, "Введите имя пользователя Telegram в формате @username"
        )
    account.nickname = body.nickname.strip()
    account.telegram_username = username
    db.commit()
    return account_out(db, account)


def retire_session(db, key):
    entry = db.get(AuthSession, key) if key else None
    if entry is None:
        return
    account_id = entry.account_id
    ended_guest = db.execute(
        update(Account)
        .where(Account.id == account_id, Account.guest_until.is_not(None))
        .values(guest_until=time.time())
    )
    db.execute(delete(AuthSession).where(AuthSession.digest == key))
    if ended_guest.rowcount:
        purge_guest(db, account_id)


@router.post("/logout")
def logout(request: Request, response: Response):
    with Session() as db:
        retire_session(db, token_digest(request))
        db.commit()
    response.delete_cookie(
        COOKIE, httponly=True, secure=request.url.scheme == "https", samesite="lax"
    )
    return {"ok": True}


def purge_guest(db, account_id):
    projects = select(Project.id).where(Project.owner_id == account_id)
    runs = select(Run.id).where(Run.project_id.in_(projects))
    # Cancelling queued rows also serializes cleanup with the worker's claim.
    db.execute(
        update(Run)
        .where(Run.id.in_(runs), Run.status == "queued")
        .values(status="cancelled", cancel_requested=True)
    )
    running = db.execute(
        update(Run)
        .where(Run.id.in_(runs), Run.status == "running")
        .values(cancel_requested=True)
    )
    if running.rowcount:
        return
    for table in (Finding, Event, NodeRun):
        db.execute(delete(table).where(table.run_id.in_(runs)))
    db.execute(delete(Run).where(Run.project_id.in_(projects)))
    workflows = select(Workflow.id).where(Workflow.project_id.in_(projects))
    db.execute(delete(Version).where(Version.workflow_id.in_(workflows)))
    db.execute(delete(Workflow).where(Workflow.project_id.in_(projects)))
    db.execute(delete(Project).where(Project.owner_id == account_id))
    db.execute(delete(AuthSession).where(AuthSession.account_id == account_id))
    db.execute(delete(Account).where(Account.id == account_id))


def cleanup_sessions(db, now):
    # Lock the lease before deleting so a simultaneous heartbeat cannot revive it.
    guests = db.scalars(
        update(Account)
        .where(Account.guest_until <= now)
        .values(guest_until=Account.guest_until)
        .returning(Account.id)
    )
    for account_id in guests.all():
        purge_guest(db, account_id)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
