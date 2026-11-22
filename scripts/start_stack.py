"""Run CenTRap on Windows with a local model or a configured AI provider."""

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
LOGS = ROOT / ".qa" / "startup"
ASSETS = [
    (
        "llama.zip",
        "https://github.com/ggml-org/llama.cpp/releases/download/b12600/llama-b12600-bin-win-cpu-x64.zip",
        "a31a14f1630408422228d02ff2a3fc41c06a6b3b3849d8d2782c37f0f6e30951",
        "runtime",
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


def build_id():
    paths = [
        ROOT / "frontend" / name
        for name in (
            "index.html",
            "package.json",
            "package-lock.json",
            "vite.config.ts",
            "tsconfig.json",
        )
    ]
    paths += list((ROOT / "frontend" / "src").rglob("*"))
    paths += list((ROOT / "frontend" / "public").rglob("*"))
    paths += list((ROOT / "backend").rglob("*"))
    paths += [
        ROOT / "scripts" / name
        for name in ("start.ps1", "local_services.ps1", "start_stack.py")
    ]
    digest = hashlib.sha256()
    for path in sorted(paths):
        if not path.is_file() or "__pycache__" in path.parts or "tests" in path.parts:
            continue
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(checksum(path)))
    return digest.hexdigest()


def run(port, release=None):
    base = f"http://127.0.0.1:{port}"
    env = os.environ | {
        "WORKER_MODE": "local",
        "PUBLIC_URL": os.getenv("PUBLIC_URL") or base,
        "CENTERAI_BUILD_ID": release or build_id(),
    }
    commands = []
    configured = any(
        os.getenv(key)
        for key in ("AI_PROVIDER", "AI_BASE_URL", "AI_MODEL", "AI_API_KEY")
    )
    ports = (port,) if configured else (port, 8091)
    for number in ports:
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", number))
        except OSError:
            raise RuntimeError(f"Port {number} is already in use") from None
    if not configured:
        print("Preparing the local Qwen model…", flush=True)
        prepare()
        env.update(
            {
                "AI_PROVIDER": "openai-compatible",
                "AI_MODEL": "qwen-local",
                "AI_BASE_URL": "http://127.0.0.1:8091/v1",
                "AI_API_KEY": secrets.token_urlsafe(32),
            }
        )
        commands.append(
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
            )
        )
    commands.append(
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
            base + "/api/v1/auth/session",
        )
    )
    LOGS.mkdir(parents=True, exist_ok=True)
    children = []
    opener = build_opener(ProxyHandler({}))
    try:
        for name, cmd, health in commands:
            with (LOGS / f"{name}.log").open("w", encoding="utf-8") as log:
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
                    raise RuntimeError(f"{name} stopped. See {LOGS / (name + '.log')}")
                try:
                    with opener.open(health, timeout=1):
                        break
                except (URLError, OSError):
                    time.sleep(0.5)
            else:
                raise RuntimeError(f"{name} did not become ready")
        print(
            f"CenTRap: {base}   Ctrl+C to stop",
            flush=True,
        )
        webbrowser.open(f"{base}/?build={env['CENTERAI_BUILD_ID']}")
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError(f"A CenTRap service stopped. See {LOGS}")
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                child.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--build-id", action="store_true")
    parser.add_argument("--release")
    args = parser.parse_args()
    if args.build_id:
        print(build_id())
        sys.exit()
    try:
        run(args.port, args.release)
    except KeyboardInterrupt:
        pass
