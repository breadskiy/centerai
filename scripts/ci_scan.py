"""Run a CenterAI workflow in CI, export both reports and optionally gate the build."""

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def scan(base, workflow, directory, archive=None, timeout=180, fail_on=None):
    use_proxy = urlsplit(base).hostname not in ("127.0.0.1", "localhost", "::1")
    with httpx.Client(
        base_url=base.rstrip("/") + "/api/v1/", timeout=35, trust_env=use_proxy
    ) as client:
        if archive:
            original = client.get(f"workflows/{workflow}").raise_for_status().json()
            with archive.open("rb") as file:
                project = (
                    client.post(
                        "projects",
                        data={"name": archive.stem[:100]},
                        files={"archive": (archive.name, file, "application/zip")},
                    )
                    .raise_for_status()
                    .json()
                )
            graph = original["graph"]
            # A CI copy is initiated by the runner, never arm its source schedule.
            for node in graph["nodes"]:
                if node["type"] == "schedule_trigger":
                    node["config"]["enabled"] = False
            workflow = (
                client.post(
                    "workflows",
                    json={
                        "project_id": project["id"],
                        "graph": graph,
                        "name": original["name"],
                        "description": original["description"],
                    },
                )
                .raise_for_status()
                .json()["id"]
            )
        run = client.post(f"workflows/{workflow}/runs").raise_for_status().json()
        path = "runs/" + run["id"]
        deadline = time.monotonic() + timeout
        while run["status"] in ("queued", "running"):
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for " + path)
            time.sleep(0.5)
            run = client.get(path).raise_for_status().json()
        directory.mkdir(exist_ok=True, parents=True)
        for fmt in ("json", "txt"):
            data = (
                client.get(path + "/report", params={"format": fmt})
                .raise_for_status()
                .content
            )
            (directory / ("report." + fmt)).write_bytes(data)
        print(f"{path} {run['status']} ({run['count']} findings)")
        if run["status"] != "success":
            raise RuntimeError(run.get("error") or run["status"])
        if fail_on:
            ranks = ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
            findings = json.loads((directory / "report.json").read_bytes())["findings"]
            if any(
                ranks.index(f["severity"]) >= ranks.index(fail_on) for f in findings
            ):
                raise RuntimeError("Severity threshold reached: " + fail_on)
        return run


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--fail-on", choices=["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    )
    args = parser.parse_args()
    scan(args.url, args.workflow, args.output, args.archive, args.timeout, args.fail_on)
