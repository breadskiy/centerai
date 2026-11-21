"""Acceptance check for a fresh live stack. No fixture database or direct worker calls."""

import json
import os
from pathlib import Path
import time
import httpx

from ci_scan import scan


def verify():
    base = os.getenv("CENTERAI_TEST_URL", "http://127.0.0.1:8000")
    output = Path(".qa/stack-reports")
    with httpx.Client(base_url=base + "/api/v1/", timeout=45) as client:
        settings = client.get("settings").raise_for_status().json()
        assert settings["worker"] == "celery"
        project = (
            client.post(
                "projects",
                data={
                    "name": "Acceptance · Repair Desk",
                    "repository": "https://github.com/TBagirov/training",
                },
            )
            .raise_for_status()
            .json()
        )
        graph = client.get("registry").raise_for_status().json()["default_graph"]
        payload = {
            "name": "Stack acceptance",
            "project_id": project["id"],
            "graph": graph,
        }
        flow = client.post("workflows", json=payload).raise_for_status().json()
        path = "workflows/" + flow["id"]
        try:
            run = scan(base, flow["id"], output)
            rows = json.loads((output / "report.json").read_bytes())["findings"]
            assert len(rows) == run["count"] == 15
            for category in ("SECRET", "SCA", "SAST"):
                assert sum(f["category"] == category for f in rows) == 5
            filtered = (
                client.get("findings", params={"run_id": run["id"], "q": "jsoup"})
                .raise_for_status()
                .json()
            )
            assert len(filtered) == 1 and filtered[0]["category"] == "SCA"
            cursor = run["events"][-2]["id"]
            replay = (
                client.get(
                    "runs/" + run["id"] + "/events",
                    headers={"Last-Event-ID": str(cursor)},
                )
                .raise_for_status()
                .text
            )
            assert replay.count("id: ") == 1 and "event: done" in replay
            graph["nodes"][0].update(
                type="schedule_trigger",
                config={
                    "cron": "* * * * *",
                    "timezone": "Europe/Moscow",
                    "enabled": True,
                },
            )
            scheduled = (
                client.put(path, json={**payload, "revision": flow["revision"]})
                .raise_for_status()
                .json()
            )
            assert scheduled["next_due"] is not None
            deadline = time.monotonic() + 100
            while time.monotonic() < deadline:
                history = (
                    client.get("runs", params={"workflow_id": flow["id"]})
                    .raise_for_status()
                    .json()
                )
                automatic = [
                    r
                    for r in history
                    if r["trigger"] == "schedule" and r["status"] == "success"
                ]
                if automatic:
                    assert len(automatic) == 1 and automatic[0]["count"] == 15
                    print("Scheduled execution:", automatic[0]["id"], flush=True)
                    break
                time.sleep(1)
            else:
                raise TimeoutError("Scheduled execution did not finish")
            graph["nodes"][0]["config"]["enabled"] = False
            result = (
                client.put(path, json={**payload, "revision": scheduled["revision"]})
                .raise_for_status()
                .json()
            )
            assert result["next_due"] is None
        finally:
            client.delete("projects/" + project["id"]).raise_for_status()


if __name__ == "__main__":
    verify()
