"""Isolated API, real worker, compiled UI and small synthetic ZIP for browser tests."""

import json
import os
import socketserver
from email import policy
from email.parser import BytesParser
from pathlib import Path
import tempfile
from threading import Thread
import zipfile
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import uvicorn


class CaptureMail(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 Test mailbox\r\n")
        for line in self.rfile:
            command = line.split(maxsplit=1)[0].upper() if line.strip() else b""
            if command == b"DATA":
                self.wfile.write(b"354 End data with a dot\r\n")
                lines = []
                for part in self.rfile:
                    if part == b".\r\n":
                        break
                    lines.append(part[1:] if part.startswith(b"..") else part)
                message = BytesParser(policy=policy.default).parsebytes(b"".join(lines))
                mailbox = ROOT / ".qa/e2e-mail.json"
                temporary = mailbox.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps(
                        {
                            "from": str(message["From"]),
                            "to": str(message["To"]),
                            "body": message.get_content(),
                        }
                    ),
                    encoding="utf-8",
                )
                temporary.replace(mailbox)
            elif command == b"QUIT":
                self.wfile.write(b"221 Closing\r\n")
                return
            self.wfile.write(b"250 OK\r\n")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as workspace:
        os.environ["CENTERAI_DATA"] = workspace
        os.environ.pop("DATABASE_URL", None)
        os.environ["WORKER_MODE"] = "local"
        os.environ["AI_PROVIDER"] = "ollama"
        os.environ["AI_BASE_URL"] = "http://127.0.0.1:1"
        os.environ["GITHUB_CLIENT_ID"] = "browser-test-client"
        os.environ["GITHUB_CLIENT_SECRET"] = "browser-test-secret"
        os.environ["GITHUB_OAUTH_CALLBACK_URL"] = (
            "http://127.0.0.1:8765/api/v1/auth/github/callback"
        )
        qa = ROOT / ".qa"
        qa.mkdir(exist_ok=True)
        with zipfile.ZipFile(qa / "e2e-fixture.zip", "w") as archive:
            archive.writestr(
                "build.gradle.kts",
                'dependencies { implementation("org.jsoup:jsoup:1.14.1") }',
            )
            archive.writestr("src/Config.kt", 'val apiKey = "synthetic_fixture_only"')
        (qa / "e2e-mail.json").unlink(missing_ok=True)
        with socketserver.TCPServer(("127.0.0.1", 0), CaptureMail) as smtp:
            os.environ.update(
                SMTP_HOST="127.0.0.1",
                SMTP_PORT=str(smtp.server_address[1]),
                SMTP_SECURITY="local",
                SMTP_FROM="noreply@example.com",
                PUBLIC_URL="http://127.0.0.1:8765",
            )
            os.environ.pop("SMTP_USER", None)
            os.environ.pop("SMTP_PASSWORD", None)
            Thread(target=smtp.serve_forever, daemon=True).start()
            try:
                uvicorn.run("backend.api:app", host="127.0.0.1", port=8765)
            finally:
                smtp.shutdown()
