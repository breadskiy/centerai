"""Discover and watch public repositories owned or co-managed by the user."""

import logging
import re
import time
from collections import Counter
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .auth import DB, member
from .db import Account, Finding, RepositoryWatch, Run, Session
from .github_oauth import repository_token
from .graph import Graph
from .scan_profiles import ProfileUnavailable, commit_triggered_graph, resolve_scan_profile

router = APIRouter(prefix="/api/v1/github-repositories")
logger = logging.getLogger(__name__)
INTERVAL = 60
EMPTY_REPOSITORY = "Репозиторий пока пуст. Добавьте первый коммит, чтобы запустить проверку."
REPOSITORY_ACCESS = "Выберите публичный репозиторий, где вы владелец или соавтор"


class GitHubUnavailable(Exception):
    def __init__(self, message, retry_after=INTERVAL):
        super().__init__(message)
        self.retry_after = retry_after


class GitHubLoginExpired(GitHubUnavailable):
    pass


def github(path, *, token=None, **params):
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(
            "https://api.github.com" + path,
            params=params,
            headers=headers,
            timeout=8,
            follow_redirects=False,
        )
        if token and response.status_code == 401:
            raise GitHubLoginExpired("Войдите через GitHub заново, чтобы обновить доступ")
        if response.status_code in (403, 429) and (
            response.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in response.headers
        ):
            delay = INTERVAL
            try:
                delay = max(delay, int(response.headers.get("retry-after", "0")))
                delay = max(delay, int(response.headers.get("x-ratelimit-reset", "0")) - time.time() + 1)
            except ValueError:
                pass
            raise GitHubUnavailable("Достигнут лимит GitHub. Проверка возобновится автоматически.", delay)
        if response.status_code == 409 and path.endswith("/commits"):
            raise GitHubUnavailable(EMPTY_REPOSITORY)
        if response.status_code in (404, 409):
            raise GitHubUnavailable("Репозиторий или ветка недоступны на GitHub")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GitHubUnavailable("Не удалось получить данные GitHub") from exc


def linked(db):
    account = member(db)
    if not account.github_id or not account.github_login:
        raise HTTPException(403, "Привяжите GitHub в личном кабинете")
    return account


def repository_out(repo, account):
    return {
        "id": str(repo["id"]),
        "name": repo["full_name"],
        "branch": repo["default_branch"],
        "archived": repo["archived"],
        "owner": str(repo["owner"]["id"]) == account.github_id,
    }


def accessible_repositories(token, page):
    return github(
        "/user/repos",
        token=token,
        visibility="public",
        affiliation="owner,collaborator",
        sort="full_name",
        direction="asc",
        per_page=30,
        page=page,
    )


@router.get("")
def repositories(db: DB, page: int = Query(1, ge=1, le=1000)):
    account = linked(db)
    try:
        token = repository_token(db, account.id)
        if token:
            try:
                rows = accessible_repositories(token, page)
            except GitHubLoginExpired:
                token = None
        if not token:
            rows = github(
                "/users/" + quote(account.github_login, safe="") + "/repos",
                type="owner", sort="full_name", direction="asc", per_page=30, page=page,
            )
    except GitHubUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return {
        "items": [repository_out(repo, account) for repo in rows if not repo["private"]],
        "has_more": len(rows) == 30,
        "needs_github_login": not token,
    }


def finding_counts(db, run_id):
    return Counter(
        (row.get("rule_id"), row.get("path"), row.get("title"), row.get("cve"))
        for row in db.scalars(select(Finding.detail).where(Finding.run_id == run_id))
    )


