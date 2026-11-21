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
        raise ValueError("ZIP РїСЂРµРІС‹С€Р°РµС‚ 24 РњР‘")
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            entries = archive.infolist()
            if len(entries) > 4000 or sum(e.file_size for e in entries) > MAX_TOTAL:
                raise ValueError(
                    "РџСЂРµРІС‹С€РµРЅ Р»РёРјРёС‚ РѕР±СЉС‘РјР° РёР»Рё С‡РёСЃР»Р° С„Р°Р№Р»РѕРІ"
                )
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
                    raise ValueError("РќРµРґРѕРїСѓСЃС‚РёРјР°СЏ Р·Р°РїРёСЃСЊ РІ ZIP")
                if entry.is_dir() or SKIP.intersection(path.parts):
                    continue
                if path.suffix not in SUFFIXES and path.name != ".env":
                    continue
                if entry.file_size > MAX_FILE or str(path) in files:
                    raise ValueError(
                        "РЎР»РёС€РєРѕРј Р±РѕР»СЊС€РѕР№ РёР»Рё РґСѓР±Р»РёСЂСѓСЋС‰РёР№СЃСЏ РёСЃС…РѕРґРЅС‹Р№ С„Р°Р№Р»"
                    )
                files[str(path)] = archive.read(entry).decode("utf-8-sig")
    except (zipfile.BadZipFile, UnicodeError, NotImplementedError, RuntimeError) as exc:
        raise ValueError(
            "РћР¶РёРґР°РµС‚СЃСЏ РёСЃРїСЂР°РІРЅС‹Р№ ZIP СЃ РёСЃС…РѕРґРЅРёРєР°РјРё РІ UTF-8"
        ) from exc
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
        raise ValueError(
            "Р’ Р°СЂС…РёРІРµ РѕС‚СЃСѓС‚СЃС‚РІСѓРµС‚ РїСЂРѕРµРєС‚ Gradle Kotlin DSL"
        )
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
        raise ValueError(
            "Р’С‹Р±РµСЂРёС‚Рµ GitHub-СЂРµРїРѕР·РёС‚РѕСЂРёР№ РёР· СЃРµСЂРІРµСЂРЅРѕРіРѕ СЃРїРёСЃРєР° СЂР°Р·СЂРµС€С‘РЅРЅС‹С…"
        )
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
                    raise ValueError(
                        "РђСЂС…РёРІ СЂРµРїРѕР·РёС‚РѕСЂРёСЏ РїСЂРµРІС‹С€Р°РµС‚ 24 РњР‘"
                    )
    except httpx.HTTPError as exc:
        raise ValueError(
            "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ Р°СЂС…РёРІ СЃ GitHub"
        ) from exc
    return unpack(bytes(content))
