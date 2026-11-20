import json
import re
import tomllib
from pathlib import Path, PurePosixPath

from .common import finding, line_at

DATABASE = json.loads((Path(__file__).parents[1] / "resources/advisories.json").read_text("utf-8"))
ADVISORIES = {}
for record in DATABASE["vulnerabilities"]:
    ADVISORIES.setdefault((record["group"], record["artifact"]), []).append(record)


def numeric(version):
    if not re.fullmatch(r'\d+(?:\.\d+)*', version):
        return None
    parts = list(map(int, version.split(".")))
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def affected(version, bounds):
    v = numeric(version)
    if v is None:
        return False
    lo = numeric(bounds["lower"]) if bounds["lower"] else None
    hi = numeric(bounds["upper"]) if bounds["upper"] else None
    return ((lo is None or v > lo or (v == lo and bounds["lowerInclusive"]))
            and (hi is None or v < hi or (v == hi and bounds["upperInclusive"])))


def declarations(source, catalog):
    configs = r'(?:\w*(?:[Ii]mplementation|[Rr]untimeOnly|[Cc]ompileOnly|[Aa]pi)|classpath|annotationProcessor|kapt|ksp)'
    pattern = rf'\b(?:{configs}\s*\(\s*|add\s*\(\s*"[^"]+"\s*,\s*)"([^":\s]+):([^":\s]+)(?::([^"]+))?"'
    for m in re.finditer(pattern, source):
        yield *m.groups(), m.start(1)
    aliases = {re.sub(r"[-_.]", ".", a): item for a, item in catalog.get("libraries", {}).items()}
    for m in re.finditer(rf'\b{configs}\s*\(\s*libs\.([\w.]+)\s*\)', source):
        item = aliases.get(m[1])
        if isinstance(item, dict):
            module = item.get("module", "") or f"{item.get('group', '')}:{item.get('name', '')}"
            version = item.get("version")
            if isinstance(version, dict):
                version = catalog.get("versions", {}).get(version.get("ref"))
            if module.count(":") == 1:
                yield *module.split(":"), version, m.start()


def scan(files):
    result = []
    props = dict(re.findall(r'(?m)^\s*([\w.]+)\s*=\s*([^\s#]+)', files.get("gradle.properties", "")))
    catalog = tomllib.loads(files.get("gradle/libs.versions.toml", ""))
    for path, source in files.items():
        if PurePosixPath(path).name != "build.gradle.kts":
            continue
        source = re.sub(r'/\*.*?\*/|//[^\n]*', lambda m: re.sub(r'[^\n]', ' ', m[0]), source, flags=re.S)
        variables = {**props, **dict(re.findall(r'\bval\s+(\w+)\s*=\s*"([^"]+)"', source))}
        for name, key in re.findall(r'\bval\s+(\w+)\s*=\s*(?:providers\.gradleProperty|property|findProperty)\("([^"]+)"\)', source):
            variables[name] = props.get(key, "")
        lock_path = str(PurePosixPath(path).with_name("gradle.lockfile"))
        locks = {(g, a): v for g, a, v in re.findall(r'(?m)^([^#:\s]+):([^:\s]+):([^=\s]+)=', files.get(lock_path, ""))}
        for group, artifact, declared, offset in declarations(source, catalog):
            version = locks.get((group, artifact)) or re.sub(r'\$\{?(\w+)\}?', lambda m: variables.get(m[1], ""), declared or "")
            for advisory in ADVISORIES.get((group, artifact), []):
                if not any(affected(version, bound) for bound in advisory["ranges"]):
                    continue
                fixed = ", ".join(advisory["fixedVersions"])
                result.append(finding("SCA", path, "known-vulnerable-dependency", advisory["severity"], f"{artifact} · {version}",
                                      "Версия входит в диапазон учебного справочника уязвимостей.",
                                      f"Сверьте совместимость с исправленными версиями: {fixed}.",
                                      f"{group}:{artifact}:{version}", group=group, artifact=artifact, version=version,
                                      advisoryId=advisory["id"], aliases=advisory["aliases"], line=line_at(source, offset)))
    return result
