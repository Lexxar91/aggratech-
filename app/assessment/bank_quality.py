import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.assessment.runner import (
    PYTHON_IMAGE,
    ExecutionRequest,
    ExecutionResult,
    RunnerUnavailable,
)


class Case(BaseModel):
    """Служебный проверочный случай с ожидаемым JSON-результатом."""

    model_config = ConfigDict(extra="forbid")
    id: str
    phase: Literal["base", "transfer"]
    input: JsonValue
    expected: JsonValue


class Solution(BaseModel):
    """Подготовленная реализация и независимо заданные ожидания по случаям."""

    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["reference", "alternative", "mistake", "unadapted"]
    source: str
    expected_passes: list[str]
    error_class: str | None = None


class StructuredExample(BaseModel):
    """Ответ на SQL-часть с ожидаемой частичной оценкой по рубрике."""

    model_config = ConfigDict(extra="forbid")
    answer: dict[str, JsonValue]
    expected_score: int = Field(ge=0, le=4)


class StructuredCase(BaseModel):
    """Объективный SQL/data-кейс без исполнения свободного SQL."""

    model_config = ConfigDict(extra="forbid")
    id: str
    condition: str
    rows: list[dict[str, JsonValue]]
    expected_groups: JsonValue
    examples: list[StructuredExample]


class BankVersion(BaseModel):
    """Полная поставка одного семейства и грейда в пределах первого этапа."""

    model_config = ConfigDict(extra="forbid")
    family: Literal["X1", "X4"]
    grade: Literal["junior", "middle"]
    version: str
    skills: list[str]
    condition: str
    diagnosis: str
    transfer: str
    verification: str
    rubric: dict[str, JsonValue]
    provenance: str
    review_status: Literal["pending", "reviewed"]
    cases: list[Case] = Field(min_length=6)
    solutions: list[Solution] = Field(min_length=3)
    structured_cases: list[StructuredCase]
    candidate_tests: list[dict[str, JsonValue]]


class BankMaterials(BaseModel):
    """Версионированный набор первых двух семейств, не полный зачётный банк."""

    model_config = ConfigDict(extra="forbid")
    bank_version: str
    versions: list[BankVersion] = Field(min_length=4, max_length=4)


def structured_score(answer: dict[str, JsonValue], expected: JsonValue) -> int:
    """Оценивает два наблюдаемых требования SQL-части независимо от исходного SQL."""
    if answer.get("groups") != expected:
        return 0
    if answer.get("count_kind") != "non_null":
        return 2
    return 4 if answer.get("null_policy") == "skip_amount_keep_group" else 3


