"""Fixture-проверки формулы и CLI, не подтверждение квалификации людей."""

import copy
import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any  # Неверные JSON в негативных тестах намеренно не имеют DTO-типа.

import pytest

from app.matching.catalog import DEFAULT_PRIORITIES
from app.matching.engine import rank
from app.matching.fixtures import (
    InputError,
    candidates_from_fixture,
    example_dataset,
    load_dataset,
    load_labels,
    model_input,
)
from app.matching.metrics import measure
from app.matching.schemas import Candidate, Dataset, Labels, Need
from app.tools.matching_check import main


def dataset() -> Dataset:
    return model_input(Dataset, example_dataset())


def test_priority_and_formula() -> None:
    data = dataset()
    candidates = candidates_from_fixture(data)
    sql = rank(
        data.needs[0],
        candidates,
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    )
    http = rank(
        data.needs[1],
        candidates,
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    )
    assert sql.recommendations[0].candidate_id == "sql-strong"
    assert http.recommendations[0].candidate_id == "http-strong"
    a = sql.recommendations[0]
    b = http.recommendations[0]
    assert a.components.T == pytest.approx((0.95 * 2 + 0.6) / 3)
    assert a.components.K == pytest.approx((0.6 * 2 + 1 + 1) / 4)
    assert a.score == pytest.approx(55 * a.components.T + 25 * 0.8 + 8 + 5)
    assert any("приоритет 2" in line and "SQL" in line for line in a.explanations)
    assert any("приоритет 2" in line and "HTTP" in line for line in b.explanations)
    assert all(r.components.F == 0 for r in sql.recommendations)
    bonus = candidates[0].model_copy(
        update={"fsp_verified": True, "fsp_origin": "jury_fixture"}
    )
    improved = rank(
        data.needs[0],
        [bonus],
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    ).recommendations[0]
    assert improved.score - a.score == pytest.approx(7)
    assert improved.components.model_dump(exclude={"F"}) == a.components.model_dump(
        exclude={"F"}
    )
    assert any(
        r.group == "needs_clarification" and r.missing_conditions == ["salary"]
        for r in sql.recommendations
    )
    assert {r.candidate_id for r in sql.recommendations if r.group == "excluded"} == {
        "unconfirmed",
        "private",
    }


@pytest.mark.parametrize(
    ("days", "freshness", "penalty"),
    [(0, 1, 0), (90, 1, 0), (91, 0.5, 3), (180, 0.5, 3), (181, 0, 5)],
)
def test_freshness(days: int, freshness: float, penalty: int) -> None:
    data = dataset()
    c = candidates_from_fixture(data)[0]
    when = data.as_of - timedelta(days=days)
    c = c.model_copy(
        update={
            "skills": {
                k: v.model_copy(update={"verified_at": when})
                for k, v in c.skills.items()
            },
            "conditions": c.conditions.model_copy(update={"confirmed_at": when}),
        }
    )
    row = rank(
        data.needs[0],
        [c],
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    ).recommendations[0]
    assert row.components.U == freshness and row.components.P == penalty


@pytest.mark.parametrize(
    ("change", "group", "reason"),
    [
        ({"salary_from": 220000, "salary_to": 240000}, "eligible", None),
        ({"salary_from": 220001, "salary_to": 240000}, "excluded", "salary"),
        ({"salary_from": 100000, "salary_to": 160000}, "eligible", None),
        ({"salary_from": 100000, "salary_to": 159999}, "excluded", "salary"),
        ({"salary_from": 200000, "salary_to": None}, "eligible", None),
        ({"salary_from": None, "salary_to": None}, "needs_clarification", "salary"),
        ({"work_formats": None}, "needs_clarification", "work_formats"),
        ({"work_formats": ["office"]}, "excluded", "work_formats"),
        ({"available_from": None}, "needs_clarification", "available_from"),
    ],
)
def test_conditions(change: dict[str, object], group: str, reason: str | None) -> None:
    data = dataset()
    c = candidates_from_fixture(data)[0]
    c = c.model_copy(update={"conditions": c.conditions.model_copy(update=change)})
    row = rank(
        data.needs[0],
        [c],
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    ).recommendations[0]
    assert row.group == group
    if reason:
        assert reason in row.reasons + row.missing_conditions


