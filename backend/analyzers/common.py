import hashlib
import json
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Entry(BaseModel):
    path: Text
    severity: Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
    description: Text
    remediation: Text

    @field_validator("path")
    @classmethod
    def relative_path(cls, value):
        if (
            PurePosixPath(value).is_absolute()
            or ":" in value
            or "\\" in value
            or ".." in value.split("/")
        ):
            raise ValueError("Ожидается относительный путь проекта")
        return value


class Located(Entry):
    category: Literal["SECRET", "SAST"]
    kind: Text = Field(alias="class")
    line: int = Field(strict=True, ge=1)
    endLine: int | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def range_valid(self):
        if self.endLine is not None and not self.line <= self.endLine <= self.line + 14:
            raise ValueError("Недопустимый диапазон строк")
        return self


class Dependency(Entry):
    category: Literal["SCA"]
    group: Text
    artifact: Text
    version: Text
    advisoryId: Text


class SubmissionReportExporter:
    @staticmethod
    def export(findings):
        rows = []
        for finding in findings:
            schema = Dependency if finding["category"] == "SCA" else Located
            rows.append(
                schema.model_validate(finding).model_dump(
                    by_alias=True, exclude_none=True
                )
            )
        return {"findings": rows}


def finding(
    category,
    path,
    kind,
    severity,
    title,
    description,
    remediation,
    evidence,
    **location,
):
    row = {
        "category": category,
        "path": path,
        "class": kind,
        "severity": severity,
        "title": title,
        "description": description,
        "remediation": remediation,
        "evidence": evidence,
        "rule_id": f"{category}/{kind}",
        **location,
    }
    identity = [category, path, kind, location]
    row["id"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True).encode()
    ).hexdigest()[:24]
    return row


def line_at(source, offset):
    return source.count("\n", 0, offset) + 1
