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
    "secrets": r"(?:secrets?|секрет\w*|парол\w*|токен\w*)",
    "sca": r"(?:sca|sac|dependenc(?:y|ies)|librar(?:y|ies)|зависимост\w*|библиотек\w*|gradle)",
    "sast": r"(?:sast|static\s+(?:code\s+)?analysis|статическ\w*\s+анализ|авторизаци\w*)",
}
SEVERITY_TERMS = {
    "CRITICAL": r"(?:critical|критическ\w*)",
    "HIGH": r"(?:high|высок\w*)",
    "MEDIUM": r"(?:medium|средн\w*)",
    "LOW": r"(?:low|низк\w*)",
    "INFO": r"(?:info|информационн\w*)",
}

AI_NAME = r"(?:ai|ии|qwen(?:\d+(?:\.\d+)*)?|нейросет\w*|нейронк\w*|искусственн\w*\s+интеллект\w*)"
AI_STAGE = rf"(?:(?:анализ\w*|разбор\w*)\s+(?:(?:с помощью|через|от)\s+)?{AI_NAME}|{AI_NAME}[\s\-‑–—]+(?:анализ\w*|разбор\w*|analysis))"
EMAIL_NAME = r"(?:e[\-‑]?mail|имейл\w*|электронн\w*\s+почт\w*|почт(?:а|у|ой|е|ы)|письм(?:о|ом))"
TELEGRAM_NAME = r"(?:telegram|телегра[м]+\w*|тг)"
DELIVERY_ACTION = r"(?:отправ\w*|отосл\w*|вышл\w*|пришл\w*|присыла\w*|перешл\w*|достав\w*|скин\w*|уведом\w*|send\w*|deliver\w*|notify\w*)"


def channel_excluded(text, channel):
    if re.search(r"\b(?:без\s+(?:уведомлений|рассылки)|without\s+notifications)\b(?!\s+(?:на|по|в|через|via|by)\b)", text, re.I):
        return True
    qualifier = r"(?:(?:отправки|уведомлений|рассылки|отч[её]та|отч[её]т|его|мне|результаты|на|по|в|через|мою)\s+)*"
    negative = rf"\b(?:без|кроме|without|skip|не\s+(?:надо\s+)?{DELIVERY_ACTION}|не\s+добавля\w*)\s+{qualifier}{channel}\b"
    trailing_negative = rf"\b{channel}\s+не\s+(?:нуж\w*|надо|{DELIVERY_ACTION})\b"
    return bool(re.search(negative, text, re.I) or re.search(trailing_negative, text, re.I))


def channel_requested(text, channel):
    return bool(re.search(
        rf"\b(?:(?:{DELIVERY_ACTION}|отч[её]т\w*|результат\w*|report)\b[^.!?\n]{{0,100}}?\b{channel}"
        rf"|(?:на|по|в|через|via|by)\s+(?:(?:мою|свою|мне|мой|электронной|подтвержд[её]нную)\s+)*{channel}"
        rf"|{channel}\s+(?:the\s+)?report)\b"
        rf"|(?:^|[,;+→]|\sи\s)\s*{channel}\s*(?=$|[,;+.!?→])",
        text, re.I,
    ))


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
        r"весь\s+(?:проект|репозиторий|код)|(?:full|complete)\s+(?:(?:project|repository|code)\s+)?scan)\b",
        text,
    )
    negated_full = re.search(
        r"\b(?:не\s+полностью|не\s+(?:делай|запускай)\s+полн\w*|"
        r"not a (?:full|complete)\s+(?:(?:project|repository|code)\s+)?scan)\b",
        text,
    )
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
    notify: list[Literal["telegram"]]
    only_if_findings: bool


