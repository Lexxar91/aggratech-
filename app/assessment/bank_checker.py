"""Полный технический прогон банка и допуск только неизменённых материалов."""

import asyncio
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue

from app.assessment.bank_models import (
    FullBank,
    FullBankVersion,
    MaterialModel,
    load_bank,
)
from app.assessment.candidate_tests import CandidateTestEvaluator, Execute
from app.assessment.runner import PYTHON_IMAGE, ExecutionRequest, RunnerUnavailable
from app.assessment.structured_evaluator import equivalent, evaluate_structured

GRADER_VERSION = "backend-bank-grader-v1"
SKILL_PAIRS = {
    "1": ["language_algorithms", "sql_data"],
    "2": ["http_api", "security_validation"],
    "3": ["sql_data", "debug_reliability"],
    "4": ["language_algorithms", "http_api"],
    "5": ["sql_data", "debug_reliability"],
    "6": ["http_api", "security_validation"],
}


def digest(value: object) -> str:
    """Хеширует структурированные материалы с сохранением значений и типов."""
    raw = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def grader_hash() -> str:
    """Связывает допуск с кодом оценщиков, runner-контрактом и зависимостями."""
    paths = [
        "app/assessment/bank_checker.py",
        "app/assessment/bank_models.py",
        "app/assessment/bank_quality.py",
        "app/assessment/candidate_tests.py",
        "app/assessment/structured_evaluator.py",
        "app/assessment/runner.py",
        "uv.lock",
    ]
    return digest(
        {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}
    )


class CheckRow(MaterialModel):
    """Ожидаемый и фактический результат одной воспроизводимой проверки."""

    family: str
    grade: str
    kind: str
    case: str
    expected: JsonValue
    actual: JsonValue
    passed: bool


class VersionReport(MaterialModel):
    """Статус отдельной версии не зависит от успеха других версий."""

    family: str
    grade: str
    version: str
    material_hash: str
    status: Literal["passed", "failed", "incomplete"]
    checks: int


class QualityReport(MaterialModel):
    """Служебный технический отчёт, не свидетельство человеческой калибровки."""

    bank_version: str
    bank_hash: str
    blueprint_hash: str
    mappings_hash: str
    grader_version: str
    grader_hash: str
    runtime_image: str
    technical_status: Literal["passed", "failed", "incomplete"]
    technical_admission: Literal["passed", "blocked"]
    admission_status: Literal["admitted", "not_admitted"] = "not_admitted"
    admission_reason: str = "Independent review of these material hashes is required"
    human_difficulty: str = "not measured; final stage"
    parameters: dict[str, JsonValue]
    checks: int
    versions: list[VersionReport]
    results: list[CheckRow]
    technical_errors: list[str]


class ReviewRecord(MaterialModel):
    """Запись фактической независимой проверки конкретных байтов материалов."""

    reviewer: str = Field(min_length=1)
    author: str = Field(min_length=1)
    reviewed_at: datetime
    bank_hash: str
    blueprint_hash: str
    mappings_hash: str
    decision: Literal["approved", "changes_requested"]
    evidence: str = Field(min_length=1)


