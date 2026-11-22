import re
from http.client import HTTPException
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .ai_report import configured_provider
from .graph import validate
from .node_config import EmailConfig

ADDRESS_TEXT = re.compile(r"[^\s<>(),;:\"“”«»]+@[^\s<>(),;:\"“”«»]*")
MAIL_DESTINATION = r"(?:(?:мою|свою|подтвержд[её]нную|электронную)\s+)*почту"
ADDRESS_TARGET = re.compile(
    rf"\b(?:на|to)\s+(?:(?:{MAIL_DESTINATION}|e-?mail|адрес|address)\s*:?\s*)?"
    r"[\"<«]?(?P<address>[^\s<>(),;:\"“”«»]+@[^\s<>(),;:\"“”«»]*)",
    re.I,
)
SCANNER_TERMS = {
    "secrets": r"(?:secrets|секрет\w*|парол\w*|токен\w*)",
    "sca": r"(?:sca|зависимост\w*|библиотек\w*|gradle)",
    "sast": r"(?:sast|статическ\w*\s+анализ|авторизаци\w*)",
}
SEVERITY_TERMS = {
    "CRITICAL": r"(?:critical|критическ\w*)",
    "HIGH": r"(?:high|высок\w*)",
    "MEDIUM": r"(?:medium|средн\w*)",
    "LOW": r"(?:low|низк\w*)",
    "INFO": r"(?:info|информационн\w*)",
}


def apply_scanner_request(plan, text):
    excluded = set()
    for scanner, term in SCANNER_TERMS.items():
        negative = (
            rf"\b(?:без|кроме|исключи\w*|пропусти\w*|"
            rf"не(?:\s+(?:проверяй|добавляй|используй|запускай))?|without|except|skip)\s+{term}\b"
        )
        if re.search(negative, text):
            excluded.add(scanner)
            text = re.sub(negative, "", text)

    requested = [scanner for scanner, term in SCANNER_TERMS.items() if re.search(rf"\b{term}\b", text)]
    all_scanners = re.search(
        r"\b(?:все (?:три|анализатор\w*|виды|категории|проверки)|all (?:three|scanners))\b",
        text,
    )
    full_scan = re.search(
        r"\b(?:полность(?:ю)?|полн\w*\s+проверк\w*|комплексн\w*\s+проверк\w*|"
        r"весь\s+(?:проект|репозиторий|код)|full\s+scan|complete\s+scan)\b",
        text,
    )
    negated_full = re.search(r"\b(?:не\s+полностью|не\s+(?:делай|запускай)\s+полн\w*|not a full scan)\b", text)
    if (all_scanners or (full_scan and not requested)) and not negated_full:
        candidates = list(SCANNER_TERMS)
    else:
        candidates = requested or plan.scanners
    plan.scanners = [scanner for scanner in dict.fromkeys(candidates) if scanner not in excluded]
    if not plan.scanners and excluded:
        plan.scanners = [scanner for scanner in SCANNER_TERMS if scanner not in excluded]


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
    levels = [level for level, term in SEVERITY_TERMS.items() if re.search(rf"\b{term}\b", text)]
    severity_context = re.search(r"\b(?:только|если|покаж\w*|остав\w*|фильтр\w*|находк\w*|критичност\w*|severity|findings|only|filter)\b", text)
    excluded_level = re.search(r"\b(?:кроме|без|исключи\w*|except|without)\s+(?:" + "|".join(SEVERITY_TERMS.values()) + r")\b", text)
    if levels and severity_context and not excluded_level:
        plan.levels = levels
    elif not re.search(r"\b(?:критичност\w*|серь[её]зност\w*|важн\w*|severity)\b", text) and not levels:
        plan.levels = []
    if not re.search(r"\b(?:regex|regexp|path|files?|folder\w*|director\w*|пут\w*|файл\w*|папк\w*|каталог\w*)\b|\w/\w|\.(?:kt|kts|java)\b", text):
        plan.path_regex = ""
    ai = r"(?:ai|ии|нейросет\w*|нейронк\w*|искусственн\w*\s+интеллект\w*)"
    if re.search(rf"\b(?:без\s+{ai}|without\s+ai|не\s+(?:объясняй|поясняй))\b", text):
        plan.explanations = False
    elif re.search(
        rf"\b(?:с\s+(?:помощью\s+)?{ai}|with\s+ai|(?:ai|ии)[-\s]+анализ\w*|"
        r"объясни\w*|поясни\w*|порекомендуй\w*|explain|recommend)\b",
        text,
    ):
        plan.explanations = True
    elif not re.search(rf"\b(?:объясн\w*|поясн\w*|порекоменд\w*|рекомендац\w*|explain\w*|recommend\w*|{ai})\b", text):
        plan.explanations = False
    apply_scanner_request(plan, text)


def apply_explicit_schedule(plan, description):
    text = description.casefold()
    if re.search(r"\b(?:вручную|manual(?:ly)?|без расписания)\b", text):
        plan.cron = ""
        return
    weekdays = re.search(r"\b(?:по будням|каждый будний день|weekdays)\b", text)
    daily = re.search(r"\b(?:каждый день|ежедневно|every day|daily)\b", text)
    times = re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text)
    if not times:
        times = [
            (int(hour) % 12 + (12 if period in {"дня", "вечера"} else 0), 0)
            for hour, period in re.findall(r"\bв\s+(1[0-2]|[1-9])\s+(утра|дня|вечера|ночи)\b", text)
        ]
    if (weekdays or daily) and len(times) == 1 and not re.search(
        r"\bне\s+(?:каждый день|ежедневно|по будням)", text
    ):
        hour, minute = (int(part) for part in times[0])
        plan.cron = f"{minute} {hour} * * {'1-5' if weekdays else '*'}"


def draft(description, *, account_email=None, report_email=None, telegram_enabled=False):
    provider = configured_provider()
    model_description = ADDRESS_TEXT.sub("[email address]", description)
    messages = [
        {
            "role": "system",
            "content": (
                "Переведи задание пользователя в JSON план. Зависимости, библиотеки, Gradle = sca. "
                "Секреты, пароли и токены = secrets. Статическая проверка кода = sast. "
                "«По будням» и «каждый будний день» означают дни недели 1-5. "
                '«Вручную» означает cron пустой. Каналы уведомлений: Telegram и email. '
                "Do not add SAST merely because the code is mentioned as the source for another scan. "
                "Use all three for a full project scan or an explicit request for all three. "
                "Read every clause and include each requested scanner, filter, condition, and delivery channel. "
                "Default levels=[], cron='', timezone='Europe/Moscow', "
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
        {"role": "user", "content": model_description},
    ]
    for attempt in range(2):
        try:
            plan = Plan.model_validate_json(
                provider.complete(messages, Plan.model_json_schema())
            )
            apply_explicit_filters(plan, model_description)
            apply_explicit_schedule(plan, model_description)
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
                rf"\b(?:на\s+{MAIL_DESTINATION}|"
                r"по (?:электронной )?почте|на e-?mail|"
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
            plan.only_if_findings = bool(re.search(
                r"\b(?:если\s+(?:есть|найд\w*|обнаруж\w*|будут?\s+находк\w*)|"
                r"при\s+наличии\s+находок|only\s+if\s+(?:there\s+are\s+)?findings)\b",
                model_description,
                re.I,
            ))
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
