import re
from .common import finding, line_at

LITERAL = re.compile(r'^\s*"([^"$\n]+)"\s*$')
BIND = re.compile(r'\b(?:val|var)\s+(\w+)(?:\s*:\s*String)?\s*=\s*([^\n;]+)')
SENSITIVE = re.compile(r'pass(?:word|wd)|api[-_]?key|secret|token|authorization', re.I)
TITLES = {"password": "Пароль в исходниках", "api-key": "Встроенный ключ API",
          "configuration-token": "Токен в настройках", "secret-fallback": "Секрет по умолчанию",
          "recoverable-token": "Токен из строковых фрагментов", "private-key": "Закрытый ключ в проекте"}


def plausible(value):
    return len(value.strip()) >= 5 and not re.search(r'\$\{|<[^>]+>|change[-_]?me|placeholder|your[-_]|example|^\*+$', value, re.I)


def scan(files):
    result = []
    for path, source in files.items():
        def add(kind, start, level="HIGH"):
            result.append(finding("SECRET", path, kind, level, TITLES[kind],
                                  "Значение учётных данных может быть извлечено из файлов проекта.",
                                  "Замените значение в хранилище секретов и передавайте его через окружение.",
                                  "Значение скрыто ••••", line=line_at(source, start)))

        for match in re.finditer(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', source):
            add("private-key", match.start(), "CRITICAL")
        if path.endswith(".kt"):
            constants = {}
            for match in BIND.finditer(source):
                name, expression = match.groups()
                value = LITERAL.match(expression.strip())
                if value:
                    constants[name] = (value[1], 1)
                    if SENSITIVE.search(name) and plausible(value[1]):
                        kind = "password" if re.search("pass", name, re.I) else "api-key" if re.search("key", name, re.I) else "configuration-token"
                        add(kind, match.start(), "MEDIUM" if kind == "api-key" else "HIGH")
                else:
                    fallback = re.search(r'(?:getenv|getProperty)\(\s*"([^"]+)"\s*\)\s*\?:\s*"([^"$]+)"', expression)
                    if fallback and SENSITIVE.search(name + fallback[1]) and plausible(fallback[2]):
                        add("secret-fallback", match.start(), "LOW")
                    parts = re.split(r'\s*\+\s*', expression.strip())
                    values = [constants.get(p) or ((p[1:-1], 1) if LITERAL.fullmatch(p) else None) for p in parts]
                    if len(parts) > 1 and all(values):
                        constants[name] = ("".join(v[0] for v in values), sum(v[1] for v in values))
                        sinks = r'(?:setBearerAuth\s*\(|(?:set|header)\s*\(\s*"Authorization"\s*,)\s*(?:"Bearer\s+\$)?' + re.escape(name) + r'\b'
                        if plausible(constants[name][0]) and re.search(sinks, source[match.end():]):
                            add("recoverable-token", match.start(), "MEDIUM")
        elif path.endswith((".yml", ".yaml", ".properties", ".env")) or path.endswith("/.env") or path == ".env":
            for match in re.finditer(r'(?m)^\s*([\w.-]+)\s*[:=]\s*["\']?([^#\r\n"\']+)', source):
                key, value = match.groups()
                if SENSITIVE.search(key) and plausible(value):
                    add("password" if "pass" in key.lower() else "configuration-token", match.start(1))
    return result
