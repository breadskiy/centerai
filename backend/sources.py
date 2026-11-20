"""Normalize bounded project snapshots in memory. Archive member paths never reach the filesystem."""

import io
import os
import re
import stat
import zipfile
from pathlib import PurePosixPath

import httpx

MAX_UPLOAD = 24 * 1024 * 1024
MAX_TOTAL = 48 * 1024 * 1024
MAX_FILE = 512 * 1024
SUFFIXES = {
    ".kt",
    ".kts",
    ".yaml",
    ".yml",
    ".properties",
    ".toml",
    ".lockfile",
    ".pem",
    ".key",
    ".env",
}
SKIP = {
    ".git",
    ".gradle",
    ".idea",
    "build",
    "node_modules",
    "ground-truth",
    "vulnerability-database",
}


def unpack(blob: bytes):
    if len(blob) > MAX_UPLOAD:
        raise ValueError("ZIP превышает 24 МБ")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            if len(entries) > 4000 or sum(e.file_size for e in entries) > MAX_TOTAL:
                raise ValueError("Превышен лимит объёма или числа файлов")
            files = {}
            for entry in entries:
                name = entry.orig_filename
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or any(c in name for c in "\\:\0")
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.flag_bits & 1
                ):
                    raise ValueError("Недопустимая запись в ZIP")
                if entry.is_dir() or SKIP.intersection(path.parts):
                    continue
                if path.suffix not in SUFFIXES and path.name != ".env":
                    continue
                if entry.file_size > MAX_FILE or str(path) in files:
                    raise ValueError("Слишком большой или дублирующийся исходный файл")
                files[str(path)] = archive.read(entry).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeError, NotImplementedError, RuntimeError) as exc:
        raise ValueError("Ожидается исправный ZIP с исходниками в UTF-8") from exc
    roots = [
        PurePosixPath(p).parent
        for p in files
        if PurePosixPath(p).name == "settings.gradle.kts"
    ]
    if not roots:
        roots = [
            PurePosixPath(p).parent
            for p in files
            if PurePosixPath(p).name == "build.gradle.kts"
        ]
    if not roots:
        raise ValueError("В архиве отсутствует проект Gradle Kotlin DSL")
    root = min(roots, key=lambda p: (len(p.parts), str(p)))
    return {
        str(PurePosixPath(p).relative_to(root)): value
        for p, value in files.items()
        if PurePosixPath(p).is_relative_to(root)
    }


def fetch_repository(url):
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", url
    )
    allowed = {
        s.strip().lower()
        for s in os.getenv("ALLOWED_REPOSITORIES", "TBagirov/training").split(",")
    }
    if not match or "/".join(match.groups()).lower() not in allowed:
        raise ValueError("Выберите GitHub-репозиторий из серверного списка разрешённых")
    owner, repo = match.groups()
    try:
        with httpx.stream(
            "GET",
            f"https://codeload.github.com/{owner}/{repo}/zip/HEAD",
            timeout=25,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes(65536):
                content.extend(chunk)
                if len(content) > MAX_UPLOAD:
                    raise ValueError("Архив репозитория превышает 24 МБ")
    except httpx.HTTPError as exc:
        raise ValueError("Не удалось загрузить архив с GitHub") from exc
    return unpack(bytes(content))
