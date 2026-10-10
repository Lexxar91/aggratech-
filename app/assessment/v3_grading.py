"""Пакеты v3 и отдельные свидетельства навыков, без усреднения доли тестов."""

import json
from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from app.assessment.runner import (
    RunnerUnavailable,
    V3ExecutionRequest,
    V3ExecutionResult,
)
from app.assessment.v3_cases import cases_for
from app.assessment.v3_models import V3Assertion, V3Card, V3Case, V3TaskGrade

V3Execute = Callable[[V3ExecutionRequest], Awaitable[V3ExecutionResult]]


def package_score(results: list[tuple[str, bool]]) -> int:
    """Один обязательный провал не компенсируется дополнительными успехами."""
    ordinary = [passed for pack, passed in results if pack == "A"]
    if len(ordinary) < 2 or not any(ordinary):
        return 0
    if not all(ordinary):
        return 1
    if any(not passed for pack, passed in results if pack in ("B", "C")):
        return 2
    if any(not passed for pack, passed in results if pack == "D"):
        return 3
    return 4


def at_path(observed: JsonValue, path: list[str]) -> JsonValue:
    """Путь выбирается закрытой спецификацией, а не ответом кандидата."""
    for key in path:
        if isinstance(observed, dict):
            observed = observed[key]
        elif isinstance(observed, list) and key.isdecimal():
            observed = observed[int(key)]
        else:
            raise ValueError("observation_path_missing")
    return observed


def equal(actual: JsonValue, expected: JsonValue) -> bool:
    """bool не равен 1; порядок строк/элементов сохраняется, ключей объекта — нет."""
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            equal(actual[key], expected[key]) for key in expected
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            equal(a, e) for a, e in zip(actual, expected, strict=True)
        )
    return actual == expected


def matches(observed: JsonValue, assertion: V3Assertion) -> bool:
    """Сравнивает только независимое наблюдение со спецификацией данного признака."""
    try:
        actual = at_path(observed, assertion.path)
    except KeyError, IndexError, ValueError:
        return False
    expected = assertion.expected
    if assertion.comparison == "exact":
        return equal(actual, expected)
    if assertion.comparison == "unordered":
        if not isinstance(actual, list) or not isinstance(expected, list):
            return False
        # Мультимножество: одинаковые строки не удаляются через set.
        canonical_actual = sorted(json.dumps(v, sort_keys=True) for v in actual)
        canonical_expected = sorted(json.dumps(v, sort_keys=True) for v in expected)
        return canonical_actual == canonical_expected
    if assertion.comparison == "count":
        return (
            isinstance(actual, list)
            and type(expected) is int
            and len(actual) == expected
        )
    if assertion.comparison in ("minimum", "maximum"):
        if type(actual) is not int or type(expected) is not int:
            return False
        return (
            actual >= expected
            if assertion.comparison == "minimum"
            else actual <= expected
        )
    if assertion.comparison == "one_of":
        return isinstance(expected, list) and any(
            equal(actual, value) for value in expected
        )
    if assertion.comparison == "contains":
        return (
            isinstance(actual, list)
            and isinstance(expected, list)
            and all(any(equal(a, e) for a in actual) for e in expected)
        )
    if assertion.comparison == "excludes":
        return (
            isinstance(actual, list)
            and isinstance(expected, list)
            and not any(equal(a, e) for a in actual for e in expected)
        )
    raise ValueError("unsupported_observation_comparison")


def evaluate_observations(
    cases: list[V3Case], observations: dict[str, JsonValue]
) -> V3TaskGrade:
    """Отдельная рубрика навыка применяется только к его наблюдаемым действиям."""
    task_results: list[tuple[str, bool]] = []
    skill_results: dict[str, list[tuple[str, bool]]] = {}
    checks: list[dict[str, JsonValue]] = []
    requirement_results: dict[str, bool] = {}
    critical: set[str] = set()
    for observation in observations.values():
        if isinstance(observation, dict) and observation.get("status") in (
            "environment_error",
            "review_required",
            "invalid_item",
        ):
            return V3TaskGrade.model_validate({"status": observation["status"]})
    if len([c for c in cases if c.pack == "A"]) < 2 or {c.pack for c in cases} != set(
        "ABCD"
    ):
        return V3TaskGrade(status="invalid_item")
    for case in cases:
        observation = observations.get(case.id)
        if isinstance(observation, dict):
            state = observation.get("status")
            if state in ("environment_error", "review_required", "invalid_item"):
                return V3TaskGrade.model_validate({"status": state})
        per_skill: dict[str, list[bool]] = {}
        for assertion in case.assertions:
            passed = observation is not None and matches(observation, assertion)
            per_skill.setdefault(assertion.skill, []).append(passed)
            requirement_results[assertion.requirement_id] = (
                requirement_results.get(assertion.requirement_id, True) and passed
            )
            checks.append(
                {
                    "test_id": case.id,
                    "pack": case.pack,
                    "phase": case.phase,
                    "requirement_id": assertion.requirement_id,
                    "skill": assertion.skill,
                    "passed": passed,
                }
            )
            # Отсутствующее наблюдение не доказывает опасный побочный эффект.
            if not passed and assertion.critical and observation is not None:
                try:
                    at_path(observation, assertion.path)
                except KeyError, IndexError, ValueError:
                    continue
                critical.add(assertion.critical)
        task_results.append(
            (case.pack, all(all(values) for values in per_skill.values()))
        )
        for skill, values in per_skill.items():
            skill_results.setdefault(skill, []).append((case.pack, all(values)))
    return V3TaskGrade(
        status="completed",
        task_score=package_score(task_results),
        scores={
            skill: package_score(results) for skill, results in skill_results.items()
        },
        packs={
            pack: all(passed for p, passed in task_results if p == pack)
            for pack in "ABCD"
        },
        checks=checks,
        critical_violations=sorted(critical),
        requirement_results=requirement_results,
    )


async def grade_v3(
    card: V3Card,
    base: str,
    transfer: str,
    seed: int,
    execute: V3Execute,
) -> V3TaskGrade:
    """Неотправленный ответ и инфраструктурный отказ не получают балл 0."""
    if not base.strip():
        return V3TaskGrade(status="not_submitted")
    if not transfer.strip():
        return V3TaskGrade(status="incomplete")
    cases = cases_for(card, seed)
    if not card.cases:
        return V3TaskGrade(status="invalid_item")
    observations: dict[str, JsonValue] = {}
    try:
        for phase, source in (("base", base), ("transfer", transfer)):
            chosen = [case for case in cases if case.phase == phase]
            for start in range(0, len(chosen), 16):
                chunk = chosen[start : start + 16]
                result = await execute(
                    V3ExecutionRequest(
                        task_id=card.task_id,
                        language=card.language,
                        source=source,
                        scenarios=[case.scenario for case in chunk],
                    )
                )
                if result.status in ("timeout", "output_limit", "runtime_error"):
                    return V3TaskGrade(status="review_required")
                if result.status == "candidate_error":
                    continue
                for case, output in zip(chunk, result.outputs, strict=True):
                    observations[case.id] = output
    except RunnerUnavailable, OSError:
        return V3TaskGrade(status="environment_error")
    return evaluate_observations(cases, observations)


def family_evidence(
    grades: list[tuple[str, dict[str, int]]],
) -> dict[str, dict[str, int]]:
    """Связанные карточки не дают второго семейства по тому же навыку."""
    result: dict[str, dict[str, int]] = {}
    for family, scores in grades:
        target = result.setdefault(family, {})
        for skill, value in scores.items():
            target[skill] = min(target.get(skill, value), value)
    return result
