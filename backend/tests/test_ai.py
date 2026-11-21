import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from backend import ai_report
from backend.graph import default_graph
from backend.worker import tick

from .test_workflow import API, create_flow


@pytest.mark.parametrize("compatible", [False, True])
def test_provider_http_contract(compatible):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers.get("Authorization"), body))
            message = {"content": "validated separately"}
            envelope = (
                {"choices": [{"message": message}]}
                if compatible
                else {"message": message}
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(envelope).encode())

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            if compatible:
                provider = ai_report.OpenAICompatibleProvider(
                    "fixture", base + "/v1", "fixture-key"
                )
            else:
                provider = ai_report.OllamaProvider("fixture", base)
            schema = ai_report.AIReport.model_json_schema()
            assert provider.complete([], schema) == "validated separately"
        finally:
            server.shutdown()
            thread.join()
    path, authorization, body = received[0]
    assert path == ("/v1/chat/completions" if compatible else "/api/chat")
    assert authorization == ("Bearer fixture-key" if compatible else None)
    sent_schema = (
        body["response_format"]["json_schema"]["schema"]
        if compatible
        else body["format"]
    )
    assert sent_schema == schema


@pytest.mark.parametrize(
    "mode", ["valid", "wrong_id", "unknown_cve", "fake_line", "offline"]
)
def test_ai_workflow(client, project, monkeypatch, mode):
    calls = []

    def complete(self, messages, schema):
        calls.append(1)
        assert "findings" in schema["properties"]
        payload = messages[1]["content"]
        assert all(
            value not in payload
            for value in ("synthetic_fixture", "src/X.kt", "build.gradle.kts")
        )
        if mode == "offline":
            raise ConnectionError()
        notes = []
        for source in json.loads(payload):
            notes.append(
                {
                    "finding_id": "unknown"
                    if mode == "wrong_id"
                    else source["finding_id"],
                    "explanation": "line 42" if mode == "fake_line" else "Объяснение",
                    "technical_details": "",
                    "business_impact": "",
                    "false_positive_notes": "",
                    "remediation_steps": ["Шаг исправления"],
                    "evidence_status": "SUPPORTED",
                    "cve_references": ["CVE-2000-1234"]
                    if mode == "unknown_cve"
                    else [],
                }
            )
        return json.dumps(
            {
                "summary": "Итог",
                "findings": notes,
                "prioritized_actions": [],
                "limitations": [],
            }
        )

    monkeypatch.setenv("AI_PROVIDER", "ollama")
    monkeypatch.setattr(ai_report.OllamaProvider, "complete", complete)
    graph = default_graph()
    graph["nodes"].append(
        {"id": "ai", "type": "ai_analysis", "config": {"model": "test-model"}}
    )
    for edge in graph["edges"]:
        if edge["target"] == "report_generator":
            edge["target"] = "ai"
    graph["edges"].append({"source": "ai", "target": "report_generator"})
    flow = create_flow(client, project, graph)
    run = client.post(f"{API}/workflows/{flow['id']}/runs").json()
    tick()
    path = f"{API}/runs/{run['id']}"
    assert client.get(path).json()["status"] == "success"
    meta = client.get(path + "/nodes/ai").json()["output"]["ai"]
    ok = mode == "valid"
    assert meta["status"] == ("ok" if ok else "ai_unavailable")
    assert meta["model"] == "test-model" and meta["prompt_version"]
    assert len(calls) == (1 if ok else 2)
    rows = client.get(API + "/findings", params={"run_id": run["id"]}).json()
    assert len(rows) == 2 and all(("ai" in row) == ok for row in rows)
    assert all(
        "ai" not in row for row in client.get(path + "/report").json()["findings"]
    )
    assert ("Шаг исправления" in client.get(path + "/report?format=txt").text) == ok
