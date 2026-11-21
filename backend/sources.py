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
    return project_files(files)


def unpack_archive(blob, filename):
    name = filename.lower()
    if name.endswith(".zip"):
        return unpack(blob)
    if len(blob) > MAX_UPLOAD:
        raise ValueError("Архив превышает 24 МБ")
    formats = {
        ".rar": "all",
        ".7z": "7zip",
        ".tar": "tar",
        ".tar.gz": "tar",
        ".tgz": "tar",
    }
    format_name = next(
        (fmt for ext, fmt in formats.items() if name.endswith(ext)), None
    )
    if not format_name:
        raise ValueError("Выберите ZIP, RAR, 7Z, TAR, TAR.GZ или TGZ")
    if os.name == "nt" and "LIBARCHIVE" not in os.environ:
        os.environ["LIBARCHIVE"] = os.path.join(
            os.environ["SystemRoot"], "System32", "archiveint.dll"
        )
    try:
        from libarchive import memory_reader
        from libarchive.exception import ArchiveError
    except (ImportError, OSError):
        raise ValueError(
            "Для этого формата нужна системная библиотека libarchive"
        ) from None
    if name.endswith(".rar") and not blob.startswith(b"Rar!\x1a\x07"):
        raise ValueError("Файл не является архивом RAR")
    files, total = {}, 0
    try:
        with memory_reader(
            blob, format_name, "gzip" if name.endswith((".tar.gz", ".tgz")) else "none"
        ) as archive:
            for index, entry in enumerate(archive, 1):
                path = PurePosixPath(entry.pathname)
                total += entry.size or 0
                if index > 4000 or total > MAX_TOTAL:
                    raise ValueError("Превышен лимит объёма или числа файлов")
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or any(c in entry.pathname for c in "\\:\0")
                    or not (entry.isdir or entry.isreg)
                    or entry.linkpath
                ):
                    raise ValueError("Недопустимая запись в архиве")
                if entry.isdir:
                    continue
                selected = not SKIP.intersection(path.parts) and (
                    path.suffix in SUFFIXES or path.name == ".env"
                )
                size = 0
                content = bytearray()
                for block in entry.get_blocks():
                    size += len(block)
                    if size > (entry.size or 0) or (selected and size > MAX_FILE):
                        raise ValueError("Превышен лимит распакованного файла")
                    if selected:
                        content.extend(block)
                if selected:
                    if str(path) in files:
                        raise ValueError("Дублирующийся исходный файл")
                    files[str(path)] = content.decode("utf-8-sig")
    except (ArchiveError, UnicodeError, TypeError) as exc:
        raise ValueError(
            "Проверьте формат архива, кодировку UTF-8 и отсутствие пароля"
        ) from exc
    return project_files(files)


def project_files(files):
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


def fetch_repository(url, *, public=False):
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", url
    )
    allowed = {
        s.strip().lower()
        for s in os.getenv("ALLOWED_REPOSITORIES", "TBagirov/training").split(",")
    }
    if not match:
        raise ValueError("Введите ссылку вида https://github.com/владелец/репозиторий")
    if not public and "/".join(match.groups()).lower() not in allowed:
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
