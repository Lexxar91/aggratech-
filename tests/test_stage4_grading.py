import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.assessment.bank_models import FullBankVersion, load_bank
from app.assessment.grading import DIAGNOSIS, VERIFICATION, grade_family, selected_task
from app.assessment.policy import check_calendar, decide
from app.assessment.runner import (
    PYTHON_IMAGE,
    ExecutionRequest,
    ExecutionResult,
    RunnerClient,
    RunnerUnavailable,
)
from app.assessment.runtime_bank import admitted_bank
from app.assessment.schemas import TaskAnswer
from app.core.config import Settings
from app.core.errors import ApiError

BANK = load_bank(Path("bank/private/full.json"))
NOW = datetime(2026, 10, 9, tzinfo=UTC)


def prepared_answer(
    version: FullBankVersion, phase: str, index: int = 0, kind: str = "reference"
) -> TaskAnswer:
    task = selected_task(version, phase, index)
    structured = next(e.answer for e in task.examples if e.kind == kind) if task else {}
    source = next((s.source for s in version.solutions if s.kind == kind), "")
    return TaskAnswer(
        source=source,
        structured=structured,
        diagnosis=DIAGNOSIS.get(version.family, ""),
        verification=VERIFICATION,
        tests=version.candidate_tests,
    )


def evidence(form: str = "X") -> dict[str, dict[str, int]]:
    return {
        v.family: {s: 4 for s in v.skills}
        for v in BANK.versions
        if v.grade == "junior" and v.family.startswith(form)
    }


@pytest.mark.parametrize("grade", ["junior", "middle"])
def test_four_outcomes_and_critical_not_compensated(grade: str) -> None:
    complete = evidence()
    assert decide(grade, complete, b_completed=True)[0] == "confirmed"
    complete["X5"]["sql_data"] = 2
    outcome, score, _ = decide(grade, complete, b_completed=True)
    assert outcome == "not_confirmed" and score is not None and score > 90
    assert decide(grade, complete, b_completed=False)[0] == "insufficient"
    assert (
        decide(grade, complete, b_completed=True, review_required=True)[0]
        == "review_required"
    )
    del complete["X5"]
    assert decide(grade, complete, b_completed=True)[0] == "insufficient"


def test_no_repeat_family_or_a_only_confirmation() -> None:
    only_a = {k: v for k, v in evidence().items() if k[-1] in "1234"}
    assert decide("junior", only_a, b_completed=True)[0] == "insufficient"
    only_a["Y1"] = {"sql_data": 4}
    only_a["Y2"] = {"http_api": 4, "security_validation": 4}
    only_a["Y3"] = {"debug_reliability": 4}
    assert decide("junior", only_a, b_completed=True)[0] == "insufficient"
    with pytest.raises(ValueError):
        decide("junior", {"X1": {"sql_data": True}}, b_completed=True)


@pytest.mark.parametrize("days,allowed", [(6.999, False), (7, True), (7.001, True)])
def test_retry_boundary(days: float, allowed: bool) -> None:
    def attempt() -> None:
        check_calendar(
            NOW + timedelta(days=days),
            grade="junior",
            completed=[("junior", NOW, False)],
            published_grade=None,
            published_at=None,
        )

    if allowed:
        attempt()
    else:
        with pytest.raises(ApiError, match="7 дней"):
            attempt()


@pytest.mark.parametrize("days,allowed", [(29.999, False), (30, True)])
def test_publication_boundary(days: float, allowed: bool) -> None:
    if allowed:
        check_calendar(
            NOW + timedelta(days=days),
            grade="middle",
            completed=[],
            published_grade="junior",
            published_at=NOW,
        )
    else:
        with pytest.raises(ApiError, match="30 дней"):
            check_calendar(
                NOW + timedelta(days=days),
                grade="middle",
                completed=[],
                published_grade="junior",
                published_at=NOW,
            )


def test_adjacent_before_publication_two_cycles_and_technical_exemption() -> None:
    check_calendar(
        NOW,
        grade="middle",
        completed=[("junior", NOW, False)],
        published_grade=None,
        published_at=None,
    )
    with pytest.raises(ApiError, match="двух"):
        check_calendar(
            NOW,
            grade="middle",
            completed=[("junior", NOW, False), ("middle", NOW, False)],
            published_grade=None,
            published_at=None,
        )
    check_calendar(
        NOW + timedelta(days=30),
        grade="middle",
        completed=[("junior", NOW, False), ("middle", NOW, False)],
        published_grade=None,
        published_at=None,
    )
    check_calendar(
        NOW,
        grade="middle",
        completed=[("middle", NOW, True), ("middle", NOW, True)],
        published_grade=None,
        published_at=None,
    )