def test_location_date_and_explicit_requirements() -> None:
    data = dataset()
    c = candidates_from_fixture(data)[0]
    n = data.needs[0].model_copy(
        update={
            "work_formats": ["hybrid"],
            "location": "Москва",
            "start_date_required": True,
            "additional_requirements": {"required_experience_years": 3},
        }
    )
    assert n.desired_start_date is not None
    c = c.model_copy(
        update={
            "conditions": c.conditions.model_copy(
                update={
                    "work_formats": ["hybrid"],
                    "location": None,
                    "available_from": n.desired_start_date + timedelta(days=1),
                }
            )
        }
    )
    row = rank(
        n, [c], as_of=data.as_of, comparable_methods=frozenset(["jury-example-v1"])
    ).recommendations[0]
    assert (
        row.group == "excluded"
        and row.reasons == ["start_date"]
        and set(row.missing_conditions) == {"location", "experience_years"}
    )
    c = c.model_copy(
        update={
            "experience_years": 2,
            "conditions": c.conditions.model_copy(
                update={"location": "Казань", "available_from": n.desired_start_date}
            ),
        }
    )
    row = rank(
        n, [c], as_of=data.as_of, comparable_methods=frozenset(["jury-example-v1"])
    ).recommendations[0]
    assert set(row.reasons) == {"location", "experience_years"}
    c = c.model_copy(
        update={
            "experience_years": 3,
            "conditions": c.conditions.model_copy(update={"location": "Москва"}),
        }
    )
    assert (
        rank(
            n, [c], as_of=data.as_of, comparable_methods=frozenset(["jury-example-v1"])
        )
        .recommendations[0]
        .group
        == "eligible"
    )


def test_stack_evidence_defaults_unknown_method_and_minimum_score() -> None:
    data = dataset()
    c = candidates_from_fixture(data)[0]
    n = data.needs[0].model_copy(
        update={
            "required_stack": [],
            "preferred_stack": [],
            "required_verified_skills": [],
            "skill_priorities": {},
        }
    )
    row = rank(
        n, [c], as_of=data.as_of, comparable_methods=frozenset(["jury-example-v1"])
    ).recommendations[0]
    assert row.components.K == 1
    assert row.components.T == pytest.approx((0.95 * 20 + 0.6 * 20) / 100)
    assert set(DEFAULT_PRIORITIES) == {"junior", "middle"}
    n = Need.model_validate(
        {
            **n.model_dump(),
            "required_stack": [{"technology": "python", "verification_required": True}],
        }
    )
    row = rank(
        n, [c], as_of=data.as_of, comparable_methods=frozenset(["other-method"])
    ).recommendations[0]
    assert (
        row.components.T == row.components.U == 0
        and "required_technology:python" in row.reasons
    )
    c = c.model_copy(
        update={
            "skills": {},
            "technologies": {},
            "conditions": c.conditions.model_copy(update={"confirmed_at": None}),
        }
    )
    n = Need.model_validate({**n.model_dump(), "required_stack": []})
    row = rank(
        n, [c], as_of=data.as_of, comparable_methods=frozenset(["jury-example-v1"])
    ).recommendations[0]
    assert row.group == "eligible" and row.score >= 0  # Низкие баллы сами не фильтр.


def test_ties_filters_and_tech_weights() -> None:
    data = dataset()
    a = candidates_from_fixture(data)[0]
    b = a.model_copy(update={"candidate_id": "a-first"})
    assert (
        rank(
            data.needs[0],
            [a, b],
            as_of=data.as_of,
            comparable_methods=frozenset(["jury-example-v1"]),
        )
        .recommendations[0]
        .candidate_id
        == "a-first"
    )
    c = a.model_copy(
        update={
            "visibility": a.visibility.model_copy(
                update={"blocked_employer_ids": [data.needs[0].employer_id]}
            )
        }
    )
    assert rank(
        data.needs[0],
        [c],
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    ).recommendations[0].reasons == ["privacy"]
    n = data.needs[0].model_copy(update={"accepted_grades": ["junior"]})
    assert (
        "grade"
        in rank(
            n, [a], as_of=data.as_of, comparable_methods=frozenset(["jury-example-v1"])
        )
        .recommendations[0]
        .reasons
    )
    c = a.model_copy(
        update={"technologies": {**a.technologies, "docker": "self_reported"}}
    )
    assert (
        rank(
            data.needs[0],
            [a, c],
            as_of=data.as_of,
            comparable_methods=frozenset(["jury-example-v1"]),
        )
        .recommendations[0]
        .score
        == rank(
            data.needs[0],
            [a],
            as_of=data.as_of,
            comparable_methods=frozenset(["jury-example-v1"]),
        )
        .recommendations[0]
        .score
    )


