import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from graphlib import CycleError, TopologicalSorter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import regex
from croniter import croniter
from pydantic import BaseModel, Field, ConfigDict

from .analyzers import SCANNERS
from .analyzers.common import SubmissionReportExporter
from .notifications import telegram

LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
OPS = {">": operator.gt, ">=": operator.ge, "==": operator.eq, "<": operator.lt, "<=": operator.le}


class Position(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float = 0
    y: float = 0


class Node(BaseModel):
    id: str = Field(pattern=r"^[\w-]{1,80}$")
    type: str = Field(max_length=40)
    config: dict = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)


class Edge(BaseModel):
    source: str
    target: str
    branch: str = ""


class Graph(BaseModel):
    nodes: list[Node] = Field(max_length=80)
    edges: list[Edge] = Field(max_length=200)


@dataclass(frozen=True)
class Kind:
    title: str
    category: str
    description: str
    input: str
    output: str
    execute: object
    defaults: dict = field(default_factory=dict)


@dataclass
class Packet:
    findings: dict = field(default_factory=dict)
    branch: str = ""


@dataclass
class Context:
    session: object
    run: object
    files: dict


def pass_through(ctx, cfg, data):
    return data


def scanner(key):
    def analyze(ctx, cfg, data):
        found = {f["id"]: f for f in SCANNERS[key](ctx.files)}
        return Packet({**data.findings, **found})
    return analyze


def compare(ctx, cfg, data):
    matched = OPS[cfg["operator"]](len(data.findings), cfg["count"])
    return Packet(data.findings, "true" if matched else "false")


def severity(ctx, cfg, data):
    return Packet({i: f for i, f in data.findings.items() if f["severity"] in cfg["levels"]})


def match_regex(ctx, cfg, data):
    pattern = regex.compile(cfg["pattern"])
    return Packet({i: f for i, f in data.findings.items() if pattern.search(f["path"], timeout=.03)})


def report(ctx, cfg, data):
    SubmissionReportExporter.export(data.findings.values())
    return data


def notify(ctx, cfg, data):
    telegram(ctx.session, ctx.run, len(data.findings))
    return data


REGISTRY = {
    "manual_trigger": Kind("Ручной запуск", "Триггеры", "Запуск по команде оператора.", "—", "start", pass_through),
    "schedule_trigger": Kind("Расписание", "Триггеры", "Календарный запуск в заданной зоне.", "—", "start", pass_through,
                             {"cron": "0 9 * * 1-5", "timezone": "Europe/Moscow", "enabled": False}),
    "repository_source": Kind("Исходники", "Источник", "Снимок файлов проекта.", "start", "files", pass_through),
    "secrets_scanner": Kind("Secrets", "Анализаторы", "Поиск встроенных учётных данных.", "files", "findings", scanner("secrets_scanner")),
    "sca_scanner": Kind("SCA", "Анализаторы", "Проверка версий зависимостей Gradle.", "files", "findings", scanner("sca_scanner")),
    "sast_scanner": Kind("SAST", "Анализаторы", "Статический анализ структуры Kotlin.", "files", "findings", scanner("sast_scanner")),
    "if_else": Kind("IF / ELSE", "Логика", "Сравнение числа находок с порогом.", "findings", "findings", compare, {"operator": ">", "count": 0}),
    "severity_filter": Kind("Критичность", "Логика", "Отбор по уровням риска.", "findings", "findings", severity, {"levels": ["CRITICAL", "HIGH"]}),
    "regex_filter": Kind("Regex", "Логика", "Отбор по пути к файлу.", "findings", "findings", match_regex, {"pattern": ".*"}),
    "report_generator": Kind("Отчёт", "Вывод", "Валидация и объединение находок.", "findings", "report", report),
    "notification": Kind("Telegram", "Вывод", "Отправка краткого отчёта.", "report", "receipt", notify),
}


def next_due(cfg, now):
    base = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(cfg["timezone"]))
    return croniter(cfg["cron"], base).get_next(datetime).timestamp()


def validate_config(node):
    cfg = node.config
    try:
        if node.type == "if_else":
            assert cfg["operator"] in OPS and type(cfg["count"]) is int and cfg["count"] >= 0
        elif node.type == "severity_filter":
            assert isinstance(cfg["levels"], list) and cfg["levels"] and all(v in LEVELS for v in cfg["levels"])
        elif node.type == "regex_filter":
            assert isinstance(cfg["pattern"], str) and 0 < len(cfg["pattern"]) <= 200
            regex.compile(cfg["pattern"])
        elif node.type == "schedule_trigger":
            assert type(cfg["enabled"]) is bool and len(cfg["cron"].split()) == 5 and croniter.is_valid(cfg["cron"])
            next_due(cfg, 1700000000)
        return
    except (AssertionError, KeyError, TypeError, ValueError, AttributeError, ZoneInfoNotFoundError, regex.error):
        raise ValueError(f"Проверьте параметры узла {node.id}") from None


def validate(raw):
    graph = Graph.model_validate(raw)
    nodes = {n.id: n for n in graph.nodes}
    if not nodes or len(nodes) != len(graph.nodes):
        raise ValueError("Добавьте узлы с уникальными идентификаторами")
    if sum(n.type in ("manual_trigger", "schedule_trigger") for n in nodes.values()) != 1:
        raise ValueError("Граф должен содержать ровно один триггер")
    if not any(n.type == "report_generator" for n in nodes.values()):
        raise ValueError("Добавьте узел отчёта")
    for node in nodes.values():
        if node.type not in REGISTRY:
            raise ValueError("Неизвестный тип узла")
        validate_config(node)
    parents = {n: [] for n in nodes}
    for e in graph.edges:
        if e.source not in nodes or e.target not in nodes or e in parents[e.target]:
            raise ValueError("Проверьте концы и уникальность соединений")
        src, dst = nodes[e.source], nodes[e.target]
        if e.branch not in (("true", "false") if src.type == "if_else" else ("",)):
            raise ValueError("Выберите выход Да или Нет узла IF / ELSE")
        output, required = REGISTRY[src.type].output, REGISTRY[dst.type].input
        if output != required and not (src.type in SCANNERS and dst.type in SCANNERS):
            raise ValueError(f"Несовместимые порты: {src.id} → {dst.id}")
        parents[e.target].append(e)
    for n in nodes.values():
        if not parents[n.id] and REGISTRY[n.type].input != "—":
            raise ValueError(f"Подключите вход узла {n.id}")
    try:
        order = list(TopologicalSorter({i: [e.source for e in links] for i, links in parents.items()}).static_order())
    except CycleError:
        raise ValueError("Циклические соединения запрещены") from None
    return nodes, parents, order


def default_graph():
    layout = [("manual_trigger", 0, 125), ("repository_source", 220, 125),
              ("secrets_scanner", 440, 0), ("sca_scanner", 440, 125), ("sast_scanner", 440, 250),
              ("report_generator", 680, 125)]
    pairs = [(0, 1), (1, 2), (1, 3), (1, 4), (2, 5), (3, 5), (4, 5)]
    return {"nodes": [{"id": k, "type": k, "config": {}, "position": {"x": x, "y": y}} for k, x, y in layout],
            "edges": [{"source": layout[a][0], "target": layout[b][0], "branch": ""} for a, b in pairs]}