def validate_full_bank(bank: FullBank, blueprint: dict[str, JsonValue]) -> None:
    """Проверяет точную матрицу, отдельные действия, параметры и свидетелей ошибок."""
    keys = [(v.family, v.grade) for v in bank.versions]
    required = {
        (f"{form}{i}", g)
        for form in "XY"
        for i in range(1, 7)
        for g in ("junior", "middle")
    }
    if len(set(keys)) != 24 or set(keys) != required:
        raise ValueError("twenty_four_unique_versions_required")
    families = blueprint.get("families")
    if not isinstance(families, list) or len(families) != 12:
        raise ValueError("invalid_blueprint")
    seen: set[str] = set()
    for family in families:
        if not isinstance(family, dict):
            raise ValueError("invalid_blueprint_family")
        name = family.get("id")
        if (
            not isinstance(name, str)
            or name in seen
            or name not in {k[0] for k in required}
        ):
            raise ValueError("duplicate_or_unknown_family")
        seen.add(name)
        if (
            family.get("form") != name[0]
            or family.get("phase") != ("B" if name[1] in "56" else "A")
            or family.get("skills") != SKILL_PAIRS[name[1]]
        ):
            raise ValueError("blueprint_coverage_mismatch")
    for v in bank.versions:
        if (
            v.skills != SKILL_PAIRS[v.family[1]]
            or set(v.actions) != set(v.skills)
            or set(v.rubric) != set(v.skills)
        ):
            raise ValueError("separate_skill_actions_and_rubrics_required")
        if any(not action.strip() for action in v.actions.values()) or any(
            set(r) != set("01234") or not all(r.values()) for r in v.rubric.values()
        ):
            raise ValueError("incomplete_rubric")
        python = bool(v.solutions)
        params = v.cases if python else v.structured_cases
        ids = [c.id for c in params]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_case_id")
        for phase in ("base", "transfer"):
            if len({digest(c.input) for c in params if c.phase == phase}) < 3:
                raise ValueError("three_distinct_parameters_per_phase_required")
        if python:
            if len({s.id for s in v.solutions}) != len(v.solutions):
                raise ValueError("duplicate_solution")
            if not {"reference", "alternative", "mistake", "unadapted"} <= {
                s.kind for s in v.solutions
            }:
                raise ValueError("missing_solution_kind")
            base_ids = {c.id for c in v.cases if c.phase == "base"}
            transfer_ids = set(ids) - base_ids
            for s in v.solutions:
                passes = set(s.expected_passes)
                if not passes <= set(ids):
                    raise ValueError("unknown_expected_case")
                if s.kind in ("reference", "alternative") and passes != set(ids):
                    raise ValueError("correct_solution_must_pass_all")
                if s.kind == "mistake" and passes == set(ids):
                    raise ValueError("mistake_without_witness")
                if s.kind == "unadapted" and (
                    not base_ids <= passes or transfer_ids <= passes
                ):
                    raise ValueError("transfer_without_witness")
        for case in v.structured_cases:
            fields = [r.field for r in case.rules]
            if len(fields) != len(set(fields)):
                raise ValueError("duplicate_rubric_field")
            checked_skills = {r.skill for r in case.rules}
            if not checked_skills <= set(v.skills) or (
                not python and checked_skills != set(v.skills)
            ):
                raise ValueError("unobserved_skill")
            for skill in checked_skills:
                if sum(r.points for r in case.rules if r.skill == skill) != 4:
                    raise ValueError("rubric_must_total_four")
            for rule in case.rules:
                if (
                    rule.requires is not None
                    and rule.requires not in fields[: fields.index(rule.field)]
                ):
                    raise ValueError("invalid_rule_dependency")
                if rule.field in case.answer_options and not all(
                    any(
                        equivalent(value, option)
                        for option in case.answer_options[rule.field]
                    )
                    for value in rule.accepted
                ):
                    raise ValueError("accepted_choice_not_offered")
            if not {"reference", "alternative", "partial", "mistake"} <= {
                e.kind for e in case.examples
            }:
                raise ValueError("missing_structured_examples")
            for e in case.examples:
                if set(e.expected_scores) != checked_skills or any(
                    type(s) is not int or not 0 <= s <= 4
                    for s in e.expected_scores.values()
                ):
                    raise ValueError("invalid_expected_scores")
                if e.kind in ("reference", "alternative") and set(
                    e.expected_scores.values()
                ) != {4}:
                    raise ValueError("correct_structured_answer_must_pass")
                if e.kind == "mistake" and any(
                    s >= 3 for s in e.expected_scores.values()
                ):
                    raise ValueError("mistake_must_fail_requirement")
        if not python and not any(
            e.kind == "unadapted" and all(s < 3 for s in e.expected_scores.values())
            for c in v.structured_cases
            if c.phase == "transfer"
            for e in c.examples
        ):
            raise ValueError("structured_transfer_without_witness")
        if v.family in ("X4", "Y4"):
            good = [s for s in v.solutions if s.kind in ("reference", "alternative")]
            bad = [s for s in v.solutions if s.kind == "mistake"]
            if (
                v.test_policy is None
                or len(good) != 2
                or len(bad) != 3
                or good[0].source == good[1].source
            ):
                raise ValueError("two_distinct_correct_three_mistakes_required")
            classes = set(v.test_policy.mandatory + [v.test_policy.additional])
            if (
                len(classes) != 3
                or classes != {s.error_class for s in bad}
                or not 2 <= len(v.candidate_tests) <= 3
            ):
                raise ValueError("invalid_candidate_test_policy")
        elif v.test_policy is not None or v.candidate_tests:
            raise ValueError("candidate_tests_outside_scope")


