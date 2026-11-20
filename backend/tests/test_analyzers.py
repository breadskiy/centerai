import json
from pathlib import Path
import os

import pytest
from backend.analyzers import SCANNERS, sca, secrets, sast
from backend.analyzers.common import SubmissionReportExporter
from backend.analyzers.sca import affected
from backend.sources import SUFFIXES


def test_public_benchmark():
    root = Path(os.getenv("TRAINING_ROOT", ".qa/training"))
    if not root.is_dir():
        pytest.skip("Set TRAINING_ROOT to the organizer fixture checkout")
    project = root / "training-project"
    files = {
        f.relative_to(project).as_posix(): f.read_text("utf-8")
        for f in project.rglob("*")
        if f.is_file() and f.suffix in SUFFIXES
    }
    rows = [r for scan in SCANNERS.values() for r in scan(files)]
    truth = json.loads(
        (root / "ground-truth/training-findings.json").read_text("utf-8")
    )

    def matches(fact, expected):
        if fact["category"] != expected["category"] or fact["path"] != expected["path"]:
            return False
        if fact["category"] == "SCA":
            return all(
                fact[k] == expected[k] for k in ("group", "artifact", "version")
            ) and fact["advisoryId"] in expected.get("advisoryIds", [expected["class"]])
        return (
            fact["class"] == expected["class"]
            and expected["line"] <= fact["line"] <= expected["endLine"]
        )

    remaining = list(truth["findings"])
    tp = 0
    for fact in rows:
        match = next((e for e in remaining if matches(fact, e)), None)
        if match:
            assert fact["severity"] == match["severity"], match["id"]
            tp += 1
            remaining.remove(match)
    fp, fn = len(rows) - tp, len(remaining)
    precision, recall = tp / max(len(rows), 1), tp / max(len(truth["findings"]), 1)
    print(
        f"TP={tp} FP={fp} FN={fn} Precision={precision:.3f} Recall={recall:.3f} F1={2 * precision * recall / max(precision + recall, 1e-10):.3f}"
    )
    assert (fp, fn) == (0, 0)
    assert not any(matches(f, control) for f in rows for control in truth["controls"])
    assert len(SubmissionReportExporter.export(rows)["findings"]) == 15


@pytest.mark.parametrize(
    "version,yes",
    [("2", True), ("2.0.0", True), ("2.9", True), ("2.10", False), ("2.11", False)],
)
def test_numeric_range(version, yes):
    assert (
        affected(
            version,
            {
                "lower": "2.0",
                "upper": "2.10",
                "lowerInclusive": True,
                "upperInclusive": False,
            },
        )
        is yes
    )


def test_catalog_and_lock_override():
    files = {
        "build.gradle.kts": "dependencies { implementation(libs.parser) }",
        "gradle/libs.versions.toml": '[versions]\nv="1.14.1"\n[libraries]\nparser={module="org.jsoup:jsoup",version.ref="v"}',
    }
    assert sca(files)[0]["version"] == "1.14.1"
    files["gradle.lockfile"] = "org.jsoup:jsoup:1.14.2=runtimeClasspath"
    assert sca(files) == []


def test_secrets_are_redacted_and_ignore_env():
    source = 'val rotatedPassword = "synthetic_fixture_21"\nval newToken = System.getenv("TOKEN")\n'
    rows = secrets(
        {"renamed.kt": source, "generic.yml": "token: \u0024{ROTATED_TOKEN}"}
    )
    assert len(rows) == 1 and rows[0]["class"] == "password"
    assert "synthetic_fixture_21" not in json.dumps(rows)


def test_comments_and_multiline_fallback():
    source = '// val ignoredPassword = "sample_hidden_01"\nval connection = System.getenv("ACCESS_TOKEN")\n    ?: "fixture_fallback_23"'
    rows = secrets({"Aliases.kt": source})
    assert [(row["class"], row["line"]) for row in rows] == [("secret-fallback", 2)]


def test_sql_distinguishes_binding():
    source = 'class Repo {\n fun load(q: String) = jdbc.queryForList(\n "SELECT label FROM items WHERE label = ?", q)\n}'
    assert sast({"renamed.kt": source}) == []
    rows = sast({"renamed.kt": source.replace('= ?", q', '= \u0024q"')})
    assert len(rows) == 1 and rows[0]["class"] == "sql-injection"