def validate_materials(materials: BankMaterials) -> None:
    """Проверяет комплектность параметров, переносов, решений и четырёх версий."""
    if {(v.family, v.grade) for v in materials.versions} != {
        (family, grade) for family in ("X1", "X4") for grade in ("junior", "middle")
    }:
        raise ValueError("four_unique_versions_required")
    for version in materials.versions:
        ids = [case.id for case in version.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_case_id")
        for phase in ("base", "transfer"):
            if sum(case.phase == phase for case in version.cases) < 3:
                raise ValueError("three_parameter_sets_required_per_phase")
        if len({solution.id for solution in version.solutions}) != len(
            version.solutions
        ):
            raise ValueError("duplicate_solution_id")
        if not all(
            (
                version.condition,
                version.diagnosis,
                version.transfer,
                version.verification,
                version.provenance,
                version.rubric,
            )
        ):
            raise ValueError("incomplete_materials")
        kinds = {solution.kind for solution in version.solutions}
        if not {"reference", "alternative", "mistake", "unadapted"}.issubset(kinds):
            raise ValueError("missing_solution_kind")
        for solution in version.solutions:
            if not set(solution.expected_passes).issubset(ids):
                raise ValueError("unknown_expected_case")
            if solution.kind in ("reference", "alternative"):
                if set(solution.expected_passes) != set(ids):
                    raise ValueError("correct_solution_must_pass_all_cases")
        if version.family == "X1" and len(version.structured_cases) < 3:
            raise ValueError("three_structured_parameter_sets_required")
        if version.family == "X4":
            correct = [
                s for s in version.solutions if s.kind in ("reference", "alternative")
            ]
            mistakes = [s for s in version.solutions if s.kind == "mistake"]
            if len(correct) != 2 or len(mistakes) != 3:
                raise ValueError("x4_requires_two_correct_three_mistakes")
            if len({s.error_class for s in mistakes}) != 3:
                raise ValueError("three_error_classes_required")
            if not 2 <= len(version.candidate_tests) <= 3:
                raise ValueError("candidate_tests_required")


async def check_bank(
    path: Path,
    execute: Callable[[ExecutionRequest], Awaitable[ExecutionResult]],
) -> dict[str, object]:
    """Проверяет полный банк либо историческую поставку первых двух семейств."""
    raw = await asyncio.to_thread(path.read_bytes)
    if json.loads(raw).get("scope") == "full":
        from app.assessment.bank_checker import BankQualityChecker

        return (await BankQualityChecker(execute).check(path)).model_dump(mode="json")
    grader_source = await asyncio.to_thread(Path(__file__).read_bytes)
    materials = BankMaterials.model_validate_json(raw)
    validate_materials(materials)
    rows: list[dict[str, object]] = []
    technical_errors: list[str] = []
    checks = 0
    for version in materials.versions:
        for item in version.structured_cases:
            for example in item.examples:
                actual = structured_score(example.answer, item.expected_groups)
                rows.append(
                    {
                        "family": version.family,
                        "grade": version.grade,
                        "case": item.id,
                        "kind": "structured",
                        "expected_score": example.expected_score,
                        "actual_score": actual,
                        "passed": actual == example.expected_score,
                    }
                )
                checks += 1
        for solution in version.solutions:
            try:
                result = await execute(
                    ExecutionRequest(
                        source=solution.source,
                        inputs=[case.input for case in version.cases],
                    )
                )
            except RunnerUnavailable:
                technical_errors.append(
                    f"{version.family}/{version.grade}:runner_unavailable"
                )
                break
            if result.status != "completed":
                technical_errors.append(
                    f"{version.family}/{version.grade}/{solution.id}:{result.status}"
                )
                continue
            if len(result.outputs) != len(version.cases):
                technical_errors.append("runner_output_count_mismatch")
                continue
            for case, output in zip(version.cases, result.outputs, strict=True):
                actual_pass = output == case.expected
                expected_pass = case.id in solution.expected_passes
                rows.append(
                    {
                        "family": version.family,
                        "grade": version.grade,
                        "solution": solution.id,
                        "case": case.id,
                        "kind": "python",
                        "expected_pass": expected_pass,
                        "actual_pass": actual_pass,
                        "passed": actual_pass == expected_pass,
                    }
                )
                checks += 1
        if version.family == "X4":
            correct_cases = [
                {"input": c["input"], "expected": c["expected"]}
                for c in version.candidate_tests
            ]
            detected: set[str] = set()
            tests_valid = True
            for solution in version.solutions:
                if solution.kind == "unadapted":
                    continue
                try:
                    result = await execute(
                        ExecutionRequest(
                            source=solution.source,
                            inputs=[case["input"] for case in correct_cases],
                        )
                    )
                except RunnerUnavailable:
                    technical_errors.append(
                        f"{version.family}/{version.grade}:runner_unavailable"
                    )
                    break
                if result.status != "completed" or len(result.outputs) != len(
                    correct_cases
                ):
                    technical_errors.append("candidate_test_execution_incomplete")
                    continue
                matches = all(
                    output == case["expected"]
                    for case, output in zip(correct_cases, result.outputs, strict=True)
                )
                if solution.kind in ("reference", "alternative"):
                    tests_valid = tests_valid and matches
                elif not matches and solution.error_class is not None:
                    detected.add(solution.error_class)
                checks += 1
            rows.append(
                {
                    "family": version.family,
                    "grade": version.grade,
                    "kind": "candidate_tests",
                    "passed": tests_valid and len(detected) == 3,
                    "detected_classes": sorted(detected),
                }
            )
    passed = all(row["passed"] is True for row in rows)
    technical_status = (
        "incomplete" if technical_errors else ("passed" if passed else "failed")
    )
    return {
        "bank_version": materials.bank_version,
        "bank_hash": hashlib.sha256(raw).hexdigest(),
        "grader_hash": hashlib.sha256(grader_source).hexdigest(),
        "runtime_image": PYTHON_IMAGE,
        "scope": "stage1: X1/X4 junior/middle; not the complete bank",
        "technical_status": technical_status,
        "admission_status": "not_admitted",
        "admission_reason": "Full bank and mutual review are required at stage 3",
        "checks": checks,
        "results": rows,
        "technical_errors": technical_errors,
        "human_difficulty": "not measured",
    }