def validate_mappings(mappings: dict[str, JsonValue], bank: FullBank) -> None:
    """Проверяет три подготовленные трассировки без урезания стандартных форм."""
    examples = mappings.get("examples")
    if not isinstance(examples, list) or len(examples) != 3:
        raise ValueError("three_vacancy_mappings_required")
    for example in examples:
        if (
            not isinstance(example, dict)
            or example.get("grade") not in ("junior", "middle")
            or example.get("forms")
            != {
                "X": [f"X{i}" for i in range(1, 7)],
                "Y": [f"Y{i}" for i in range(1, 7)],
            }
        ):
            raise ValueError("standard_forms_required")
        rows = example.get("rows")
        if not isinstance(rows, list) or not rows:
            raise ValueError("empty_mapping")
        for row in rows:
            if (
                not isinstance(row, dict)
                or not row.get("requirement")
                or not row.get("technology")
            ):
                raise ValueError("invalid_requirement")
            family_ids = row.get("families")
            if not isinstance(family_ids, list) or len(family_ids) != 2:
                raise ValueError("mapping_needs_xy")
            for family in family_ids:
                version = next(
                    (
                        v
                        for v in bank.versions
                        if v.family == family and v.grade == example["grade"]
                    ),
                    None,
                )
                skill = row.get("skill")
                if (
                    version is None
                    or not isinstance(skill, str)
                    or skill not in version.actions
                    or row.get("rubric") != skill
                    or not row.get("action")
                ):
                    raise ValueError("mapping_unknown_action_or_rubric")


