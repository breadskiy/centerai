import asyncio
import json
import os
import time
from collections import Counter
from contextlib import asynccontextmanager
from threading import Event as Stop, Thread
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from typing import Annotated
from sqlalchemy import case, func, select, update
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import notifications
from .analyzers.common import SubmissionReportExporter
from .db import Base, Credential, Event, Finding, NodeRun, Project, Run, Session, Version, Workflow, cipher, engine
from .graph import Graph, LEVELS, REGISTRY, default_graph, next_due, validate
from .sources import MAX_UPLOAD, fetch_repository, unpack
from .worker import enqueue, local_worker
from .migrate import upgrade

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


@asynccontextmanager
async def lifespan(app):
    upgrade()
    cipher()
    stop = Stop()
    worker = None
    if os.getenv("WORKER_MODE", "local") == "local":
        worker = Thread(target=local_worker, args=(stop,), daemon=True)
        worker.start()
    yield
    stop.set()
    if worker:
        await asyncio.to_thread(worker.join, 15)
    engine.dispose()


app = FastAPI(title="CenterAI Security Workflow", version="1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(","))


@app.middleware("http")
async def request_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host") and origin not in os.getenv("UI_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(","):
            return JSONResponse({"detail": "Недопустимый источник запроса"}, 403)
        limit = MAX_UPLOAD + 65536 if request.url.path.endswith("/projects") else 256 * 1024
        if int(request.headers.get("content-length", 0)) > limit:
            return JSONResponse({"detail": "Превышен лимит запроса"}, 413)
        # Bound chunked uploads before multipart parsers allocate temporary files.
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > limit:
                return JSONResponse({"detail": "Превышен лимит запроса"}, 413)
            data.extend(chunk)
        request._body = bytes(data)
    return await call_next(request)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({"detail": str(exc)}, 422)


@app.exception_handler(RequestValidationError)
async def invalid_fields(request, exc):
    fields = ", ".join(".".join(map(str, e["loc"][1:])) for e in exc.errors())
    return JSONResponse({"detail": "Проверьте поля: " + fields}, 422)


def session():
    with Session() as db:
        yield db


DB = Annotated[Session, Depends(session)]
api = APIRouter(prefix="/api/v1")


def get(db, model, key):
    row = db.get(model, key)
    if not row or getattr(row, "archived", False):
        raise HTTPException(404, "Запись не найдена")
    return row


def fields(row, *names):
    return {k: getattr(row, k) for k in names}


def project_out(db, row):
    count, last = db.execute(select(func.count(Run.id), func.max(Run.created)).where(Run.project_id == row.id)).one()
    return {**fields(row, "id", "name", "description", "source", "source_type", "file_count", "created"), "runs": count, "last_run": last}


def flow_out(db, row):
    last = db.scalar(select(Run.status).where(Run.workflow_id == row.id).order_by(Run.created.desc()).limit(1))
    return {**fields(row, "id", "project_id", "name", "revision", "graph", "next_due"), "last_status": last}


def run_out(row):
    return fields(row, "id", "project_id", "project_name", "workflow_id", "workflow_name", "revision", "trigger",
                  "status", "created", "started", "finished", "count", "error")


class ProjectEdit(BaseModel):
    name: Name
    description: str = Field(default="", max_length=2000)


class FlowEdit(BaseModel):
    name: Name
    graph: Graph
    revision: int = 1


class FlowCreate(FlowEdit):
    project_id: str


class TelegramConfig(BaseModel):
    token: str = Field(default="", max_length=150)
    chat: str = Field(max_length=64)


@api.get("/registry")
def registry():
    return {"types": {k: fields(v, "title", "category", "description", "input", "output", "defaults") for k, v in REGISTRY.items()},
            "default_graph": default_graph()}


@api.get("/dashboard")
def dashboard(db: DB):
    def count(model, *criteria):
        return db.scalar(select(func.count()).select_from(model).where(*criteria))
    return {"projects": count(Project, Project.archived.is_(False)), "workflows": count(Workflow, Workflow.archived.is_(False)),
            "runs": count(Run), "findings": count(Finding),
            "levels": dict(db.execute(select(Finding.severity, func.count()).group_by(Finding.severity)).all()),
            "recent": [run_out(r) for r in db.scalars(select(Run).order_by(Run.created.desc()).limit(5))]}


@api.get("/projects")
def projects(db: DB):
    return [project_out(db, p) for p in db.scalars(select(Project).where(Project.archived.is_(False)).order_by(Project.created.desc()))]


@api.post("/projects", status_code=201)
def create_project(db: DB, name: Name = Form(), description: str = Form("", max_length=2000),
                   archive: UploadFile | None = File(None), repository: str = Form("", max_length=500)):
    if bool(archive) == bool(repository):
        raise ValueError("Выберите один источник проекта")
    files = unpack(archive.file.read(MAX_UPLOAD + 1)) if archive else fetch_repository(repository)
    if not name.strip():
        raise ValueError("Укажите название проекта")
    row = Project(name=name.strip(), description=description, source=(archive.filename or "project.zip") if archive else repository,
                  source_type="ZIP" if archive else "GitHub", file_count=len(files),
                  snapshot=cipher().encrypt(json.dumps(files, ensure_ascii=False).encode()))
    db.add(row)
    db.commit()
    return project_out(db, row)


@api.get("/projects/{key}")
def project(key: str, db: DB):
    return project_out(db, get(db, Project, key))


@api.patch("/projects/{key}")
def edit_project(key: str, body: ProjectEdit, db: DB):
    row = get(db, Project, key)
    row.name, row.description = body.name, body.description
    db.commit()
    return project_out(db, row)


@api.delete("/projects/{key}")
def delete_project(key: str, db: DB):
    get(db, Project, key).archived = True
    db.execute(update(Workflow).where(Workflow.project_id == key).values(archived=True, next_due=None))
    db.commit()
    return {"ok": True}


@api.get("/workflows")
def workflows(db: DB, project_id: str | None = None):
    query = select(Workflow).where(Workflow.archived.is_(False))
    if project_id:
        query = query.where(Workflow.project_id == project_id)
    return [flow_out(db, w) for w in db.scalars(query.order_by(Workflow.name))]


def schedule(graph):
    for node in graph["nodes"]:
        if node["type"] == "schedule_trigger" and node["config"].get("enabled"):
            validate(graph)
            return next_due(node["config"], time.time())
    return None


def version(db, row):
    db.add(Version(workflow_id=row.id, revision=row.revision, name=row.name, graph=row.graph))


@api.post("/workflows", status_code=201)
def create_flow(body: FlowCreate, db: DB):
    get(db, Project, body.project_id)
    graph = body.graph.model_dump()
    row = Workflow(name=body.name, project_id=body.project_id, graph=graph, next_due=schedule(graph))
    db.add(row)
    db.flush()
    version(db, row)
    db.commit()
    return flow_out(db, row)


@api.get("/workflows/{key}")
def workflow(key: str, db: DB):
    return flow_out(db, get(db, Workflow, key))


@api.put("/workflows/{key}")
def edit_flow(key: str, body: FlowEdit, db: DB):
    get(db, Workflow, key)
    graph = body.graph.model_dump()
    result = db.execute(update(Workflow).where(Workflow.id == key, Workflow.archived.is_(False), Workflow.revision == body.revision)
                        .values(name=body.name, revision=body.revision + 1, graph=graph, next_due=schedule(graph)))
    if not result.rowcount:
        raise HTTPException(409, "Сценарий изменён в другой вкладке. Обновите страницу.")
    row = db.get(Workflow, key)
    version(db, row)
    db.commit()
    return flow_out(db, row)


@api.delete("/workflows/{key}")
def delete_flow(key: str, db: DB):
    row = get(db, Workflow, key)
    row.archived, row.next_due = True, None
    db.commit()
    return {"ok": True}


@api.get("/workflows/{key}/versions")
def versions(key: str, db: DB):
    return [fields(v, "revision", "name", "graph", "created") for v in db.scalars(select(Version).where(Version.workflow_id == key).order_by(Version.revision.desc()))]


@api.post("/workflows/{key}/validate")
def validate_flow(key: str, db: DB, graph: Graph | None = None):
    flow = get(db, Workflow, key)
    _, _, order = validate(graph.model_dump() if graph else flow.graph)
    return {"valid": True, "order": order}


@api.post("/workflows/{key}/runs", status_code=202)
def start(key: str, db: DB):
    row = enqueue(db, get(db, Workflow, key), "manual")
    db.commit()
    return run_out(row)


@api.get("/runs")
def runs(db: DB, project_id: str | None = None, workflow_id: str | None = None, status: str | None = None,
         offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    q = select(Run)
    for column, value in [(Run.project_id, project_id), (Run.workflow_id, workflow_id), (Run.status, status)]:
        if value:
            q = q.where(column == value)
    return [run_out(row) for row in db.scalars(q.order_by(Run.created.desc()).offset(offset).limit(limit))]


@api.get("/runs/{key}")
def run(key: str, db: DB):
    row = get(db, Run, key)
    nodes = db.scalars(select(NodeRun).where(NodeRun.run_id == key)).all()
    return {**run_out(row), "graph": row.graph,
            "nodes": [fields(n, "node_id", "status", "output", "started", "finished") for n in nodes],
            "events": [event_out(e) for e in db.scalars(select(Event).where(Event.run_id == key).order_by(Event.id))]}


def event_out(e):
    return fields(e, "id", "status", "message", "node_id", "created")


@api.get("/runs/{key}/events")
async def events(key: str, request: Request):
    with Session() as db:
        get(db, Run, key)
    async def stream():
        cursor = int(request.headers.get("last-event-id", "0"))
        while not await request.is_disconnected():
            with Session() as db:
                status = db.get(Run, key).status
                batch = [event_out(e) for e in db.scalars(select(Event).where(Event.run_id == key, Event.id > cursor).order_by(Event.id))]
            for e in batch:
                cursor = e["id"]
                yield f"id: {cursor}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
            if status in ("success", "failed", "cancelled"):
                yield "event: done\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(.4)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@api.get("/findings")
def findings(db: DB, run_id: str | None = None, severity: str | None = None, category: str | None = None,
             q: str = "", sort: str = Query("severity", pattern="^(severity|path)$"), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    query = select(Finding, Run.created).join(Run, Finding.run_id == Run.id)
    for column, value in [(Finding.run_id, run_id), (Finding.severity, severity), (Finding.category, category)]:
        if value:
            query = query.where(column == value)
    if q:
        from sqlalchemy import or_
        query = query.where(or_(*(Finding.detail[k].as_string().icontains(q, autoescape=True) for k in ("path", "title", "class", "advisoryId"))))
    order = Finding.detail["path"].as_string() if sort == "path" else case(
        {level: i for i, level in enumerate(LEVELS)}, value=Finding.severity, else_=6)
    return [{**r.detail, "run_id": r.run_id} for r, _ in db.execute(query.order_by(order, Run.created.desc(), Finding.fingerprint).offset(offset).limit(limit))]


@api.get("/runs/{key}/report")
def export(key: str, db: DB, format: str = Query("json", pattern="^(json|txt)$")):
    row = get(db, Run, key)
    if row.status not in ("success", "failed"):
        raise HTTPException(409, "Дождитесь завершения проверки")
    rows = [r.detail for r in db.scalars(select(Finding).where(Finding.run_id == key).order_by(Finding.fingerprint))]
    report = SubmissionReportExporter.export(rows)
    headers = {"Content-Disposition": f'attachment; filename="centerai-{key[:8]}.{format}"'}
    if format == "json":
        return JSONResponse(report, headers=headers)
    lines = [row.project_name, row.workflow_name, f"Статус: {row.status}", f"Находки: {len(rows)}"]
    for f in rows:
        lines.extend(["", f"{f['severity']} · {f['title']}", f"{f['path']}:{f['line']}", f["description"], f["evidence"],
                      f.get("advisoryId", f["class"]), f["remediation"]])
    return PlainTextResponse("\n".join(lines), headers=headers)


@api.get("/settings")
@api.get("/integrations")
def settings(db: DB):
    return {"telegram": bool(db.get(Credential, "telegram")), "repositories": os.getenv("ALLOWED_REPOSITORIES", "TBagirov/training").split(","),
            "worker": os.getenv("WORKER_MODE", "local")}


@api.put("/integrations/telegram")
def telegram_update(body: TelegramConfig, db: DB):
    notifications.configure(db, body.token, body.chat)
    return settings(db)


@api.post("/integrations/telegram/test")
def telegram_test(db: DB):
    notifications.telegram(db)
    return {"delivered": True}


app.include_router(api)
from pathlib import Path
from fastapi.responses import FileResponse
dist = Path(__file__).resolve().parents[1] / "frontend/dist"
if dist.is_dir():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{route:path}", include_in_schema=False)
    def frontend(route: str):
        if route.startswith("api/"):
            raise HTTPException(404, "Метод не найден")
        return FileResponse(dist / "index.html")
