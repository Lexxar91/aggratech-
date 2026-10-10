"""Технический допуск v3 и отдельное операторское принятие исходных материалов."""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.assessment.runner import POSTGRES_IMAGE, PYTHON_IMAGE
from app.assessment.v3_cases import cases_for
from app.assessment.v3_grading import V3Execute, grade_v3
from app.assessment.v3_models import V3Bank, V3Material

GRADER_VERSION: Literal["backend-v3-grader-1"] = "backend-v3-grader-1"
SOURCE_HASH = "5705b3a6d2d5c4a0da11064b1fc4fed69e40fe034d4f24f609f411168d1ec458"


def digest(value: object) -> str:
    """Хеширует значения независимо от оформления JSON."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def evaluator_hash_v3() -> str:
    """Связывает методику, исполнение, адаптеры, допуск и конфигурацию."""
    paths = sorted(Path("app/assessment").glob("v3_*.py")) + [
        Path(p)
        for p in (
            "app/assessment/runner.py",
            "app/assessment/policy.py",
            "app/assessment/service.py",
            "app/assessment/jobs.py",
            "app/assessment/admin.py",
            "app/assessment/runtime_bank.py",
            "app/assessment/schemas.py",
            "app/core/config.py",
            "runner/sandbox.py",
            "runner/server.py",
            "runner/v3_adapters.py",
            "runner/v3_python.py",
            "runner/v3_sql.py",
            "bank/v3_runtime_policy.json",
            "pyproject.toml",
            "uv.lock",
        )
    ]
    return digest(
        {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    )


class OperatorAcceptance(V3Material):
    """Это разрешение пользователя, а не вымышленное независимое review."""

    type: Literal["operator_content_acceptance"]
    source_hash: str
    source_path: str
    authorization: str
    accepted_at: str
    independent_expert_review: Literal["not_recorded"] = "not_recorded"


class V3TechnicalRow(V3Material):
    task_id: str
    solution_id: str
    seed: int
    kind: str
    status: str
    task_score: int | None
    checks: int
    passed: bool
    failed_checks: list[str] = Field(default_factory=list)


class V3QualityReport(V3Material):
    bank_version: Literal["3.0"] = "3.0"
    bank_hash: str
    source_hash: str
    grader_version: Literal["backend-v3-grader-1"] = GRADER_VERSION
    grader_hash: str
    runtime_images: dict[str, str]
    technical_status: Literal["passed", "failed", "incomplete"]
    admission_status: Literal["admitted", "not_admitted"] = "not_admitted"
    acceptance_hash: str | None = None
    checks: int
    results: list[V3TechnicalRow]
    technical_errors: list[str] = Field(default_factory=list)
    human_calibration: Literal["not_measured_by_this_run"] = "not_measured_by_this_run"


def validate_materials(bank: V3Bank) -> None:
    """Сверяет исходные условия/ключи и сохранённые параметры без генерации runtime."""
    raw = Path(bank.source_path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != bank.source_hash:
        raise ValueError("v3_source_changed")
    text = raw.decode()
    common = (
        text.split("## 3. Общий технический контракт\n", 1)[1]
        .split("## 4.", 1)[0]
        .strip()
    )
    headings = list(
        re.finditer(r"^### ([XY][1-6](?:-(?:PY|SQL))?-[JM]) — (.+)$", text, re.M)
    )
    if len(headings) != 28:
        raise ValueError("v3_source_matrix_changed")
    for index, heading in enumerate(headings):
        end = (
            headings[index + 1].start()
            if index + 1 < len(headings)
            else text.index("## 6.", heading.end())
        )
        section = text[heading.end() : end]
        card = next(c for c in bank.cards if c.task_id == heading[1])
        reference = next(s for s in card.solutions if s.kind == "reference")
        notes = (
            section.split("**Ключ для разработчика проверки**", 1)[1]
            .split("**Обязательные пакеты", 1)[0]
            .strip()
        )
        code = re.search(r"```(python|sql)\n(.*?)```", notes, re.S)
        if code is None or (
            card.title != heading[2]
            or card.common_contract != common
            or card.condition
            != section.split("**Кандидату**", 1)[1].split("**Перенос", 1)[0].strip()
            or card.transfer
            != section.split(
                "**Перенос — показать после сохранения первого решения**", 1
            )[1]
            .split("**Ключ", 1)[0]
            .strip()
            or reference.base != code[2]
            or reference.transfer != code[2]
            or card.developer_notes != notes
            or card.packs != dict(re.findall(r"^- ([ABCD]): (.+)$", section, re.M))
        ):
            raise ValueError("v3_published_material_changed")
        if len(set(card.seeds)) < 3 or not card.cases:
            raise ValueError("v3_saved_seeds_missing")
        if {m.get("seed") for m in card.parameter_manifests} != set(card.seeds):
            raise ValueError("v3_parameter_manifest_missing")
        if len({case.id for case in card.cases}) != len(card.cases):
            raise ValueError("v3_duplicate_case")
        for seed in card.seeds:
            cases = cases_for(card, seed)
            manifest = next(m for m in card.parameter_manifests if m["seed"] == seed)
            if manifest["fixture_hash"] != digest(
                [c.model_dump(mode="json") for c in cases]
            ):
                raise ValueError("v3_fixture_hash_mismatch")
            if {case.pack for case in cases} != set("ABCD") or sum(
                c.pack == "A" for c in cases
            ) < 2:
                raise ValueError("v3_package_coverage_missing")
            for case in cases:
                if (
                    case.pack in ("A", "B")
                    and case.phase != "base"
                    or case.pack == "C"
                    and case.phase != "transfer"
                ):
                    raise ValueError("v3_package_phase_mismatch")
                if any(
                    not any(
                        r.id == a.requirement_id and r.skill == a.skill
                        for r in card.requirements
                    )
                    for a in case.assertions
                ):
                    raise ValueError("v3_requirement_mapping_invalid")


def expected_rows(bank: V3Bank) -> set[tuple[str, str, int]]:
    """Каждый ответ проверяется на всех seeds, частичные — на своём."""
    return {
        (card.task_id, solution.id, seed)
        for card in bank.cards
        for solution in card.solutions
        for seed in card.seeds
        if solution.seed is None or solution.seed == seed
    }


def require_admission_v3(
    bank_path: Path,
    report: V3QualityReport,
    acceptance_path: Path | None,
    *,
    technical_only: bool = False,
) -> V3Bank:
    """Ручной admitted без полного актуального технического отчёта недостаточен."""
    bank = V3Bank.model_validate_json(bank_path.read_bytes())
    validate_materials(bank)
    if (
        report.bank_hash != digest(bank.model_dump(mode="json"))
        or report.source_hash != bank.source_hash
        or report.grader_hash != evaluator_hash_v3()
        or report.runtime_images != {"python": PYTHON_IMAGE, "sql": POSTGRES_IMAGE}
        or report.technical_status != "passed"
        or report.technical_errors
        or any(not row.passed for row in report.results)
        or {(r.task_id, r.solution_id, r.seed) for r in report.results}
        != expected_rows(bank)
        or len(report.results) != len(expected_rows(bank))
        or report.checks != sum(r.checks for r in report.results)
    ):
        raise ValueError("v3_technical_admission_stale_or_incomplete")
    for row in report.results:
        card = next(c for c in bank.cards if c.task_id == row.task_id)
        solution = next(s for s in card.solutions if s.id == row.solution_id)
        expected_score = (
            1
            if solution.kind == "partial"
            else 2
            if solution.kind == "unadapted" and card.task_id in {"X2-J", "Y2-J", "Y4-J"}
            else 4
        )
        if (
            row.kind != solution.kind
            or row.status != "completed"
            or row.task_score is None
            or not 0 <= row.task_score <= 4
            or (
                row.task_score >= 4
                if solution.kind == "mistake"
                else row.task_score != expected_score
            )
        ):
            raise ValueError("v3_technical_solution_result_invalid")
        if row.checks != sum(len(c.assertions) for c in cases_for(card, row.seed)):
            raise ValueError("v3_technical_checks_incomplete")
    if not technical_only:
        if acceptance_path is None:
            raise ValueError("v3_operator_acceptance_missing")
        acceptance = OperatorAcceptance.model_validate_json(
            acceptance_path.read_bytes()
        )
        if (
            acceptance.source_hash != bank.source_hash
            or acceptance.source_hash != SOURCE_HASH
            or acceptance.source_path != bank.source_path
            or not acceptance.authorization.strip()
            or report.acceptance_hash != digest(acceptance.model_dump(mode="json"))
        ):
            raise ValueError("v3_operator_acceptance_changed")
    return bank


async def check_bank_v3(bank_path: Path, execute: V3Execute) -> V3QualityReport:
    """Исполняет настоящие ответы; не создаёт оценок или фиктивного review вручную."""
    initial_hash = await asyncio.to_thread(evaluator_hash_v3)
    bank = V3Bank.model_validate_json(await asyncio.to_thread(bank_path.read_bytes))
    await asyncio.to_thread(validate_materials, bank)
    rows: list[V3TechnicalRow] = []
    errors: list[str] = []
    for card in bank.cards:
        for solution in card.solutions:
            for seed in card.seeds:
                if solution.seed is not None and solution.seed != seed:
                    continue
                grade = await grade_v3(
                    card, solution.base, solution.transfer, seed, execute
                )
                passed = grade.status == "completed"
                if solution.kind in ("reference", "alternative"):
                    passed = (
                        passed
                        and grade.task_score == 4
                        and all(v == 4 for v in grade.scores.values())
                        and not grade.critical_violations
                    )
                elif solution.kind == "partial":
                    passed = passed and grade.task_score == 1
                elif solution.kind == "unadapted":
                    passed = passed and (
                        grade.task_score == 2
                        if card.task_id in {"X2-J", "Y2-J", "Y4-J"}
                        else grade.task_score == 4
                    )
                else:
                    passed = (
                        passed and grade.task_score is not None and grade.task_score < 4
                    )
                checks = sum(len(c.assertions) for c in cases_for(card, seed))
                row = V3TechnicalRow(
                    task_id=card.task_id,
                    solution_id=solution.id,
                    seed=seed,
                    kind=solution.kind,
                    status=grade.status,
                    task_score=grade.task_score,
                    checks=checks,
                    passed=passed,
                    failed_checks=[
                        str(c["test_id"]) + ":" + str(c["requirement_id"])
                        for c in grade.checks
                        if c["passed"] is False
                    ],
                )
                rows.append(row)
                if grade.status != "completed":
                    errors.append(f"{card.task_id}:{solution.id}:{seed}:{grade.status}")
        selected = [r for r in rows if r.task_id == card.task_id]
        print(
            f"{card.task_id}: {sum(r.passed for r in selected)}/{len(selected)}",
            flush=True,
        )
    changed = initial_hash != await asyncio.to_thread(evaluator_hash_v3)
    if changed:
        errors.append("evaluator_changed_during_check")
    return V3QualityReport(
        bank_hash=digest(bank.model_dump(mode="json")),
        source_hash=bank.source_hash,
        grader_hash=initial_hash,
        runtime_images={"python": PYTHON_IMAGE, "sql": POSTGRES_IMAGE},
        technical_status="incomplete"
        if changed
        else "passed"
        if all(r.passed for r in rows) and not errors
        else "failed",
        checks=sum(r.checks for r in rows),
        results=rows,
        technical_errors=errors,
    )