class BankQualityChecker:
    """Выполняет все проверки и сохраняет фактические результаты по 24 версиям."""

    def __init__(self, execute: Execute) -> None:
        self.execute = execute

    async def check(
        self,
        path: Path,
        blueprint_path: Path = Path("bank/blueprints.json"),
        mappings_path: Path = Path("bank/vacancy_mappings.json"),
    ) -> QualityReport:
        """Незавершённый прогон или расхождение закрывает технический допуск."""
        bank = await asyncio.to_thread(load_bank, path)
        bank_raw = await asyncio.to_thread(path.read_bytes)
        blueprint_raw = await asyncio.to_thread(blueprint_path.read_bytes)
        mappings_raw = await asyncio.to_thread(mappings_path.read_bytes)
        code_hash = await asyncio.to_thread(grader_hash)
        blueprint = json.loads(blueprint_raw)
        mappings = json.loads(mappings_raw)
        validate_full_bank(bank, blueprint)
        validate_mappings(mappings, bank)
        rows: list[CheckRow] = []
        errors: list[str] = []
        versions: list[VersionReport] = []
        evaluator = CandidateTestEvaluator(self.execute)
        for v in bank.versions:
            offset, error_offset = len(rows), len(errors)

            def record(
                kind: str,
                case: str,
                expected: JsonValue,
                actual: JsonValue,
                version: FullBankVersion = v,
            ) -> None:
                rows.append(
                    CheckRow(
                        family=version.family,
                        grade=version.grade,
                        kind=kind,
                        case=case,
                        expected=expected,
                        actual=actual,
                        passed=equivalent(actual, expected),
                    )
                )

            for case in v.structured_cases:
                for index, example in enumerate(case.examples):
                    actual = evaluate_structured(case, example.answer)
                    record(
                        "structured:" + example.kind,
                        case.id + ":" + str(index),
                        {str(k): val for k, val in example.expected_scores.items()},
                        {str(k): val for k, val in actual.items()},
                    )
            for solution in v.solutions:
                try:
                    result = await self.execute(
                        ExecutionRequest(
                            source=solution.source, inputs=[c.input for c in v.cases]
                        )
                    )
                    if result.status != "completed" or len(result.outputs) != len(
                        v.cases
                    ):
                        errors.append(
                            f"{v.family}/{v.grade}/{solution.id}:execution_incomplete"
                        )
                        continue
                    for python_case, out in zip(v.cases, result.outputs, strict=True):
                        record(
                            "python:" + solution.kind,
                            solution.id + ":" + python_case.id,
                            python_case.id in solution.expected_passes,
                            equivalent(out, python_case.expected),
                        )
                except RunnerUnavailable:
                    errors.append(f"{v.family}/{v.grade}:runner_unavailable")
                    break
            if v.test_policy:
                outcome = await evaluator.evaluate(v, v.candidate_tests)
                if outcome.status == "incomplete":
                    errors.append(f"{v.family}/{v.grade}:candidate_tests_incomplete")
                record(
                    "candidate_tests",
                    "all_classes",
                    True,
                    outcome.mandatory_met and outcome.additional_met,
                )
                wrong = [dict(c) for c in v.candidate_tests]
                wrong[0] = {"input": wrong[0]["input"], "expected": {"wrong": True}}
                rejected = await evaluator.evaluate(v, wrong)
                if rejected.status == "incomplete":
                    errors.append(f"{v.family}/{v.grade}:wrong_expectation_incomplete")
                record(
                    "candidate_tests",
                    "wrong_expectation",
                    False,
                    rejected.mandatory_met,
                )
                record(
                    "candidate_tests",
                    "wrong_case_not_valid",
                    False,
                    rejected.valid_cases[0] if rejected.valid_cases else True,
                )
                duplicates = await evaluator.evaluate(v, [v.candidate_tests[0]] * 2)
                repeated = await evaluator.evaluate(v, [v.candidate_tests[0]] * 3)
                if "incomplete" in (duplicates.status, repeated.status):
                    errors.append(f"{v.family}/{v.grade}:duplicates_incomplete")
                record(
                    "candidate_tests",
                    "duplicates_no_gain",
                    [str(x) for x in duplicates.detected_classes],
                    [str(x) for x in repeated.detected_classes],
                )
            status: Literal["passed", "failed", "incomplete"] = "passed"
            if len(errors) > error_offset:
                status = "incomplete"
            elif not all(row.passed for row in rows[offset:]):
                status = "failed"
            versions.append(
                VersionReport(
                    family=v.family,
                    grade=v.grade,
                    version=v.version,
                    material_hash=digest(v.model_dump(mode="json")),
                    status=status,
                    checks=len(rows) - offset,
                )
            )
        overall: Literal["passed", "failed", "incomplete"] = (
            "incomplete"
            if errors
            else ("passed" if all(v.status == "passed" for v in versions) else "failed")
        )
        return QualityReport(
            bank_version=bank.bank_version,
            bank_hash=hashlib.sha256(bank_raw).hexdigest(),
            blueprint_hash=hashlib.sha256(blueprint_raw).hexdigest(),
            mappings_hash=hashlib.sha256(mappings_raw).hexdigest(),
            grader_version=GRADER_VERSION,
            grader_hash=code_hash,
            runtime_image=PYTHON_IMAGE,
            technical_status=overall,
            technical_admission="passed" if overall == "passed" else "blocked",
            parameters={
                "minimum_parameter_sets_per_phase": 3,
                "versions": 24,
                "forms": ["X", "Y"],
                "candidate_tests": "2..3",
                "runtime_generation": False,
            },
            checks=len(rows),
            versions=versions,
            results=rows,
            technical_errors=errors,
        )


