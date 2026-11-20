"""Defensive static analysis of educational Kotlin projects."""
import fnmatch
import json
import re
from pathlib import Path

CATALOG = json.loads(Path(__file__).with_name("advisories.json").read_text(encoding="utf8"))["vulnerabilities"]


def finding(cat, kind, path, text, offset):
    return {"category": cat, "class": kind, "path": path, "line": text.count("\n", 0, offset)+1, "severity": "HIGH"}


def secrets(files):
    rows = []
    for path, text in files.items():
        if path.endswith((".yml", ".yaml", ".properties")):
            for m in re.finditer(r'(?im)^[ \t]*(?:authorization|[\w.-]*token)\s*[:=]\s*["\']?(?:Bearer\s+)?([^\s"$\'#<>]{8,})', text):
                if not re.search(r'example|placeholder|your[-_]', m[1], re.I):
                    rows.append(finding("SECRET","configuration-token",path,text,m.start(1)))
        if not path.endswith(".kt"):
            continue
        constants = set()
        for m in re.finditer(r'\b(?:val|var)\s+(\w+)(?:\s*:\s*String)?\s*=\s*([^\n;]+)', text):
            name, expr = m.groups()
            sink = re.escape(name)+r'\b'
            if re.search(r'getenv\s*\([^)]*\)\s*\?:\s*"[^"$]{6,}"', expr):
                kind = "secret-fallback"
            elif re.fullmatch(r'\s*"[^"$]+"\s*', expr):
                constants.add(name)
                if len(expr.strip('" ')) < 6 or re.search(r'placeholder|example|your[-_]|<[^>]+>', expr,re.I):
                    continue
                if re.search("password|passwd",name,re.I) or re.search(r'"[^"]*password"\s*(?:to|,)\s*'+sink,text,re.I):
                    kind = "password"
                elif re.search("api.?key",name,re.I) or re.search(r'"x-api-key"\s*,\s*'+sink,text,re.I):
                    kind = "api-key"
                else:
                    continue
            else:
                parts = [v.strip() for v in expr.split("+")]
                if len(parts)<2 or not all(v in constants or re.fullmatch(r'"[^"$]+"',v) for v in parts):
                    continue
                if not re.search(r'setBearerAuth\s*\(\s*'+sink,text):
                    continue
                kind = "recoverable-token"
            rows.append(finding("SECRET",kind,path,text,m.start()))
    return rows


def numeric(value):
    parts = list(map(int,value.split(".")))
    while parts and parts[-1]==0:
        parts.pop()
    return tuple(parts)


def matches(version, interval):
    if not re.fullmatch(r'\d+(?:\.\d+)*',version):
        return False
    v = numeric(version)
    for key in ("lower","upper"):
        if interval.get(key) is None:
            continue
        bound = numeric(interval[key])
        if v == bound and not interval[key+"Inclusive"]:
            return False
        if key=="lower" and v<bound or key=="upper" and v>bound:
            return False
    return True


def sca(files):
    rows = {}
    for path,text in files.items():
        if Path(path).name!="build.gradle.kts":
            continue
        prefix = path[:-len("build.gradle.kts")]
        props = dict(re.findall(r'(?m)^([\w.-]+)\s*=\s*([^\s#]+)',files.get("gradle.properties","")+"\n"+files.get(prefix+"gradle.properties","")))
        variables = dict(re.findall(r'\bval\s+(\w+)\s*=\s*"([\d.]+)"',text))
        for name,prop in re.findall(r'val\s+(\w+)\s*=\s*(?:providers\.)?gradleProperty\("([^"]+)"\)',text):
            variables[name] = props.get(prop,"")
        locks = dict(re.findall(r'(?m)^([^:\s#]+:[^:\s]+):([^=\s]+)=',files.get(prefix+"gradle.lockfile","")))
        for group,artifact,decl in re.findall(r'(?:\b(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*\(\s*|\badd\s*\(\s*"[^"]+"\s*,\s*)"([\w.-]+):([\w.-]+)(?::([^"]+))?"',text):
            version = locks.get(group+":"+artifact,variables.get(decl.strip("$"+"{}"),decl))
            for adv in CATALOG:
                if (group,artifact)!=(adv["group"],adv["artifact"]):
                    continue
                if any(matches(version,r) for r in adv["ranges"]):
                    rows[path,group,artifact,adv["id"]] = dict(category="SCA",path=path,group=group,artifact=artifact,version=version,
                        advisoryId=adv["id"],severity=adv["severity"],fixedVersions=adv["fixedVersions"],
                        cve_references=[v for v in adv["aliases"] if v.startswith("CVE-")])
    return list(rows.values())