def write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_cli_offline_reproducible_swapped_and_partial_labels(tmp_path: Path) -> None:
    assert main(["--write-example", str(tmp_path / "example")]) == 0
    inp = tmp_path / "example/dataset.json"
    labels_path = tmp_path / "example/labels.json"
    assert main(["--input", str(inp), "--validate-only"]) == 0
    first = tmp_path / "first"
    second = tmp_path / "second"
    assert (
        main(
            ["--input", str(inp), "--labels", str(labels_path), "--output", str(first)]
        )
        == 0
    )
    assert set(p.name for p in first.iterdir()) == {
        "rankings.json",
        "metrics.json",
        "report.md",
        "run_manifest.json",
    }
    labels = json.loads(labels_path.read_text())
    labels["pairs"][0]["relevance"] = 0
    labels["pairs"][1]["relevance"] = 3
    swapped = write(tmp_path / "swapped.json", labels)
    assert (
        main(["--input", str(inp), "--labels", str(swapped), "--output", str(second)])
        == 0
    )
    assert (first / "rankings.json").read_bytes() == (
        second / "rankings.json"
    ).read_bytes()
    assert (first / "metrics.json").read_bytes() != (
        second / "metrics.json"
    ).read_bytes()
    manifest = json.loads((first / "run_manifest.json").read_text())
    manifest2 = json.loads((second / "run_manifest.json").read_text())
    assert (
        manifest["dataset_sha256"] == manifest2["dataset_sha256"]
        and manifest["labels_sha256"] != manifest2["labels_sha256"]
    )
    labels["pairs"] = labels["pairs"][1:]
    assert (
        main(
            [
                "--input",
                str(inp),
                "--labels",
                str(write(tmp_path / "partial.json", labels)),
                "--output",
                str(tmp_path / "partial"),
            ]
        )
        == 0
    )
    partial = json.loads((tmp_path / "partial/metrics.json").read_text())
    assert all(
        r["status"] == "not_measured" and r["precision_at_10"] is None
        for r in partial["records"]
        if r["need_id"] == "sql-priority"
    )
    assert main(["--input", str(inp), "--output", str(tmp_path / "none")]) == 0
    assert all(
        r["status"] == "not_measured"
        for r in json.loads((tmp_path / "none/metrics.json").read_text())["records"]
    )
    before = {p.name: p.read_bytes() for p in first.iterdir()}
    assert main(["--input", str(inp), "--output", str(first)]) == 2
    assert before == {p.name: p.read_bytes() for p in first.iterdir()}
    # Отдельный процесс не импортирует конфигурацию/ORM/инфраструктурные клиенты.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; from app.tools.matching_check import "
                "main; assert not any(x in sys.modules for x in "
                "['sqlalchemy','app.core.config','app.core.database',"
                "'app.assessment.runner','app.notifications.queue']);"
                " raise SystemExit(main(sys.argv[1:]))"
            ),
            "--input",
            str(inp),
            "--output",
            str(tmp_path / "process"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (first / "rankings.json").read_bytes() == (
        tmp_path / "process/rankings.json"
    ).read_bytes()


def test_metrics_full_oracle_and_short_denominator() -> None:
    data = dataset()
    labels = Labels.model_validate(
        {
            "schema_version": "matching-labels-v1",
            "dataset_id": data.dataset_id,
            "pairs": [
                {
                    "need_id": n.need_id,
                    "candidate_id": c.candidate_id,
                    "relevance": 2,
                    "eligibility": "eligible",
                }
                for n in data.needs
                for c in data.candidates
            ],
        }
    )
    rankings = [
        rank(
            n,
            candidates_from_fixture(data),
            as_of=data.as_of,
            comparable_methods=frozenset(["jury-example-v1"]),
            algorithm=a,
        )
        for a in ("B0", "B1", "B2")
        for n in data.needs
    ]
    measured: Any = measure(data, rankings, labels)
    rows = measured["records"]
    first = next(r for r in rows if r["algorithm"] == "B2" and r["group"] == "eligible")
    assert (
        first["precision_at_10"] == 0.2 and first["recall_at_20"] == 0.4
    )  # Oracle включает пропущенных фильтрами кандидатов.
    assert first["ndcg_at_10"] < 1
    assert len(first["eligibility_errors"]) == 3
    for row in measured["average_paired_differences_equal_weight_per_need"]:
        for metric in ["precision_at_10", "recall_at_20", "ndcg_at_10"]:
            assert row[metric] == (
                0 if row["group"] == "eligible" or metric == "precision_at_10" else None
            )
    zeros = labels.model_copy(
        update={"pairs": [p.model_copy(update={"relevance": 0}) for p in labels.pairs]}
    )
    zero_metrics: Any = measure(data, rankings, zeros)
    first = zero_metrics["records"][0]
    assert (
        first["recall_at_20"] is None
        and first["ndcg_at_10"] is None
        and first["precision_at_10"] == 0
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("unexpected",), True),
        (("as_of",), 123456),
        (("as_of",), "2026-10-07T10:00:00+01:00"),
        (("candidates", 0, "skills", "sql_data", "score"), True),
        (("candidates", 0, "skills", "sql_data", "score"), "95"),
        (("candidates", 0, "skills", "sql_data", "score"), 101),
        (("candidates", 0, "skills", "sql_data", "score"), 10**400),
        (
            ("candidates", 0, "skills", "sql_data", "verified_at"),
            "2027-01-01T00:00:00Z",
        ),
        (("candidates", 0, "conditions", "confirmed_at"), "2027-01-01T00:00:00Z"),
        (("candidates", 0, "conditions", "salary_to"), 1),
        (("candidates", 0, "technologies"), {"fastapi": "verified"}),
        (
            ("candidates", 0, "technologies"),
            {"Python": "self_reported", "python": "self_reported"},
        ),
        (("candidates", 0, "assessment_scope", "format"), "other"),
        (("candidates", 0, "assessment_scope", "language"), "go"),
        (("candidates", 0, "category_status"), "confirmed"),
        (("candidates", 1, "assessment_scope", "method_version"), "incomparable"),
        (("needs", 0, "skill_priorities"), {"sql_data": True}),
        (("needs", 0, "skill_priorities"), {"unknown_skill": 2}),
        (
            ("needs", 0, "required_stack"),
            [{"technology": "unknown", "verification_required": False}],
        ),
        (("needs", 0, "salary_from"), False),
        (("needs", 0, "salary_to"), 1),
    ],
)
def test_invalid_dataset(
    tmp_path: Path, path: tuple[object, ...], value: object
) -> None:
    data = copy.deepcopy(example_dataset())
    target: Any = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    input_path = write(tmp_path / "input.json", data)
    with pytest.raises(InputError):
        load_dataset(input_path)
    out = tmp_path / "out"
    assert main(["--input", str(input_path), "--output", str(out)]) == 2
    assert set(p.name for p in out.iterdir()) == {"errors.json"}
    assert "password" not in (out / "errors.json").read_text()