def require_admission(
    path: Path,
    report: QualityReport,
    *,
    reviews: list[ReviewRecord] | None = None,
    technical_only: bool = False,
    blueprint_path: Path = Path("bank/blueprints.json"),
    mappings_path: Path = Path("bank/vacancy_mappings.json"),
) -> FullBank:
    """Отклоняет старые/неполные отчёты; зачётный допуск требует review."""
    bank = load_bank(path)
    validate_full_bank(bank, json.loads(blueprint_path.read_bytes()))
    validate_mappings(json.loads(mappings_path.read_bytes()), bank)
    if (
        report.bank_hash != hashlib.sha256(path.read_bytes()).hexdigest()
        or report.bank_version != bank.bank_version
        or report.blueprint_hash
        != hashlib.sha256(blueprint_path.read_bytes()).hexdigest()
        or report.mappings_hash
        != hashlib.sha256(mappings_path.read_bytes()).hexdigest()
    ):
        raise ValueError("materials_changed")
    if (
        report.grader_version != GRADER_VERSION
        or report.grader_hash != grader_hash()
        or report.runtime_image != PYTHON_IMAGE
    ):
        raise ValueError("grader_changed")
    if (
        report.technical_status != "passed"
        or report.technical_admission != "passed"
        or report.technical_errors
        or not report.results
        or report.checks != len(report.results)
        or not all(
            r.passed and equivalent(r.expected, r.actual) for r in report.results
        )
    ):
        raise ValueError("technical_admission_failed")
    expected: dict[tuple[str, str], FullBankVersion] = {
        (v.family, v.grade): v for v in bank.versions
    }
    if len(report.versions) != 24 or {
        (v.family, v.grade) for v in report.versions
    } != set(expected):
        raise ValueError("incomplete_versions")
    for result in report.versions:
        v = expected[(result.family, result.grade)]
        rows = [r for r in report.results if (r.family, r.grade) == (v.family, v.grade)]
        plan: dict[tuple[str, str], JsonValue] = {}
        for c in v.structured_cases:
            for index, example in enumerate(c.examples):
                plan[("structured:" + example.kind, c.id + ":" + str(index))] = {
                    str(k): val for k, val in example.expected_scores.items()
                }
        for solution in v.solutions:
            for python_case in v.cases:
                plan[
                    ("python:" + solution.kind, solution.id + ":" + python_case.id)
                ] = python_case.id in solution.expected_passes
        if v.test_policy:
            plan[("candidate_tests", "all_classes")] = True
            plan[("candidate_tests", "wrong_expectation")] = False
            plan[("candidate_tests", "wrong_case_not_valid")] = False
            duplicate = next(
                (
                    r
                    for r in rows
                    if r.kind == "candidate_tests" and r.case == "duplicates_no_gain"
                ),
                None,
            )
            if (
                duplicate is None
                or not isinstance(duplicate.actual, list)
                or any(
                    x not in v.test_policy.mandatory + [v.test_policy.additional]
                    for x in duplicate.actual
                )
            ):
                raise ValueError("incomplete_candidate_tests")
            plan[("candidate_tests", "duplicates_no_gain")] = duplicate.actual
        required_checks = len(plan)
        if (
            result.status != "passed"
            or result.version != v.version
            or result.material_hash != digest(v.model_dump(mode="json"))
            or result.checks != required_checks
            or len(rows) != required_checks
            or len({(r.kind, r.case) for r in rows}) != required_checks
        ):
            raise ValueError("incomplete_or_changed_version")
        if {(r.kind, r.case) for r in rows} != set(plan) or any(
            not equivalent(r.expected, plan[(r.kind, r.case)]) for r in rows
        ):
            raise ValueError("report_does_not_match_check_plan")
    if not technical_only:
        authors = {v.author for v in bank.versions}
        approved = [
            r
            for r in (reviews or [])
            if r.decision == "approved"
            and r.reviewer not in authors
            and r.reviewer != r.author
            and r.author in authors
            and r.reviewed_at.tzinfo is not None
            and r.bank_hash == report.bank_hash
            and r.blueprint_hash == report.blueprint_hash
            and r.mappings_hash == report.mappings_hash
        ]
        if not approved:
            raise ValueError("independent_review_required")
    return bank


def public_summary(report: QualityReport) -> dict[str, JsonValue]:
    """Публикует агрегаты и версии без заданий, ответов и закрытого пула."""
    return {
        "bank_version": report.bank_version,
        "bank_hash": report.bank_hash,
        "grader_version": report.grader_version,
        "grader_hash": report.grader_hash,
        "technical_status": report.technical_status,
        "checks": report.checks,
        "versions_checked": len(report.versions),
        "admission_status": report.admission_status,
        "human_difficulty": report.human_difficulty,
    }
