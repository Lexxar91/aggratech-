"""Измеримая проверка 2–3 JSON-случаев X4/Y4 через изолированный runner."""

import json
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import Field, JsonValue, ValidationError

from app.assessment.bank_models import FullBankVersion, MaterialModel
from app.assessment.runner import ExecutionRequest, ExecutionResult, RunnerUnavailable
from app.assessment.structured_evaluator import equivalent

Execute = Callable[[ExecutionRequest], Awaitable[ExecutionResult]]


class CandidateCase(MaterialModel):
    """Один ограниченный случай, без произвольного проверяющего кода."""

    input: dict[str, JsonValue]
    expected: dict[str, JsonValue]


class TestEvaluation(MaterialModel):
    """Служебные подпризнаки; исходники и подготовленные входы сюда не входят."""

    status: Literal["completed", "invalid", "incomplete"]
    valid_cases: list[bool] = Field(default_factory=list)
    detected_classes: list[str] = Field(default_factory=list)
    mandatory_met: bool = False
    additional_met: bool = False
    reason: str | None = None


def validate_candidate_input(
    version: FullBankVersion, value: dict[str, JsonValue]
) -> None:
    """Ограничивает граф страниц и сценарий HTTP объявленным контрактом грейда."""

    def integer(item: JsonValue, maximum: int, minimum: int = 0) -> bool:
        return (
            isinstance(item, int)
            and not isinstance(item, bool)
            and minimum <= item <= maximum
        )

    if version.family == "X4":
        allowed = {"start", "pages"} | (
            {"max_items"} if version.grade == "junior" else {"detect_cycles"}
        )
        pages, start = value.get("pages"), value.get("start")
        if (
            set(value) - allowed
            or not isinstance(pages, dict)
            or not 1 <= len(pages) <= 12
        ):
            raise ValueError("invalid_pages")
        if not isinstance(start, str) or start not in pages:
            raise ValueError("invalid_start")
        if "max_items" in value and not integer(value["max_items"], 100):
            raise ValueError("invalid_max_items")
        if "detect_cycles" in value and type(value["detect_cycles"]) is not bool:
            raise ValueError("invalid_detect_cycles")
        for page in pages.values():
            if not isinstance(page, dict) or set(page) != {"items", "has_more", "next"}:
                raise ValueError("invalid_page")
            items = page["items"]
            if not isinstance(items, list) or len(items) > 20:
                raise ValueError("invalid_items")
            if type(page["has_more"]) is not bool or not isinstance(page["next"], str):
                raise ValueError("invalid_page_cursor")
            if page["has_more"] and page["next"] not in pages:
                raise ValueError("missing_next_page")
            for item in items:
                if not isinstance(item, dict) or set(item) != {"id", "value"}:
                    raise ValueError("invalid_item")
                if not isinstance(item["id"], str) or not integer(
                    item["value"], 10000, -10000
                ):
                    raise ValueError("invalid_item_value")
        cursor, seen = start, set()
        while cursor not in seen:
            seen.add(cursor)
            page = pages[cursor]
            assert isinstance(page, dict)
            if not page["has_more"]:
                return
            next_cursor = page["next"]
            assert isinstance(next_cursor, str)
            cursor = next_cursor
        if value.get("detect_cycles") is not True:
            raise ValueError("cycle_outside_contract")
    elif version.family == "Y4":
        allowed = {"responses", "max_attempts", "retryable"}
        if version.grade == "middle":
            allowed |= {"method_safe", "budget"}
        if set(value) - allowed or not integer(value.get("max_attempts"), 5, 1):
            raise ValueError("invalid_attempt_limit")
        responses = value.get("responses")
        if not isinstance(responses, list) or not 1 <= len(responses) <= 8:
            raise ValueError("invalid_responses")
        if not isinstance(value.get("retryable"), list) or value["retryable"] not in (
            [503],
            [503, 429],
        ):
            raise ValueError("invalid_retryable")
        if "budget" in value and not integer(value["budget"], 100):
            raise ValueError("invalid_budget")
        if "method_safe" in value and type(value["method_safe"]) is not bool:
            raise ValueError("invalid_method_safety")
        for response in responses:
            if not isinstance(response, dict) or set(response) != {"status", "delay"}:
                raise ValueError("invalid_response")
            if type(response["status"]) is not int or response["status"] not in (
                200,
                400,
                429,
                503,
            ):
                raise ValueError("invalid_status")
            if not integer(response["delay"], 10) or (
                version.grade == "junior" and response["delay"] != 0
            ):
                raise ValueError("invalid_delay")
    else:
        raise ValueError("candidate_tests_only_x4_y4")