def compile_plan(plan, recipient=None):
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
    if recipient is not None:
        wire(
            report,
            add(
                "email_notification",
                x + 220,
                260 if plan.notify else 120,
                config={"recipient": recipient} if recipient else {},
            ),
        )
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
    ai_option = rf"(?:{AI_STAGE}|{AI_NAME})"
    if re.search(
        rf"\b(?:(?:без|without|исключи|пропусти|не\s+(?:добавляй|включай|используй|делай))\s+{ai_option}"
        rf"|{ai_option}\s+не\s+(?:нуж\w*|надо|добавляй)|не\s+(?:объясняй|поясняй)"
        r"|(?:без|without)\s+(?:объясн\w*|поясн\w*|рекомендаци\w*|explanations|recommendations))\b", text
    ):
        plan.explanations = False
    elif re.search(
        rf"\b(?:{AI_STAGE}|(?:с|с помощью|через|with|добавь|включи|используй)\s+{AI_NAME}"
        r"|объясн\w*|поясн\w*|порекомендуй\w*|рекомендаци\w*|explain\w*|recommend\w*)\b"
        rf"|(?:^|[,;+→]|\sи\s)\s*{AI_NAME}\s*(?=$|[,;+.!?→]|\sи\s)",
        text,
    ):
        plan.explanations = True
    elif not re.search(rf"\b(?:объясн\w*|поясн\w*|порекоменд\w*|рекомендац\w*|explain\w*|recommend\w*|{AI_NAME})\b", text):
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
    elif not re.search(
        r"\b(?:расписан\w*|cron|по будням|по выходным|кажд\w*|ежеднев\w*|еженедел\w*|"
        r"ежемесяч\w*|weekdays|weekends|daily|weekly|monthly|every|schedule\w*|"
        r"понедельник\w*|вторник\w*|сред[ауеы]|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)\b",
        text,
    ):
        plan.cron = ""


def draft_email_recipient(description, account_email, report_email):
    if channel_excluded(description, EMAIL_NAME) or re.search(
        rf"\bне\s+{DELIVERY_ACTION}\b[^,;.!?\n]{{0,45}}@", description, re.I
    ):
        return None
    targets = {
        match["address"].rstrip(".").casefold()
        for match in ADDRESS_TARGET.finditer(description)
    }
    email_requested = channel_requested(ADDRESS_TEXT.sub("", description), EMAIL_NAME) or re.search(
        r"\bsend\w* .{0,60}\binbox\b", description, re.I
    )
    explicit_delivery = targets and re.search(
        rf"\b{DELIVERY_ACTION}\b",
        description,
        re.I,
    )
    if not (email_requested or explicit_delivery):
        return None
    addresses = {
        value.rstrip(".").casefold() for value in ADDRESS_TEXT.findall(description)
    }
    if len(targets) > 1 or (targets and len(addresses) > 1):
        raise ValueError("Укажите одного получателя отчёта.")
    if targets:
        try:
            recipient = EmailConfig(recipient=next(iter(targets))).recipient
        except ValidationError:
            raise ValueError("Укажите корректный email получателя.") from None
        if recipient not in (account_email, report_email):
            raise ValueError(
                "Подтвердите адрес для отчётов в личном кабинете."
            )
        return recipient
    if addresses:
        raise ValueError("Укажите адрес в формате «отправь отчёт на user@example.com».")
    return ""


def draft(description, *, account_email=None, report_email=None, telegram_enabled=False, smtp_configured=True):
    recipient = draft_email_recipient(description, account_email, report_email)
    try:
        provider = configured_provider()
    except ValueError:
        raise ValueError(
            "Сервис модели недоступен. Проверьте подключение AI."
        ) from None
    model_description = ADDRESS_TEXT.sub("[email address]", description)
    messages = [
        {
            "role": "system",
            "content": (
                "Переведи задание пользователя в JSON план. Зависимости, библиотеки, Gradle = sca. "
                "Секреты, пароли и токены = secrets. Статическая проверка кода = sast. "
                "«По будням» и «каждый будний день» означают дни недели 1-5. "
                "«Вручную» означает cron пустой. В поле notify указывай только Telegram, email обрабатывается отдельно. "
                "Use all three for a full project scan or an explicit request for all three. "
                "Read every clause and include each requested scanner, filter and condition. "
                "Do not add SAST merely because code is mentioned as the source for another scan. Default levels=[], cron='', timezone='Europe/Moscow', "
                "path_regex='', explanations=false, notify=[], only_if_findings=false. "
                "Use five-field cron only if requested. "
                "Requests for AI analysis, Qwen review or recommendations mean explanations=true. "
                "This stage follows the requested scanners and never replaces them. "
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
            telegram = channel_requested(model_description, TELEGRAM_NAME) and not channel_excluded(model_description, TELEGRAM_NAME)
            plan.notify = ["telegram"] if telegram else []
            warnings = []
            if recipient is not None and not smtp_configured:
                warnings.append("Почтовый сервер не настроен.")
            if recipient == "" and not account_email:
                warnings.append("Подтвердите почту аккаунта в личном кабинете для отправки отчёта.")
            if plan.notify and not telegram_enabled:
                warnings.append("Подключите Telegram для доставки отчёта.")
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
