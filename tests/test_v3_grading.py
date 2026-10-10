"""Регрессии новой рубрики и отдельных доказательств; не результаты людей."""

import asyncio
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.assessment.runner import V3ExecutionRequest, V3ExecutionResult
from app.assessment.v3_grading import (
    evaluate_observations,
    family_evidence,
    grade_v3,
    package_score,
)
from app.assessment.v3_models import V3Assertion, V3Bank, V3Case
from runner.v3_sql import bind_query


@pytest.mark.parametrize(
    ("values", "score"),
    [
        ([False, False, False, False, False], 0),
        ([True, False, True, True, True], 1),
        ([True, True, False, True, True], 2),
        ([True, True, True, False, True], 2),
        ([True, True, True, True, False], 3),
        ([True, True, True, True, True], 4),
    ],
)
def test_v3_package_decisions(values: list[bool], score: int) -> None:
    results = list(zip("AABCD", values, strict=True))
    # Сто лёгких D не закрывают ни одну обязательную ошибку B/C.
    assert package_score(results + [("D", True)] * 100) == score


def test_linked_tasks_keep_one_family_per_skill() -> None:
    evidence = family_evidence(
        [
            ("X1", {"language_algorithms": 4}),
            ("X1", {"sql_data": 3}),
            ("X1", {"sql_data": 2}),
            ("X3", {"sql_data": 4}),
        ]
    )
    assert evidence == {
        "X1": {"language_algorithms": 4, "sql_data": 2},
        "X3": {"sql_data": 4},
    }


def test_secondary_skill_uses_independent_observation() -> None:
    cases = []
    observations: dict[str, JsonValue] = {}
    for i, pack in enumerate("AABCD"):
        case = V3Case.model_validate(
            {
                "id": f"test-{i}",
                "pack": pack,
                "phase": "base",
                "seed": 1729,
                "scenario": {},
                "assertions": [
                    V3Assertion(
                        path=["status_code"],
                        expected=202,
                        requirement_id="http",
                        skill="http_api",
                    ).model_dump(),
                    V3Assertion(
                        path=["writes"],
                        expected=0,
                        requirement_id="signature",
                        skill="security_validation",
                        critical="unsigned_event",
                    ).model_dump(),
                ],
            }
        )
        cases.append(case)
        observations[case.id] = {"status_code": 202, "writes": 1 if pack == "C" else 0}
    result = evaluate_observations(cases, observations)
    assert result.task_score == 2
    assert result.scores == {"http_api": 4, "security_validation": 2}
    assert result.critical_violations == ["unsigned_event"]


@pytest.mark.parametrize(
    "state", ["environment_error", "review_required", "invalid_item"]
)
def test_non_numeric_states_do_not_create_zero(state: str) -> None:
    case = V3Case.model_validate(
        {
            "id": "state",
            "pack": "A",
            "phase": "base",
            "seed": 1729,
            "scenario": {},
            "assertions": [
                V3Assertion(
                    path=["value"], expected=1, requirement_id="one", skill="sql_data"
                ).model_dump()
            ],
        }
    )
    result = evaluate_observations([case], {"state": {"status": state}})
    assert result.status == state
    assert result.task_score is None and result.scores == {}


async def test_missing_submission_never_calls_runtime() -> None:
    bank = V3Bank.model_validate_json(
        await asyncio.to_thread(Path("bank/private/v3.json").read_bytes)
    )

    async def unexpected(request: V3ExecutionRequest) -> V3ExecutionResult:
        raise AssertionError("Missing evidence must not execute")

    absent = await grade_v3(bank.cards[0], "", "", 1729, unexpected)
    unfinished = await grade_v3(
        bank.cards[0], "def totals(): pass", "", 1729, unexpected
    )
    assert absent.status == "not_submitted"
    assert unfinished.status == "incomplete"
    assert absent.task_score is None and unfinished.task_score is None


def test_sql_binds_values_outside_literals() -> None:
    query, params = bind_query(
        "SELECT ':tenant', 2::bigint WHERE :tenant=:tenant -- :other\n", {"tenant": 7}
    )
    assert query == "SELECT ':tenant', 2::bigint WHERE $1=$1 -- :other"
    assert params == [7]


@pytest.mark.parametrize(
    "source", ["SELECT 1; SELECT 2", "SELECT 1\n\\! cat /etc/passwd"]
)
def test_sql_meta_commands_and_multiple_statements_rejected(source: str) -> None:
    with pytest.raises(ValueError):
        bind_query(source, {})


def test_sql_plpgsql_body_is_one_statement() -> None:
    source = (
        "CREATE FUNCTION apply_event(a bigint) RETURNS "
        "text LANGUAGE plpgsql AS $$ BEGIN RETURN 'ok'; "
        "END; $$;"
    )
    result, values = bind_query(source, {})
    assert "RETURN 'ok'; END;" in result
    assert values == []


def test_runner_request_cannot_contain_closed_expectations() -> None:
    with pytest.raises(ValueError):
        V3ExecutionRequest(
            task_id="Y3-J",
            language="sql",
            source="SELECT 1",
            scenarios=[{"expected": [[1]]}],
        )