def test_limits_missing_duplicates_and_aliases(tmp_path: Path) -> None:
    data = example_dataset()
    data["candidates"] = data["candidates"] * 201
    with pytest.raises(InputError):
        load_dataset(write(tmp_path / "large.json", data))
    data = example_dataset()
    data["needs"] = data["needs"] * 51
    with pytest.raises(InputError):
        load_dataset(write(tmp_path / "needs.json", data))
    data = example_dataset()
    data["candidates"].append(data["candidates"][0])
    with pytest.raises(InputError, match="duplicate_id"):
        load_dataset(write(tmp_path / "duplicates.json", data))
    inp = tmp_path / "raw.json"
    inp.write_text('{"dataset_id":"one","dataset_id":"two"}')
    with pytest.raises(InputError, match="duplicate_json_key"):
        load_dataset(inp)
    inp.write_text('{"value":NaN}')
    with pytest.raises(InputError, match="non_finite_number"):
        load_dataset(inp)
    inp.write_text('{"value":' + "9" * 5000 + "}")
    with pytest.raises(InputError):
        load_dataset(inp)
    inp.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(InputError, match="file_size_limit"):
        load_dataset(inp)
    data = example_dataset()
    del data["candidates"][0]["conditions"]["location"]
    with pytest.raises(InputError):
        load_dataset(write(inp, data))
    data = example_dataset()
    data["needs"][0]["required_stack"][0]["technology"] = "Python"
    assert (
        load_dataset(write(inp, data))[0].needs[0].required_stack[0].technology
        == "python"
    )
    assert (
        main(
            [
                "--input",
                str(
                    write(
                        inp,
                        {
                            "schema_version": "matching-fixture-v1",
                            "dataset_id": "empty",
                            "as_of": "2026-10-07T00:00:00Z",
                            "candidates": [],
                            "needs": [],
                        },
                    )
                ),
                "--output",
                str(tmp_path / "empty"),
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    "error", ["reference", "dataset", "duplicate", "relevance", "eligibility", "limit"]
)
def test_invalid_labels(tmp_path: Path, error: str) -> None:
    data = dataset()
    pair = {
        "need_id": data.needs[0].need_id,
        "candidate_id": data.candidates[0].candidate_id,
        "relevance": 2,
        "eligibility": "eligible",
    }
    value: dict[str, Any] = {
        "schema_version": "matching-labels-v1",
        "dataset_id": data.dataset_id,
        "pairs": [pair],
    }
    if error == "reference":
        pair["candidate_id"] = "missing"
    if error == "dataset":
        value["dataset_id"] = "other"
    if error == "duplicate":
        value["pairs"] = [pair, pair]
    if error == "relevance":
        pair["relevance"] = True
    if error == "eligibility":
        pair["eligibility"] = "unknown"
    if error == "limit":
        value["pairs"] = [pair] * 100001
    with pytest.raises(InputError):
        load_labels(write(tmp_path / "labels.json", value), data)


def test_score_t_k_id_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.matching import engine
    from app.matching.schemas import Components

    data = dataset()
    base = candidates_from_fixture(data)[0]
    a = base.model_copy(update={"candidate_id": "z-higher-t"})
    b = base.model_copy(update={"candidate_id": "a-lower-t"})
    values = {
        a.candidate_id: Components(T=0.8, K=0.6, A=1, F=0, U=1, P=0),
        b.candidate_id: Components(T=0.7, K=0.82, A=1, F=0, U=1, P=0),
    }

    def prepared(
        need: Need, candidate: Candidate, skills: object, as_of: object
    ) -> Components:
        return values[candidate.candidate_id]

    monkeypatch.setattr(engine, "components", prepared)
    rows = rank(
        data.needs[0],
        [b, a],
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    ).recommendations
    assert rows[0].score == rows[1].score and rows[0].candidate_id == "z-higher-t"
    values[a.candidate_id] = Components(T=0.8, K=0.8, A=1, F=0, U=0, P=0)
    values[b.candidate_id] = Components(T=0.8, K=0.6, A=1, F=0, U=1, P=0)
    rows = rank(
        data.needs[0],
        [b, a],
        as_of=data.as_of,
        comparable_methods=frozenset(["jury-example-v1"]),
    ).recommendations
    assert rows[0].score == rows[1].score and rows[0].candidate_id == "z-higher-t"


def test_new_dataset_and_stable_runs(tmp_path: Path) -> None:
    data = example_dataset()
    data["dataset_id"] = "independent-transform"
    for i, row in enumerate(data["candidates"]):
        row["candidate_id"] = f"new-{i}"
        for evidence in row["skills"].values():
            evidence["score"] = max(0, evidence["score"] - 17)
    for i, need in enumerate(data["needs"]):
        need["need_id"] = f"new-need-{i}"
    inp = write(tmp_path / "input.json", data)
    assert main(["--input", str(inp), "--output", str(tmp_path / "one")]) == 0
    assert main(["--input", str(inp), "--output", str(tmp_path / "two")]) == 0
    assert (tmp_path / "one/rankings.json").read_bytes() == (
        tmp_path / "two/rankings.json"
    ).read_bytes()
    a = json.loads((tmp_path / "one/run_manifest.json").read_text())
    b = json.loads((tmp_path / "two/run_manifest.json").read_text())
    del a["duration_seconds"]
    del b["duration_seconds"]
    assert a == b
