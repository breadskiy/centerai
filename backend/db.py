import os
import time
from pathlib import Path
from uuid import uuid4
from cryptography.fernet import Fernet
from sqlalchemy import (
    Float,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATA = Path(os.getenv("CENTERAI_DATA", "data")).resolve()
DATA.mkdir(parents=True, exist_ok=True)
URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA / 'centerai.db').as_posix()}")
engine = create_engine(
    URL,
    pool_pre_ping=True,
    **({"connect_args": {"timeout": 20}} if URL.startswith("sqlite") else {}),
)
if URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


def cipher():
    key = os.getenv("CENTERAI_KEY")
    if key:
        return Fernet(key.encode())
    path = DATA / "workspace.key"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as file:
            file.write(Fernet.generate_key())
    return Fernet(path.read_bytes())


def uid():
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str]
    description: Mapped[str]
    source: Mapped[str]
    source_type: Mapped[str]
    snapshot: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    file_count: Mapped[int]
    created: Mapped[float] = mapped_column(default=time.time)
    archived: Mapped[bool] = mapped_column(default=False)


class Workflow(Base):
    __tablename__ = "workflows"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    revision: Mapped[int] = mapped_column(default=1)
    graph: Mapped[dict] = mapped_column(JSON)
    archived: Mapped[bool] = mapped_column(default=False)
    next_due: Mapped[float | None] = mapped_column(Float, index=True)


class Version(Base):
    __tablename__ = "workflow_versions"
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(primary_key=True)
    description: Mapped[str] = mapped_column(default="")
    name: Mapped[str]
    graph: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(default=time.time)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    workflow_name: Mapped[str]
    project_name: Mapped[str]
    revision: Mapped[int]
    graph: Mapped[dict] = mapped_column(JSON)
    trigger: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued", index=True)
    created: Mapped[float] = mapped_column(default=time.time, index=True)
    started: Mapped[float | None] = mapped_column(Float)
    finished: Mapped[float | None] = mapped_column(Float)
    heartbeat: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None]
    count: Mapped[int] = mapped_column(default=0)


class NodeRun(Base):
    __tablename__ = "node_runs"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str]
    started: Mapped[float | None] = mapped_column(Float)
    finished: Mapped[float | None] = mapped_column(Float)
    output: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    status: Mapped[str]
    node_id: Mapped[str | None]
    message: Mapped[str]
    created: Mapped[float] = mapped_column(default=time.time)


class Finding(Base):
    __tablename__ = "findings"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(primary_key=True)
    severity: Mapped[str] = mapped_column(index=True)
    category: Mapped[str] = mapped_column(index=True)
    detail: Mapped[dict] = mapped_column(JSON)


class Credential(Base):
    __tablename__ = "credentials"
    provider: Mapped[str] = mapped_column(primary_key=True)
    encrypted: Mapped[bytes] = mapped_column(LargeBinary)