@router.get("/watches")
def watches(db: DB):
    account = linked(db)
    rows = db.execute(
        select(RepositoryWatch, Run)
        .outerjoin(Run, Run.id == RepositoryWatch.run_id)
        .where(
            RepositoryWatch.account_id == account.id,
            RepositoryWatch.github_id == account.github_id,
        )
    )
    output = {}
    for watch, run in rows:
        delta = None
        if run and run.status == "success" and watch.baseline_id:
            previous = finding_counts(db, watch.baseline_id)
            current = finding_counts(db, run.id)
            delta = {"new": sum((current - previous).values()), "fixed": sum((previous - current).values())}
        output[watch.repository_id] = {
            "enabled": watch.enabled,
            "sha": watch.sha,
            "head_sha": watch.head_sha,
            "head_committed_at": watch.head_committed_at,
            "profile": watch.profile,
            "scan_profile": watch.scan_profile,
            "scenario_revision": watch.scenario_revision,
            "scan_scenario_revision": watch.scan_scenario_revision,
            "branch": watch.branch,
            "error": watch.error,
            "run_id": run.id if run else None,
            "status": run.status if run else None,
            "count": run.count if run else None,
            "delta": delta,
        }
    return output


class WatchSetting(BaseModel):
    enabled: bool
    page: Annotated[int, Field(ge=1, le=1000)] = 1
    profile: Annotated[str, Field(min_length=1, max_length=120)] | None = None


def repository_access(db, account, repository_id, page):
    try:
        repo = github(f"/repositories/{repository_id}")
        if repo["private"] or repo["archived"]:
            raise HTTPException(404, REPOSITORY_ACCESS)
        if str(repo["owner"]["id"]) != account.github_id:
            token = repository_token(db, account.id)
            if not token:
                raise HTTPException(404, REPOSITORY_ACCESS)
            accessible = accessible_repositories(token, page)
            if not any(row["id"] == repository_id and not row["private"] for row in accessible):
                raise HTTPException(404, REPOSITORY_ACCESS)
    except GitHubLoginExpired as exc:
        raise HTTPException(403, str(exc)) from exc
    except GitHubUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return repo


def new_watch(db, account, repository_id, repo):
    row = RepositoryWatch(
        account_id=account.id, repository_id=str(repository_id),
        github_id=account.github_id, full_name=repo["full_name"],
        branch=repo["default_branch"], enabled=False, due=0,
    )
    db.add(row)
    return row


@router.put("/{repository_id}/watch")
def set_watch(repository_id: int, body: WatchSetting, db: DB):
    account = linked(db)
    key = (account.id, str(repository_id))
    row = db.get(RepositoryWatch, key)
    same_identity = row is not None and row.github_id == account.github_id
    if body.profile is not None:
        try:
            resolve_scan_profile(db, account.id, body.profile)
        except ProfileUnavailable as exc:
            raise HTTPException(404, str(exc)) from exc
    profile = body.profile or (row.profile if same_identity else "full")
    if same_identity and (row.enabled or not body.enabled):
        if row.profile != profile or row.enabled != body.enabled:
            if row.profile != profile:
                row.scenario = None
                row.scenario_revision += 1
            row.profile, row.enabled = profile, body.enabled
            row.due, row.error = 0, None
            db.commit()
        return {"enabled": row.enabled, "profile": row.profile}
    if not body.enabled and body.profile is None:
        return {"enabled": False, "profile": profile}
    if body.enabled and db.scalar(
        select(RepositoryWatch.repository_id)
        .where(RepositoryWatch.account_id == account.id, RepositoryWatch.enabled.is_(True))
        .offset(4).limit(1)
    ):
        raise HTTPException(409, "Можно отслеживать до пяти репозиториев")
    repo = repository_access(db, account, repository_id, body.page)
    if not row:
        row = new_watch(db, account, repository_id, repo)
    if row.github_id != account.github_id or row.branch != repo["default_branch"]:
        row.sha = row.run_id = row.baseline_id = None
        row.head_sha = row.head_committed_at = None
    if row.scenario is not None and (not same_identity or row.profile != profile):
        row.scenario = None
        row.scenario_revision += 1
    row.github_id = account.github_id
    row.full_name = repo["full_name"]
    row.branch = repo["default_branch"]
    row.enabled = body.enabled
    row.profile = profile
    row.due = 0
    row.error = None
    try:
        db.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "Настройка уже изменилась. Обновите список.") from exc
    return {"enabled": row.enabled, "profile": row.profile}