def test_current_receipt_demo_only() -> None:
    _, report = admitted_bank(Settings(), "demo")
    assert report.admission_status == "not_admitted"
    with pytest.raises(ApiError):
        admitted_bank(Settings(), "credit")
    with pytest.raises(ApiError):
        admitted_bank(Settings(), "anything")


@pytest.mark.runner
@pytest.mark.parametrize(
    "version", BANK.versions, ids=lambda v: f"{v.family}-{v.grade}"
)
async def test_runtime_rubric_reference_all_versions(version: FullBankVersion) -> None:
    runner = RunnerClient(Settings())
    try:
        result = await grade_family(
            version,
            prepared_answer(version, "base"),
            prepared_answer(version, "transfer"),
            0,
            runner.execute,
        )
        assert set(result.scores) == set(version.skills)
        assert all(score >= 3 for score in result.scores.values()), result
        assert result.base_correct and result.transfer_correct
        if version.test_policy:
            assert result.tests_valid and result.mandatory_tests_met
    finally:
        await runner.close()


@pytest.mark.runner
@pytest.mark.parametrize(
    "version",
    [v for v in BANK.versions if v.solutions],
    ids=lambda v: f"{v.family}-{v.grade}",
)
async def test_runtime_unadapted_and_bad_candidate_tests(
    version: FullBankVersion,
) -> None:
    runner = RunnerClient(Settings())
    try:
        base = prepared_answer(version, "base")
        transfer = prepared_answer(version, "transfer")
        transfer.source = next(
            s.source for s in version.solutions if s.kind == "unadapted"
        )
        result = await grade_family(version, base, transfer, 0, runner.execute)
        assert any(score <= 2 for score in result.scores.values())
        if version.test_policy:
            transfer = prepared_answer(version, "transfer")
            base.tests = []
            result = await grade_family(version, base, transfer, 0, runner.execute)
            assert result.scores["language_algorithms"] <= 2
            assert result.scores["http_api"] >= 3
    finally:
        await runner.close()


@pytest.mark.parametrize(
    "status", ["candidate_error", "timeout", "output_limit", "runtime_error"]
)
async def test_execution_failures_are_not_infrastructure_scores(status: str) -> None:
    version = BANK.versions[0]

    async def execute(request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult.model_validate(
            {
                "status": status,
                "outputs": [],
                "runtime_image": PYTHON_IMAGE,
                "duration_ms": 0,
            }
        )

    if status == "runtime_error":
        with pytest.raises(RunnerUnavailable):
            await grade_family(
                version,
                prepared_answer(version, "base"),
                prepared_answer(version, "transfer"),
                0,
                execute,
            )
    else:
        result = await grade_family(
            version,
            prepared_answer(version, "base"),
            prepared_answer(version, "transfer"),
            0,
            execute,
        )
        assert result.scores["language_algorithms"] == 1


@pytest.mark.parametrize(
    "version",
    [v for v in BANK.versions if not v.solutions],
    ids=lambda v: f"{v.family}-{v.grade}",
)
async def test_structured_partial_and_transfer_are_not_confirmation(
    version: FullBankVersion,
) -> None:
    async def execute(request: ExecutionRequest) -> ExecutionResult:
        raise AssertionError("Structured grading must not execute code")

    base = prepared_answer(version, "base", kind="partial")
    transfer = prepared_answer(version, "transfer", kind="partial")
    result = await grade_family(version, base, transfer, 0, execute)
    assert all(x <= 2 for x in result.scores.values())
    result = await grade_family(
        version, prepared_answer(version, "base"), TaskAnswer(), 0, execute
    )
    assert all(x <= 2 for x in result.scores.values())


@pytest.mark.runner
@pytest.mark.parametrize("grade", ["junior", "middle"])
async def test_http_delay_error_does_not_erase_algorithm(grade: str) -> None:
    version = next(v for v in BANK.versions if v.family == "Y4" and v.grade == grade)
    base = prepared_answer(version, "base")
    transfer = prepared_answer(version, "transfer")
    for answer in (base, transfer):
        answer.source += """
_original = solve
def solve(data):
    result = _original(data)
    result["waits"] = [-1]
    return result
"""
    runner = RunnerClient(Settings())
    try:
        result = await grade_family(version, base, transfer, 0, runner.execute)
        assert result.scores["language_algorithms"] >= 3
        assert result.scores["http_api"] <= 2
    finally:
        await runner.close()


@pytest.mark.parametrize("module", ["app.worker", "app.tools.assessment_admin"])
def test_standalone_process_registers_foreign_keys(module: str) -> None:
    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module}; "
            "from app.core.database import Base; "
            "assert {'users', 'assessment_cycles'} <= "
            "{table.name for table in Base.metadata.sorted_tables}",
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
