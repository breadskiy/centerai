"""Executable configuration contracts shared by graph validation and the palette."""

from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import regex
from croniter import croniter
from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmptyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AIConfig(EmptyConfig):
    model: str = Field(default="", max_length=160)


class EmailConfig(EmptyConfig):
    recipient: str = Field(default="", max_length=254)

    @field_validator("recipient")
    @classmethod
    def valid_recipient(cls, value):
        if not value:
            return ""
        try:
            return validate_email(
                value, check_deliverability=False, allow_smtputf8=False
            ).normalized.lower()
        except EmailNotValidError:
            raise ValueError("Укажите корректный email получателя.") from None


class CompareConfig(EmptyConfig):
    operator: Literal[">", ">=", "==", "<", "<="]
    count: int = Field(ge=0)


class LevelsConfig(EmptyConfig):
    levels: list[Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]] = Field(
        min_length=1, max_length=5
    )


class PatternConfig(EmptyConfig):
    pattern: str = Field(min_length=1, max_length=200)

    @field_validator("pattern")
    @classmethod
    def valid_regex(cls, pattern):
        try:
            regex.compile(pattern)
        except regex.error:
            raise ValueError("Некорректное регулярное выражение") from None
        return pattern


class ScheduleConfig(EmptyConfig):
    cron: str = Field(max_length=120)
    timezone: str = Field(max_length=100)
    enabled: bool

    @field_validator("cron")
    @classmethod
    def valid_cron(cls, value):
        if len(value.split()) != 5 or not croniter.is_valid(value):
            raise ValueError("Ожидается cron из пяти полей")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Неизвестный часовой пояс") from None
        return value
