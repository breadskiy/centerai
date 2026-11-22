"""Resolve built-in and published scan profiles for manual and GitHub runs."""

from sqlalchemy import select

from .db import Project, Version, Workflow
from .graph import Graph, default_graph, validate

BUILTIN_PROFILES = {
    "full": "Полная проверка",
    "ai": "Полная проверка с AI",
    "sca": "Только зависимости",
    "secrets": "Только секреты",
    "sast": "Только код",
}


class ProfileUnavailable(LookupError):
    pass


def commit_triggered_graph(raw):
    graph = Graph.model_validate(raw).model_dump()
    for node in graph["nodes"]:
        if node["type"] == "schedule_trigger":
            node["config"]["enabled"] = False
    validate(graph)
    return graph


def resolve_scan_profile(db, account_id, profile):
    if profile in BUILTIN_PROFILES:
        title = BUILTIN_PROFILES[profile]
        graph = default_graph(with_ai=profile == "ai")
        if profile in ("sca", "secrets", "sast"):
            scanners = ("sca_scanner", "secrets_scanner", "sast_scanner")
            omitted = set(scanners) - {f"{profile}_scanner"}
            graph["nodes"] = [node for node in graph["nodes"] if node["id"] not in omitted]
            graph["edges"] = [
                edge for edge in graph["edges"]
                if edge["source"] not in omitted and edge["target"] not in omitted
            ]
    else:
        parts = profile.split(":")
        if len(parts) != 2 or len(parts[1]) > 9 or not parts[1].isascii() or not parts[1].isdigit():
            raise ValueError("Выберите профиль проверки")
        snapshot = db.scalar(
            select(Version)
            .join(Workflow, Workflow.id == Version.workflow_id)
            .join(Project, Project.id == Workflow.project_id)
            .where(
                Version.workflow_id == parts[0],
                Version.revision == int(parts[1]),
                Version.published_at.is_not(None),
                Project.owner_id == account_id,
            )
        )
        if snapshot is None:
            raise ProfileUnavailable("Шаблон не опубликован или недоступен")
        title = snapshot.name
        return title, commit_triggered_graph(snapshot.graph)
    validate(graph)
    return title, graph
