import re
from http.client import HTTPException
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .ai_report import configured_provider
from .graph import validate
from .node_config import EmailConfig

ADDRESS_TEXT = re.compile(r"[^\s<>(),;:\"“”«»]+@[^\s<>(),;:\"“”«»]*")
ADDRESS_TARGET = re.compile(
    r"\b(?:на|to)\s+(?:(?:(?:электронную\s+)?почту|e-?mail|адрес|address)\s*:?\s*)?"
    r"[\"<«]?(?P<address>[^\s<>(),;:\"“”«»]+@[^\s<>(),;:\"“”«»]*)",
    re.I,
)


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
    notify: list[Literal["telegram", "email"]]
    only_if_findings: bool


def compile_plan(plan, recipient=""):
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
    if "telegram" in plan.notify:
        wire(report, add("notification", x + 220))
    if "email" in plan.notify:
        wire(report, add(
            "email_notification", x + 220,
            260 if "telegram" in plan.notify else 120,
            config={"recipient": recipient} if recipient else {},
        ))
    graph = {"nodes": nodes, "edges": edges}
    validate(graph)
    return graph


def apply_explicit_filters(plan, description):
    """Preserve unambiguous positive scanner and risk requests in compact-model drafts."""
    text = description.casefold()
    if not re.search(
        r"\b(?:critical|high|medium|low|info|severity|критическ\w*|высок\w*|"
        r"средн\w*|низк\w*|информационн\w*|критичност\w*|серьёзност\w*|серьезност\w*|важн\w*)\b",
        text,
    ):
        plan.levels = []
    if not re.search(r"\b(?:regex|regexp|path|files?|folder\w*|director\w*|пут\w*|файл\w*|папк\w*|каталог\w*)\b|\w/\w|\.(?:kt|kts|java)\b", text):
        plan.path_regex = ""
    if not re.search(r"\b(?:объясн\w*|поясн\w*|порекоменд\w*|рекомендац\w*|explain\w*|recommend\w*|ai|ии)\b", text):
        plan.explanations = False
    if re.search(r"\b(не|без|кроме|исключ\w*|except|without|not)\b", text):
        return
    matches = {
        "sca": r"\b(?:sca|зависимост\w*|библиотек\w*)\b",
        "secrets": r"\b(?:secrets|секрет\w*|парол\w*|токен\w*)\b",
        "sast": r"\b(?:sast|статическ\w*\s+анализ|авторизаци\w*)\b",
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


def apply_explicit_schedule(plan, description):
    text = description.casefold()
    if re.search(r"\b(?:вручную|manual(?:ly)?|без расписания)\b", text):
        plan.cron = ""
        return
    weekdays = re.search(r"\b(?:по будням|каждый будний день|weekdays)\b", text)
    daily = re.search(r"\b(?:каждый день|ежедневно|every day|daily)\b", text)
    times = re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if (weekdays or daily) and len(times) == 1 and not re.search(
        r"\bне\s+(?:каждый день|ежедневно|по будням)", text
    ):
        hour, minute = (int(part) for part in times[0])
        plan.cron = f"{minute} {hour} * * {'1-5' if weekdays else '*'}"


def draft(description, *, account_email=None, report_email=None, telegram_enabled=False):
    provider = configured_provider()
    messages = [
        {
            "role": "system",
            "content": (
                "Переведи задание пользователя в JSON план. Зависимости, библиотеки, Gradle = sca. "
                "Секреты, пароли и токены = secrets. Статическая проверка кода = sast. "
                "«По будням» и «каждый будний день» означают дни недели 1-5. "
                '«Вручную» означает cron пустой. Каналы уведомлений: Telegram и email. '
                "Do not add SAST merely because the code is mentioned as the source for another scan. "
                "Use all three only for a general scan. Default levels=[], cron='', timezone='Europe/Moscow', "
                "path_regex='', explanations=false, notify=[], only_if_findings=false. "
                "Use five-field cron only if requested. "
                "Include filters and explanation stages only when explicitly requested. "
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
        {"role": "user", "content": ADDRESS_TEXT.sub("[email address]", description)},
    ]
    for attempt in range(2):
        try:
            plan = Plan.model_validate_json(
                provider.complete(messages, Plan.model_json_schema())
            )
            apply_explicit_filters(plan, description)
            apply_explicit_schedule(plan, description)
            warnings = []
            plan.notify = []
            no_delivery = re.search(r"\bбез (?:уведомлен\w*|рассылк\w*)\b", description, re.I)
            telegram_requested = re.search(r"\b(?:telegram|телеграм\w*)\b", description, re.I)
            telegram_excluded = re.search(
                r"\b(?:без|не отправляй в)\s+(?:telegram|телеграм\w*)\b", description, re.I
            )
            if telegram_requested and not (telegram_excluded or no_delivery):
                plan.notify.append("telegram")
                if not telegram_enabled:
                    warnings.append("Подключите Telegram в настройках для доставки отчёта.")
            targets = {
                match["address"].rstrip(".").casefold()
                for match in ADDRESS_TARGET.finditer(description)
            }
            email_requested = re.search(
                r"\b(?:на (?:электронную )?почту|по (?:электронной )?почте|на e-?mail|"
                r"send\w* .{0,60}\b(?:e-?mail|inbox)|e-?mail (?:the )?report)\b",
                description, re.I,
            )
            email_excluded = re.search(
                r"\b(?:без (?:почты|e-?mail)|не отправляй[^.!?]{0,45}(?:почт|e-?mail))",
                description, re.I,
            )
            recipient = ""
            explicit_delivery = targets and re.search(
                r"\b(?:отправ\w*|пришл\w*|присыл\w*|уведом\w*|send\w*|deliver\w*)\b",
                description, re.I,
            )
            if (email_requested or explicit_delivery) and not (email_excluded or no_delivery):
                mentioned_addresses = {address.rstrip(".").casefold() for address in ADDRESS_TEXT.findall(description)}
                if len(targets) > 1 or (targets and len(mentioned_addresses) > 1):
                    warnings.append("В промпте указан не один адрес. Укажите одного получателя отчёта.")
                elif targets:
                    try:
                        target = EmailConfig(recipient=next(iter(targets))).recipient
                    except ValidationError:
                        warnings.append("Укажите корректный email получателя.")
                    else:
                        if target in (account_email, report_email):
                            recipient = target
                            plan.notify.append("email")
                        else:
                            warnings.append("Адрес из промпта не подтверждён или почта не настроена. Проверьте раздел «Отчёты по почте» в личном кабинете.")
                elif mentioned_addresses:
                    warnings.append("Для отправки укажите адрес в формате «отправь отчёт на user@example.com».")
                elif account_email:
                    plan.notify.append("email")
                else:
                    warnings.append("Почта не настроена для этого аккаунта. Отчёт будет доступен в CenterAI.")
            if not re.search(r"\b(?:только если|если (?:есть|найден\w*|обнаружен\w*))\b", description, re.I):
                plan.only_if_findings = False
            return {**compile_plan(plan, recipient), "warnings": warnings}
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
