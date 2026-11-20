import io
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

# All tests run against an isolated workspace, including when a local app is running.
_workspace = tempfile.TemporaryDirectory()
os.environ["CENTERAI_DATA"] = _workspace.name
os.environ["DATABASE_URL"] = (
    "sqlite:///" + (Path(_workspace.name) / "test.db").as_posix()
)
os.environ["WORKER_MODE"] = "test"

from fastapi.testclient import TestClient
from backend.api import app
from backend.db import Base, engine


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    _workspace.cleanup()


def zip_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, source in files.items():
            archive.writestr(path, source)
    return out.getvalue()


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def project(client):
    archive = zip_bytes(
        {
            "work/build.gradle.kts": 'dependencies { implementation("org.jsoup:jsoup:1.14.1") }',
            "work/src/X.kt": 'class Config { val apiKey = "example" }\nval labPassword = "synthetic_fixture_21"',
        }
    )
    res = client.post(
        "/api/v1/projects",
        data={"name": "Workshop"},
        files={"archive": ("work.zip", archive)},
    )
    assert res.status_code == 201, res.text
    return res.json()