class CandidateTestEvaluator:
    """Проверяет корректность тестов прежде обнаружения заранее заданных ошибок."""

    def __init__(self, execute: Execute) -> None:
        self.execute = execute

    async def evaluate(
        self, version: FullBankVersion, raw_cases: list[dict[str, JsonValue]]
    ) -> TestEvaluation:
        """Различает неверный ответ, найденную ошибку и инфраструктурный сбой."""
        try:
            if version.test_policy is None or not 2 <= len(raw_cases) <= 3:
                raise ValueError("two_or_three_cases_required")
            if len(json.dumps(raw_cases, allow_nan=False).encode()) > 16384:
                raise ValueError("cases_too_large")
            cases = [CandidateCase.model_validate(case) for case in raw_cases]
            for case in cases:
                validate_candidate_input(version, case.input)
        except ValueError, ValidationError:
            return TestEvaluation(status="invalid", reason="invalid_test_contract")

        valid = [True] * len(cases)
        correct = [
            s for s in version.solutions if s.kind in ("reference", "alternative")
        ]
        mistakes = [s for s in version.solutions if s.kind == "mistake"]
        if len(correct) != 2 or len(mistakes) != 3:
            return TestEvaluation(status="incomplete", reason="invalid_materials")
        detected: set[str] = set()
        try:
            for solution in correct + mistakes:
                result = await self.execute(
                    ExecutionRequest(
                        source=solution.source, inputs=[case.input for case in cases]
                    )
                )
                if result.status != "completed" or len(result.outputs) != len(cases):
                    return TestEvaluation(
                        status="incomplete", reason="execution_incomplete"
                    )
                matches = [
                    equivalent(out, case.expected)
                    for out, case in zip(result.outputs, cases, strict=True)
                ]
                if solution.kind in ("reference", "alternative"):
                    valid = [a and b for a, b in zip(valid, matches, strict=True)]
                elif solution.error_class and any(
                    ok and not match for ok, match in zip(valid, matches, strict=True)
                ):
                    detected.add(solution.error_class)
        except RunnerUnavailable:
            return TestEvaluation(status="incomplete", reason="runner_unavailable")
        policy = version.test_policy
        return TestEvaluation(
            status="completed",
            valid_cases=valid,
            detected_classes=sorted(detected),
            mandatory_met=all(valid) and set(policy.mandatory) <= detected,
            additional_met=all(valid) and policy.additional in detected,
        )


def apply_test_rubric(
    scores: dict[str, int],
    version: FullBankVersion,
    result: TestEvaluation,
    *,
    base_correct: bool,
    transfer_correct: bool,
) -> dict[str, int]:
    """Ограничивает только связанный навык; не добавляет баллов или доказательств."""
    if result.status == "incomplete":
        raise RunnerUnavailable("candidate_test_evaluation_incomplete")
    if version.test_policy is None:
        raise ValueError("missing_test_policy")
    updated = dict(scores)
    cap = 4 if result.additional_met else 3
    if not (base_correct and transfer_correct and result.mandatory_met):
        cap = 2
    skill = version.test_policy.skill
    updated[skill] = min(updated[skill], cap)
    return updated
