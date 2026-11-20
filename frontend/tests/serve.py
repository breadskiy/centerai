"""Isolated API, real worker, compiled UI and small synthetic ZIP for browser tests."""
import io
import os
from pathlib import Path
import tempfile
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import uvicorn

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as workspace:
        os.environ["CENTERAI_DATA"] = workspace
        os.environ.pop("DATABASE_URL", None)
        os.environ["WORKER_MODE"] = "local"
        qa = ROOT / ".qa"
        qa.mkdir(exist_ok=True)
        with zipfile.ZipFile(qa / "e2e-fixture.zip", "w") as archive:
            archive.writestr("build.gradle.kts", 'dependencies { implementation("org.jsoup:jsoup:1.14.1") }')
            archive.writestr("src/Config.kt", 'val apiKey = "synthetic_fixture_only"')
        uvicorn.run("backend.api:app", host="127.0.0.1", port=8765)
