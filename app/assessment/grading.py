"""Оценка одного семейства по сохранённым материалам; эталоны не уходят runner."""

from pydantic import BaseModel, Field, JsonValue

from app.assessment.bank_models import FullBankVersion, StructuredTask
from app.assessment.candidate_tests import (
    CandidateTestEvaluator,
    Execute,
    apply_test_rubric,
)
from app.assessment.runner import ExecutionRequest, RunnerUnavailable
from app.assessment.schemas import TaskAnswer
from app.assessment.structured_evaluator import equivalent, evaluate_structured

DIAGNOSIS = {
    "X1": "wrong_aggregate",
    "X4": "first_page",
    "Y1": "lost_order",
    "Y4": "non_retryable",
}
VERIFICATION = ["empty", "boundary", "transfer"]


class FamilyGrade(BaseModel):
    """Оценки и безопасные признаки без входов, ответов и закрытых исходников."""

    scores: dict[str, int] = Field(default_factory=dict)
    base_correct: bool = False
    transfer_correct: bool = False
    tests_valid: bool | None = None
    mandatory_tests_met: bool | None = None
    quality_limited: bool = False


def selected_task(
    version: FullBankVersion, phase: str, index: int
) -> StructuredTask | None:
    """Возвращает зафиксированный параметрический вариант структурированной части."""
    choices = [c for c in version.structured_cases if c.phase == phase]
    return choices[index % len(choices)] if choices else None


async def execute_observed(
    source: str, inputs: list[JsonValue], execute: Execute
) -> tuple[list[JsonValue], bool]:
    """Собирает выход и факт изменения входа; ожидаемые ответы остаются вне sandbox."""
    if not source.strip():
        return [], False
    # Только наблюдение входа/выхода; рубрики, эталоны и ожидаемые ответы не передаются.
    instrumented = (
        source
        + """
_observed_candidate = solve
import json as _observation_json
def solve(data):
    before = _observation_json.dumps(data, sort_keys=True)
    result = _observed_candidate(data)
    unchanged = before == _observation_json.dumps(data, sort_keys=True)
    return {"value": result, "input_unchanged": unchanged}
"""
    )
    try:
        result = await execute(ExecutionRequest(source=instrumented, inputs=inputs))
    except ValueError:
        return [], False
    if result.status == "runtime_error":
        raise RunnerUnavailable("execution_infrastructure_failure")
    if result.status != "completed":
        return [], False
    if len(result.outputs) != len(inputs):
        raise RunnerUnavailable("output_count_mismatch")
    values: list[JsonValue] = []
    unchanged = True
    for output in result.outputs:
        if not isinstance(output, dict) or set(output) != {"value", "input_unchanged"}:
            raise RunnerUnavailable("observation_protocol_failure")
        values.append(output["value"])
        unchanged = unchanged and output["input_unchanged"] is True
    return values, unchanged


def projection(value: JsonValue, skill: str, family: str) -> JsonValue:
    """Разделяет выход алгоритма и трассу HTTP, сохраняя отдельные действия навыков."""
    if isinstance(value, dict) and family == "X4":
        keys = ["items"] if skill == "language_algorithms" else ["calls", "error"]
        return {key: value[key] for key in keys if key in value}
    if isinstance(value, dict) and family == "Y4":
        keys = (
            ["calls"]
            if skill == "language_algorithms"
            else ["calls", "status", "waits"]
        )
        return {key: value[key] for key in keys if key in value}
    return value


async def grade_family(
    version: FullBankVersion,
    base: TaskAnswer,
    transfer: TaskAnswer,
    index: int,
    execute: Execute,
) -> FamilyGrade:
    """Применяет рубрики и ограничение переноса без превращения сбоя в ноль."""
    scores: dict[str, int] = {}
    base_ok, transfer_ok = True, True
    for phase, answer in (("base", base), ("transfer", transfer)):
        task = selected_task(version, phase, index)
        if task:
            result = evaluate_structured(task, answer.structured)
            if phase == "base":
                scores.update((str(skill), score) for skill, score in result.items())
                base_ok = all(x >= 3 for x in result.values())
            else:
                transfer_ok = all(x >= 3 for x in result.values())
                for skill, value in result.items():
                    scores[skill] = (
                        min(scores[skill], value)
                        if value >= 3
                        else min(scores[skill], 2)
                    )
    quality_limited = False
    policy_base, policy_transfer = False, False
    if version.solutions:
        base_cases = [c for c in version.cases if c.phase == "base"]
        all_cases = version.cases
        base_outputs, base_unchanged = await execute_observed(
            base.source, [c.input for c in base_cases], execute
        )
        adapted_outputs, transfer_unchanged = await execute_observed(
            transfer.source, [c.input for c in all_cases], execute
        )
        code_skills = [s for s in version.skills if s not in scores]
        verification = set(VERIFICATION) <= set(base.verification) | set(
            transfer.verification
        )
        for skill in code_skills:
            basic = len(base_outputs) == len(base_cases) and all(
                equivalent(
                    projection(o, skill, version.family),
                    projection(c.expected, skill, version.family),
                )
                for o, c in zip(base_outputs, base_cases, strict=False)
            )
            adapted = len(adapted_outputs) == len(all_cases) and all(
                equivalent(
                    projection(o, skill, version.family),
                    projection(c.expected, skill, version.family),
                )
                for o, c in zip(adapted_outputs, all_cases, strict=False)
            )
            score = 1 if base.diagnosis == DIAGNOSIS.get(version.family) else 0
            if basic:
                score = 2
                if adapted and (verification or version.test_policy):
                    score = 3
                    if base_unchanged and transfer_unchanged:
                        score = 4
            if (
                version.family == "X1"
                and version.grade == "middle"
                and skill == "language_algorithms"
            ):
                # Линейную сложность нельзя доказать результатами нескольких входов.
                # Непроверенное дополнительное требование не даёт уровень 4.
                score = min(score, 3)
                quality_limited = True
            if version.test_policy and skill == version.test_policy.skill:
                policy_base, policy_transfer = basic, adapted
            scores[skill] = score
            base_ok = base_ok and basic
            transfer_ok = transfer_ok and adapted
    evaluation = None
    if version.test_policy:
        evaluation = await CandidateTestEvaluator(execute).evaluate(version, base.tests)
        scores = apply_test_rubric(
            scores,
            version,
            evaluation,
            base_correct=policy_base,
            transfer_correct=policy_transfer,
        )
    return FamilyGrade(
        scores=scores,
        base_correct=base_ok,
        transfer_correct=transfer_ok,
        tests_valid=all(evaluation.valid_cases)
        if evaluation and evaluation.valid_cases
        else None,
        mandatory_tests_met=evaluation.mandatory_met if evaluation else None,
        quality_limited=quality_limited,
    )
