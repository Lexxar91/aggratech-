"""Допуск v3: синтетический отчёт здесь только проверяет gate, не допускает продукт."""

from pathlib import Path

import pytest

from app.assessment.runner import POSTGRES_IMAGE, PYTHON_IMAGE
from app.assessment.v3_admission import (
    OperatorAcceptance,
    V3QualityReport,
    V3TechnicalRow,
    digest,
    evaluator_hash_v3,
    require_admission_v3,
    validate_materials,
)
from app.assessment.v3_models import V3Bank

BANK = Path("bank/private/v3.json")
ACCEPTANCE = Path("bank/private/v3_operator_acceptance.json")


def synthetic_report() -> V3QualityReport:
    """Только unit fixture: реальный допуск требует отдельного запуска всех решений."""
    bank = V3Bank.model_validate_json(BANK.read_bytes())
    rows = [
        V3TechnicalRow(
            task_id=c.task_id,
            solution_id=s.id,
            seed=seed,
            kind=s.kind,
            status="completed",
            task_score=(
                1
                if s.kind == "partial"
                else 0
                if s.kind == "mistake"
                else 2
                if s.kind == "unadapted" and c.task_id in {"X2-J", "Y2-J", "Y4-J"}
                else 4
            ),
            checks=sum(len(case.assertions) for case in c.cases if case.seed == seed),
            passed=True,
        )
        for c in bank.cards
        for s in c.solutions
        for seed in c.seeds
        if s.seed is None or s.seed == seed
    ]
    acceptance = OperatorAcceptance.model_validate_json(ACCEPTANCE.read_bytes())
    return V3QualityReport(
        bank_hash=digest(bank.model_dump(mode="json")),
        source_hash=bank.source_hash,
        grader_hash=evaluator_hash_v3(),
        runtime_images={"python": PYTHON_IMAGE, "sql": POSTGRES_IMAGE},
        technical_status="passed",
        admission_status="admitted",
        acceptance_hash=digest(acceptance.model_dump(mode="json")),
        checks=sum(r.checks for r in rows),
        results=rows,
    )


def test_materials_retain_source_and_saved_cases() -> None:
    bank = V3Bank.model_validate_json(BANK.read_bytes())
    validate_materials(bank)
    assert len(bank.cards) == 28
    for c in bank.cards:
        assert len(c.seeds) >= 3 and len(c.parameter_manifests) == len(c.seeds)
        assert {case.pack for case in c.cases} == set("ABCD")
    changed = bank.model_copy(deep=True)
    changed.cards[0].condition += "\nHidden new rule"
    with pytest.raises(ValueError, match="published_material_changed"):
        validate_materials(changed)
    changed = bank.model_copy(deep=True)
    changed.cards[0].cases[0].scenario["changed"] = True
    with pytest.raises(ValueError, match="fixture_hash_mismatch"):
        validate_materials(changed)


@pytest.mark.parametrize(
    "change",
    [
        "status_only",
        "evaluator",
        "runtime",
        "source",
        "bank",
        "missing",
        "duplicate",
        "failed",
        "checks",
        "acceptance",
    ],
)
def test_admitted_flag_cannot_bypass_technical_provenance(change: str) -> None:
    report = synthetic_report()
    if change == "status_only":
        report.results = []
    elif change == "evaluator":
        report.grader_hash = "0" * 64
    elif change == "runtime":
        report.runtime_images["sql"] = "postgres:17"
    elif change == "source":
        report.source_hash = "0" * 64
    elif change == "bank":
        report.bank_hash = "0" * 64
    elif change == "missing":
        report.results.pop()
    elif change == "duplicate":
        report.results.append(report.results[0])
    elif change == "failed":
        report.results[0].passed = False
    elif change == "checks":
        report.results[0].checks -= 1
    else:
        report.acceptance_hash = "0" * 64
    with pytest.raises(ValueError):
        require_admission_v3(BANK, report, ACCEPTANCE)


@pytest.mark.parametrize("change", ["status", "kind", "range", "mistake", "partial"])
def test_passed_row_cannot_hide_wrong_technical_result(change: str) -> None:
    report = synthetic_report()
    if change == "status":
        report.results[0].status = "environment_error"
    elif change == "kind":
        report.results[0].kind = "mistake"
    elif change == "range":
        report.results[0].task_score = 5
    else:
        next(r for r in report.results if r.kind == change).task_score = 4
    with pytest.raises(ValueError, match="solution_result_invalid"):
        require_admission_v3(BANK, report, ACCEPTANCE)


def test_operator_acceptance_is_distinct_and_source_bound(tmp_path: Path) -> None:
    report = synthetic_report()
    require_admission_v3(BANK, report, ACCEPTANCE)
    with pytest.raises(ValueError, match="acceptance_missing"):
        require_admission_v3(BANK, report, None)
    receipt = OperatorAcceptance.model_validate_json(ACCEPTANCE.read_bytes())
    receipt.source_hash = "0" * 64
    changed = tmp_path / "acceptance.json"
    changed.write_text(receipt.model_dump_json())
    with pytest.raises(ValueError, match="acceptance_changed"):
        require_admission_v3(BANK, report, changed)


@pytest.mark.parametrize(
    "filename",
    [
        "v3_grading.py",
        "v3_adapters.py",
        "v3_sql.py",
        "v3_python.py",
        "v3_runtime_policy.json",
        "policy.py",
        "service.py",
        "uv.lock",
    ],
)
def test_evaluator_hash_includes_runtime_and_configuration(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = evaluator_hash_v3()
    read = Path.read_bytes

    def modified(path: Path) -> bytes:
        raw = read(path)
        return raw + b"\nchanged" if path.name == filename else raw

    monkeypatch.setattr(Path, "read_bytes", modified)
    assert evaluator_hash_v3() != before