class ScenarioEdit(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    description: str = Field("", max_length=2000)
    graph: Graph
    revision: int = Field(ge=0)


def scenario_out(repository_id, full_name, revision, scenario):
    return {"id": str(repository_id), "repository": full_name, "revision": revision, **scenario}


@router.get("/{repository_id}/scenario")
def repository_scenario(repository_id: int, db: DB, page: int = Query(1, ge=1, le=1000)):
    account = linked(db)
    row = db.get(RepositoryWatch, (account.id, str(repository_id)))
    if row is not None and row.github_id == account.github_id:
        full_name = row.full_name
        if row.scenario is not None:
            return scenario_out(repository_id, full_name, row.scenario_revision, row.scenario)
        profile, revision = row.profile, row.scenario_revision
    else:
        full_name = repository_access(db, account, repository_id, page)["full_name"]
        profile, revision = "full", 0
    try:
        title, graph = resolve_scan_profile(db, account.id, profile)
    except ProfileUnavailable:
        title, graph = resolve_scan_profile(db, account.id, "full")
    return scenario_out(repository_id, full_name, revision, {"name": title, "description": "", "graph": graph})


@router.put("/{repository_id}/scenario")
def save_repository_scenario(
    repository_id: int, body: ScenarioEdit, db: DB, page: int = Query(1, ge=1, le=1000)
):
    account = linked(db)
    scenario = body.model_dump(exclude={"revision"})
    scenario["graph"] = commit_triggered_graph(scenario["graph"])
    revision = body.revision + 1
    row = db.get(RepositoryWatch, (account.id, str(repository_id)))
    conflict = HTTPException(409, "Сценарий изменён в другой вкладке. Обновите страницу.")
    if row is None or row.github_id != account.github_id:
        if body.revision:
            raise conflict
        repo = repository_access(db, account, repository_id, page)
        full_name = repo["full_name"]
        if row is None:
            row = new_watch(db, account, repository_id, repo)
            row.scenario, row.scenario_revision = scenario, revision
        else:
            changed = db.execute(update(RepositoryWatch).where(
                RepositoryWatch.account_id == account.id,
                RepositoryWatch.repository_id == str(repository_id),
                RepositoryWatch.github_id == row.github_id,
                RepositoryWatch.scenario_revision == row.scenario_revision,
            ).values(
                github_id=account.github_id, full_name=repo["full_name"], branch=repo["default_branch"],
                enabled=False, due=0, error=None, profile="full", scan_profile="full",
                scenario=scenario, scenario_revision=revision, scan_scenario_revision=0,
                sha=None, head_sha=None, head_committed_at=None, run_id=None, baseline_id=None,
            ))
            if not changed.rowcount:
                raise conflict
    else:
        full_name = row.full_name
        changed = db.execute(update(RepositoryWatch).where(
            RepositoryWatch.account_id == account.id,
            RepositoryWatch.repository_id == str(repository_id),
            RepositoryWatch.github_id == account.github_id,
            RepositoryWatch.scenario_revision == body.revision,
        ).values(scenario=scenario, scenario_revision=revision, due=0, error=None))
        if not changed.rowcount:
            raise conflict
    try:
        db.commit()
    except IntegrityError as exc:
        raise conflict from exc
    return scenario_out(repository_id, full_name, revision, scenario)


@router.post("/{repository_id}/scenario/validate")
def validate_repository_scenario(repository_id: int, body: Graph, db: DB):
    linked(db)
    commit_triggered_graph(body.model_dump())
    return {"valid": True}


def inspect_repository(key, prepare_scan, interval=INTERVAL):
    with Session() as db:
        watch = db.get(RepositoryWatch, key)
        now = time.time()
        if not watch or not watch.enabled or watch.due > now:
            return
        account = db.get(Account, watch.account_id)
        if account.github_id != watch.github_id:
            return
        last = db.get(Run, watch.run_id) if watch.run_id else None
        if last and last.status in ("queued", "running"):
            return
        # Claim once across worker processes, without holding a lock during HTTP.
        claimed = now + interval
        claim = db.execute(update(RepositoryWatch).where(
            RepositoryWatch.account_id == key[0],
            RepositoryWatch.repository_id == key[1],
            RepositoryWatch.enabled.is_(True),
            RepositoryWatch.due == watch.due,
        ).values(due=claimed))
        db.commit()
        if not claim.rowcount:
            return
        watch = db.get(RepositoryWatch, key)
        full_name, branch, identity = watch.full_name, watch.branch, watch.github_id
        profile = watch.profile
        previous_sha, previous_profile = watch.sha, watch.scan_profile
        scenario = watch.scenario
        scenario_revision = watch.scenario_revision
        scenario_changed = scenario_revision != watch.scan_scenario_revision
        db.rollback()

        error = None
        limit_delay = None
        retry_after = interval
        scan = None
        head = None
        try:
            owner, name = (quote(part, safe="") for part in full_name.split("/"))
            commits = github(f"/repos/{owner}/{name}/commits", sha=branch, per_page=1)
            if not commits:
                raise GitHubUnavailable(EMPTY_REPOSITORY)
            sha = commits[0]["sha"]
            if not re.fullmatch(r"[a-f0-9]{40}", sha):
                raise ValueError("GitHub вернул некорректный идентификатор коммита")
            commit_date = ((commits[0].get("commit") or {}).get("committer") or {}).get("date")
            committed_at = datetime.fromisoformat(commit_date).timestamp() if commit_date else None
            head = (sha, committed_at)
            if sha != previous_sha or profile != previous_profile or scenario_changed:
                if scenario is not None:
                    title, graph = scenario["name"], commit_triggered_graph(scenario["graph"])
                else:
                    with Session() as profile_db:
                        title, graph = resolve_scan_profile(profile_db, key[0], profile)
                scan = prepare_scan(full_name, sha, title, graph)
        except GitHubUnavailable as exc:
            error = str(exc)
            retry_after = max(interval, exc.retry_after)
            if exc.retry_after > INTERVAL:
                limit_delay = exc.retry_after
        except (ValueError, ProfileUnavailable) as exc:
            error = str(exc)

        # Verify the watch is still current before writing a run.
        changed = db.execute(update(RepositoryWatch).where(
            RepositoryWatch.account_id == key[0],
            RepositoryWatch.repository_id == key[1],
            RepositoryWatch.github_id == identity,
            RepositoryWatch.profile == profile,
            RepositoryWatch.scenario_revision == scenario_revision,
            RepositoryWatch.enabled.is_(True),
            RepositoryWatch.due == claimed,
        ).values(due=max(claimed, time.time() + retry_after), error=error))
        if not changed.rowcount:
            return
        watch = db.get(RepositoryWatch, key)
        account = db.get(Account, key[0])
        if account.github_id != identity:
            return
        if head:
            watch.head_sha, watch.head_committed_at = head
        if scan is not None:
            prior = db.get(Run, watch.run_id) if watch.run_id else None
            if profile != previous_profile or scenario_changed:
                watch.baseline_id = None
            elif prior and prior.status == "success":
                watch.baseline_id = prior.id
            db.info["account"] = account
            watch.run_id = scan(db).id
            watch.sha = sha
            watch.scan_profile = profile
            watch.scan_scenario_revision = scenario_revision
        db.commit()
        return limit_delay


def watch_worker(stop, prepare_scan):
    while not stop.is_set():
        delay = 5
        try:
            with Session() as db:
                active = (
                    select(RepositoryWatch.account_id, RepositoryWatch.repository_id)
                    .join(Account, Account.id == RepositoryWatch.account_id)
                    .where(
                        RepositoryWatch.enabled.is_(True),
                        RepositoryWatch.github_id == Account.github_id,
                    )
                )
                # Anonymous GitHub requests share an hourly budget. Leave room for listing.
                count = db.scalar(select(func.count()).select_from(active.subquery()))
                interval = max(INTERVAL, 75 * count)
                keys = db.execute(
                    active.where(RepositoryWatch.due <= time.time())
                    .order_by(RepositoryWatch.due)
                ).all()
            for key in keys:
                if stop.is_set():
                    break
                limit_delay = inspect_repository(tuple(key), prepare_scan, interval)
                if limit_delay:
                    delay = limit_delay
                    break
        except Exception:
            logger.exception("GitHub repository watch failed")
        stop.wait(delay)
