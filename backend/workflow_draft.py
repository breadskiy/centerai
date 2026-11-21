import re
from http.client import HTTPException
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai_report import configured_provider
from .graph import validate


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scanners: list[Literal["secrets", "sca", "sast"]] = Field(
        min_length=1, max_length=3
    )
    levels: list[Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]]
    cron: str
    timezone: str
    path_regex: str
    explanations: bool
    notify: list[Literal["telegram"]]
    only_if_findings: bool


def compile_plan(plan):
    nodes, edges = [], []

    def add(kind, x, y=120, config=None, key=None):
        key = key or kind
        nodes.append(
            dict(id=key, type=kind, config=config or {}, position=dict(x=x, y=y))
        )
        return key

    def wire(source, target, branch=""):
        edges.append(dict(source=source, target=target, branch=branch))

    trigger = (
        add(
            "schedule_trigger",
            0,
            config={
                "cron": plan.cron,
                "timezone": plan.timezone or "Europe/Moscow",
                "enabled": False,
            },
        )
        if plan.cron
        else add("manual_trigger", 0)
    )
    source = add("repository_source", 220)
    wire(trigger, source)
    parents = []
    for i, scanner in enumerate(dict.fromkeys(plan.scanners)):
        node = add(scanner + "_scanner", 440, i * 140)
        wire(source, node)
        parents.append(node)
    x = 660
    stages = []
    if plan.path_regex:
        stages.append(("regex_filter", {"pattern": plan.path_regex}))
    if plan.levels:
        stages.append(("severity_filter", {"levels": plan.levels}))
    if plan.explanations:
        stages.append(("ai_analysis", {}))
    if plan.only_if_findings:
        stages.append(("if_else", {"operator": ">", "count": 0}))
    for kind, cfg in stages:
        node = add(kind, x, config=cfg)
        for parent in parents:
            wire(parent, node)
        parents = [node]
        x += 220
    report = add("report_generator", x)
    for parent in parents:
        wire(parent, report, "true" if plan.only_if_findings else "")
    if plan.only_if_findings:
        wire("if_else", add("report_generator", x, 300, key="empty_report"), "false")
    if plan.notify:
        wire(report, add("notification", x + 220))
    graph = {"nodes": nodes, "edges": edges}
    validate(graph)
    return graph


def apply_explicit_filters(plan, description):
    """Preserve unambiguous positive scanner and risk requests in compact-model drafts."""
    text = description.casefold()
    if re.search(r"\b(не|без|кроме|исключ\w*|except|without|not)\b", text):
        return
    matches = {
        "sca": r"\b(?:sca|зависимост\w*|библиотек\w*)\b",
        "secrets": r"\b(?:secrets|секрет\w*|парол\w*|токен\w*)\b",
        "sast": r"\b(?:sast|код(?:а)?|авторизаци\w*)\b",
    }
    requested = [name for name, pattern in matches.items() if re.search(pattern, text)]
    if requested and not re.search(r"все (?:три|анализатор|виды|категории)", text):
        plan.scanners = requested
    if (
        re.search(r"\b(?:critical|критическ\w*)\b", text)
        and not re.search(
            r"\b(?:high|medium|low|info|высок\w*|средн\w*|низк\w*|информационн\w*)\b",
            text,
        )
        and re.search(r"(?:только|оставь|если есть)\s+(?:critical|критическ)", text)
    ):
        plan.levels = ["CRITICAL"]


def draft(description):
    provider = configured_provider()
    messages = [
        {
            "role": "system",
            "content": (
                "Переведи задание пользователя в JSON план. Зависимости, библиотеки, Gradle = sca. "
                "Секреты, пароли и токены = secrets. Статическая проверка кода = sast. "
                "«По будням» и «каждый будний день» означают дни недели 1-5. "
                '«Вручную» означает cron пустой. Единственный канал уведомлений — Telegram. '
                "Use all three only for a general scan. Default levels=[], cron='', timezone='Europe/Moscow', "
                "path_regex='', explanations=false, notify=[], only_if_findings=false. "
                "Use five-field cron only if requested. "
                "Include an explanation stage only when explicitly requested. "
                "Set only_if_findings=true for conditional delivery. Do not invent recipients or actions."
            ),
        },
        {
            "role": "user",
            "content": "Запускай вручную проверку паролей и сделай отчёт.",
        },
        {
            "role": "assistant",
            "content": '{"scanners":["secrets"],"levels":[],"cron":"","timezone":"Europe/Moscow","path_regex":"","explanations":false,"notify":[],"only_if_findings":false}',
        },
        {
            "role": "user",
            "content": "В 10 утра по будням проверь библиотеки. Только если найдены HIGH, отправь в Telegram.",
        },
        {
            "role": "assistant",
            "content": '{"scanners":["sca"],"levels":["HIGH"],"cron":"0 10 * * 1-5","timezone":"Europe/Moscow","path_regex":"","explanations":false,"notify":["telegram"],"only_if_findings":true}',
        },
        {"role": "user", "content": description},
    ]
    for attempt in range(2):
        try:
            plan = Plan.model_validate_json(
                provider.complete(messages, Plan.model_json_schema())
            )
            apply_explicit_filters(plan, description)
            if not re.search(r"\b(?:telegram|телеграм\w*)\b", description, re.I) or re.search(
                r"\b(?:без|не отправляй в)\s+(?:telegram|телеграм\w*)\b", description, re.I
            ):
                plan.notify = []
            if not re.search(r"\b(?:только если|если (?:есть|найден\w*|обнаружен\w*))\b", description, re.I):
                plan.only_if_findings = False
            return compile_plan(plan)
        except (ValueError, TypeError, KeyError, IndexError):
            if attempt:
                raise ValueError(
                    "Модель не сформировала корректный план. Уточните описание."
                ) from None
            messages.append(
                {
                    "role": "user",
                    "content": "Исправь структуру и параметры согласно схеме.",
                }
            )
        except (OSError, HTTPException):
            raise ValueError(
                "Сервис модели недоступен. Проверьте подключение AI."
            ) from None