def sast(files):
    rows = []
    kt = {p:t for p,t in files.items() if p.endswith(".kt")}
    routes = {r for t in kt.values() for r in re.findall(r'@(?:Get|Post|Put|Delete|Patch)Mapping\s*\(\s*"([^"]+)"',t)}
    for path,text in kt.items():
        def add(kind,pos):
            rows.append(finding("SAST",kind,path,text,pos))
        for m in re.finditer(r'(?:query\w*|update|execute)\s*\(\s*"([^"\n]{0,2000})"(\s*\+\s*\w+)?',text):
            if re.search(r'\b(?:SELECT|INSERT|UPDATE|DELETE)\b',m[1],re.I) and ("$" in m[1] or m[2]):
                add("sql-injection",m.start())
        for m in re.finditer(r'(?:hostnameVerifier\s*=|setHostnameVerifier\s*\()[^{}]{0,80}\{[^{}]{0,100}->\s*true\s*\}',text):
            add("tls-verification",m.start())
        for m in re.finditer(r'CorsConfiguration\(\)\s*\.apply\s*\{([^{}]*)\}',text):
            origin = re.search(r'allowedOrigin(?:s|Patterns)\s*=\s*listOf\(\s*"\*"',m[1])
            if origin and re.search(r'allowCredentials\s*=\s*true',m[1]):
                add("credentialed-cors",m.start(1)+origin.start())
        rules = list(re.finditer(r'requestMatchers\(\s*(?:(?:HttpMethod\.)?(\w+)\s*,\s*)?"([^"]+)"\s*\)\s*\.(\w+)\(',text))
        for i,rule in enumerate(rules):
            if rule[3]=="permitAll" and rule[2] in routes and any(
                r[3] in ("hasRole","hasAuthority","authenticated") and (not r[1] or r[1]==rule[1])
                and fnmatch.fnmatchcase(rule[2],r[2]) for r in rules[i+1:]):
                add("route-authorization",rule.start())
        for m in re.finditer(r'@(?:Get|Post|Put|Delete|Patch)Mapping\s*\(\s*"[^"]*\{[^"]+"\s*\)\s*fun\s+\w+\s*\(\s*@PathVariable\s+(\w+)\s*:[^)]*\)([^@]{0,1000})',text):
            call = re.search(r'\b\w+\.(\w+)\(\s*'+re.escape(m[1])+r'\s*\)',m[2])
            if not call or re.search(r'principal|authenticat|checkPermission',m.group(),re.I):
                continue
            pattern = r'fun\s+'+re.escape(call[1])+r'\s*\([^)]*\)[^{}]{0,500}?\bWHERE\s+\w+\s*=\s*\?\s*"'
            if any(re.search(pattern,t,re.I) for t in kt.values()):
                add("object-authorization",m.start(2)+call.start())
    return rows


SCANNERS = {"secrets":secrets, "sca":sca, "sast":sast}


class SubmissionReportExporter:
    @staticmethod
    def export(rows):
        fields = {"category","path","severity","description","remediation","class","line","endLine","group","artifact","version","advisoryId"}
        return {"findings":[{k:v for k,v in row.items() if k in fields} for row in rows]}
