"""Run an isolated Windows demo with local inference and an SMTP inbox."""

import argparse
import hashlib
import os
import secrets
import socket
import subprocess
import sys
import time
import webbrowser
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".qa" / "model"
DATA = ROOT / ".qa" / "full-demo"
ASSETS = [
    (
        "llama.zip",
        "https://github.com/ggml-org/llama.cpp/releases/download/b12600/llama-b12600-bin-win-cpu-x64.zip",
        "a31a14f1630408422228d02ff2a3fc41c06a6b3b3849d8d2782c37f0f6e30951",
        "runtime",
    ),
    (
        "mailpit.zip",
        "https://github.com/axllent/mailpit/releases/download/v1.34.0/mailpit-windows-amd64.zip",
        "8f080d41374bf22686606374a0a483c8563c1bf29ae078179792392ff8c911d7",
        "mailpit",
    ),
    (
        "qwen.gguf",
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/dd26da440ef0330c47919d1ecae0966d24022222/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e",
        None,
    ),
]


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare():
    CACHE.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    for name, url, digest, folder in ASSETS:
        path = CACHE / name
        if not path.exists() or checksum(path) != digest:
            tmp = path.with_suffix(".download")
            subprocess.run(
                ["curl.exe", "-fL", "--retry", "2", "-o", tmp, url], check=True
            )
            if checksum(tmp) != digest:
                raise RuntimeError(f"Checksum failed for {name}")
            tmp.replace(path)
        if folder:
            with zipfile.ZipFile(path) as archive:
                archive.extractall(CACHE / folder)


def run(port, open_browser):
    for number in (port, 8091, 8025, 1025):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", number))
    prepare()
    base = f"http://127.0.0.1:{port}"
    env = os.environ | {
        "CENTERAI_DATA": str(DATA),
        "DATABASE_URL": f"sqlite:///{(DATA / 'centerai.db').as_posix()}",
        "WORKER_MODE": "local",
        "PUBLIC_URL": base,
        "CENTERAI_DEMO": "1",
        "AI_PROVIDER": "openai-compatible",
        "AI_MODEL": "qwen-local",
        "AI_BASE_URL": "http://127.0.0.1:8091/v1",
        "AI_API_KEY": secrets.token_urlsafe(32),
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "1025",
        "SMTP_SECURITY": "local",
        "SMTP_FROM": "centerai@example.test",
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
    }
    commands = [
        (
            "model",
            [
                CACHE / "runtime/llama-server.exe",
                "-m",
                CACHE / "qwen.gguf",
                "--alias",
                "qwen-local",
                "--api-key",
                env["AI_API_KEY"],
                "--host",
                "127.0.0.1",
                "--port",
                "8091",
                "-c",
                "8192",
                "-np",
                "1",
                "-t",
                "6",
                "--temp",
                "0",
            ],
            "http://127.0.0.1:8091/health",
        ),
        (
            "mail",
            [
                CACHE / "mailpit/mailpit.exe",
                "--listen",
                "127.0.0.1:8025",
                "--smtp",
                "127.0.0.1:1025",
                "--database",
                DATA / "mail.db",
            ],
            "http://127.0.0.1:8025/livez",
        ),
        (
            "app",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            base + "/api/v1/settings",
        ),
    ]
    children = []
    opener = build_opener(ProxyHandler({}))
    try:
        for name, cmd, health in commands:
            with (DATA / f"{name}.log").open("w", encoding="utf-8") as log:
                child = subprocess.Popen(
                    cmd,
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            children.append(child)
            for _ in range(120):
                if child.poll() is not None:
                    raise RuntimeError(f"{name} stopped. See {DATA / (name + '.log')}")
                try:
                    with opener.open(health, timeout=1):
                        break
                except (URLError, OSError):
                    time.sleep(0.5)
            else:
                raise RuntimeError(f"{name} did not become ready")
        print(
            f"CenterAI: {base}   Mail inbox: http://127.0.0.1:8025   Ctrl+C to stop",
            flush=True,
        )
        if open_browser:
            webbrowser.open(base)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError(f"A demo service stopped. See {DATA}")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8002)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    try:
        run(args.port, args.open_browser)
    except KeyboardInterrupt:
        pass
