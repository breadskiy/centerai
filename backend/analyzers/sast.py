"""Local structural rules. Source is parsed as text and is never executed."""
import fnmatch
import re
from dataclasses import dataclass

import tree_sitter_kotlin
from tree_sitter import Language, Parser
from .common import finding, line_at

LANGUAGE = Language(tree_sitter_kotlin.language())


@dataclass
class Function:
    path: str
    name: str
    text: str
    line: int


def functions(path, source, parser):
    raw = source.encode()
    todo = [parser.parse(raw).root_node]
    while todo:
        node = todo.pop()
        if node.type == "function_declaration":
            text = raw[node.start_byte:node.end_byte].decode()
            name = re.search(r'\bfun\s+(\w+)', text)
            if name:
                yield Function(path, name[1], text, node.start_point.row + 1)
        else:
            todo.extend(reversed(node.named_children))


def scan(files):
    parser = Parser(LANGUAGE)
    funcs = [f for p, s in files.items() if p.endswith(".kt") for f in functions(p, s, parser)]
    result = []
    routes = {}
    object_calls = set()
    for f in funcs:
        mapping = re.search(r'@(Get|Post|Put|Delete|Patch)Mapping\s*\(\s*"([^"]*)"', f.text)
        if mapping:
            prefix = re.search(r'@RequestMapping\s*\(\s*"([^"]+)"[^)]*\)\s*(?:\w+\s+)*class\b', files[f.path])
            route = ((prefix[1].rstrip("/") if prefix else "") + "/" + mapping[2].lstrip("/")).rstrip("/")
            routes[mapping[1].upper(), route] = f
        param = re.search(r'@PathVariable(?:\([^)]*\))?\s+(\w+)', f.text)
        if param and not re.search(r'Principal|Authentication|@PreAuthorize|@PostAuthorize', f.text):
            for call in re.finditer(r'\b(\w+)\.(\w+)\(\s*' + re.escape(param[1]) + r'\s*\)', f.text):
                owner = re.search(r'\b' + re.escape(call[1]) + r'\s*:\s*(\w+)', files[f.path])
                if owner:
                    object_calls.add((owner[1], call[2]))

    for f in funcs:
        def add(kind, match, severity, title, description, remediation):
            result.append(finding("SAST", f.path, kind, severity, title, description,
                                  remediation, f"fun {f.name}(…) · {kind}",
                                  line=f.line - 1 + line_at(f.text, match.start())))

        sql = re.search(r'\b(?:query\w*|execute\w*|update)\s*\(\s*"{1,3}\s*(?:SELECT|UPDATE|DELETE|INSERT)\b[^"]*(?:\$\{?\w+|"[\s\n]*\+\s*\w+)', f.text, re.I)
        if sql:
            add("sql-injection", sql, "HIGH", "Динамический SQL", "Строка запроса содержит подстановку данных.",
                "Передавайте значение параметром подготовленного запроса.")
        tls = re.search(r'(?:hostnameVerifier\s*=|setHostnameVerifier\s*\()\s*(?:HostnameVerifier\s*)?\{\s*[^{}]*?->\s*true\s*}', f.text)
        if tls:
            add("tls-verification", tls, "HIGH", "Проверка имени узла отключена", "HostnameVerifier принимает любое имя.",
                "Используйте стандартную проверку имени узла при TLS-соединении.")
        for block in re.finditer(r'CorsConfiguration\s*\(\s*\)\s*\.apply\s*\{([^{}]*)}', f.text):
            wildcard = re.search(r'allowedOrigin(?:Pattern)?s\s*=\s*(?:listOf|mutableListOf)\(\s*"\*"', block[1])
            if wildcard and re.search(r'allowCredentials\s*=\s*true', block[1]):
                add("credentialed-cors", re.compile(r'allowedOrigin').search(f.text, block.start(1)), "MEDIUM",
                    "CORS разрешает сторонние origin", "В одной конфигурации совмещены wildcard-origin и credentials.",
                    "Укажите конкретные доверенные origin или отключите credentials.")

        seen = []
        for rule in re.finditer(r'requestMatchers\(\s*(?:(?:HttpMethod\.)?([A-Z]+)\s*,\s*)?"([^"]+)"\s*\)\s*\.\s*(\w+)', f.text):
            method, pattern, action = rule.groups()
            for (verb, route), handler in routes.items():
                if (method and verb != method) or not fnmatch.fnmatchcase(route, pattern):
                    continue
                if any((not m or m == verb) and fnmatch.fnmatchcase(route, p) for m, p in seen):
                    continue
                if action == "permitAll" and re.search(r'query(?:ForList)?\s*\(', handler.text) and not re.search(r'@(?:Pre|Post)Authorize|Principal|Authentication', handler.text):
                    add("route-authorization", rule, "HIGH", "Публичный маршрут с доступом к данным",
                        "Первое подходящее правило разрешает анонимный вызов обработчика, читающего записи.",
                        "Проверьте назначение маршрута и ограничьте доступ нужной ролью.")
                    break
            seen.append((method, pattern))

        if any(name == f.name and re.search(r'\bclass\s+' + re.escape(owner) + r'\b', files[f.path]) for owner, name in object_calls):
            query = re.search(r'\bSELECT\s+([^"]+?)\s+FROM\s+[^"]*?\s+WHERE\s+([^"]+)', f.text, re.I)
            owner_field = r'\b(?:owner|customer|user|account)_?id\b'
            if query and re.search(owner_field, query[1], re.I) and not re.search(owner_field, query[2], re.I):
                add("object-authorization", query, "HIGH", "Чтение объекта без проверки владельца",
                    "ID из маршрута передаётся в запрос. Запись содержит владельца, который отсутствует в предикате.",
                    "Ограничьте запрос одновременно идентификатором объекта и текущим пользователем.")
    return result
