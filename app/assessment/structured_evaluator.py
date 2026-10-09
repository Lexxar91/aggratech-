"""Оценка объявленных признаков ответа, без сравнения текста SQL с эталоном."""

import json

from pydantic import JsonValue

from app.assessment.bank_models import Skill, StructuredTask


def equivalent(actual: JsonValue, expected: JsonValue, unordered: bool = False) -> bool:
    """Сравнивает JSON с сохранением типов; набор строк не зависит от их порядка."""

    def canonical(value: JsonValue) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)

    if unordered and isinstance(actual, list) and isinstance(expected, list):
        return sorted(map(canonical, actual)) == sorted(map(canonical, expected))
    return canonical(actual) == canonical(expected)


def evaluate_structured(
    task: StructuredTask, answer: dict[str, JsonValue]
) -> dict[Skill, int]:
    """Возвращает отдельные оценки навыков по наблюдаемым действиям и зависимостям."""
    satisfied: dict[str, bool] = {}
    for rule in task.rules:
        satisfied[rule.field] = (
            rule.field in answer
            and any(
                equivalent(answer[rule.field], value, rule.unordered)
                for value in rule.accepted
            )
            and (rule.requires is None or satisfied.get(rule.requires, False))
        )
    scores: dict[Skill, int] = {rule.skill: 0 for rule in task.rules}
    for rule in task.rules:
        if satisfied[rule.field] and (
            rule.requires is None or satisfied.get(rule.requires, False)
        ):
            scores[rule.skill] += rule.points
    return scores
