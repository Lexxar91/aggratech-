"""Состояния v3 на PostgreSQL; синтетический gate используется только test-БД."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment import jobs, service
from app.assessment.admin import intervene
from app.assessment.models import AssessmentCycle, FamilyExposure
from app.assessment.runtime_bank import credit_admission_valid
from app.assessment.v3_models import V3_METHODOLOGY, V3Bank, V3Card, V3TaskGrade
from app.core.config import Settings
from app.notifications.models import BackgroundJob
from app.notifications.queue import claim, utc_now
from tests.test_auth_profiles import auth_app as _auth_app
from tests.test_auth_profiles import client as _client
from tests.test_stage4_cycles import candidate as _candidate
from tests.test_v3_admission import synthetic_report

auth_app = _auth_app
client = _client
candidate = _candidate
pytestmark = pytest.mark.integration


@pytest.fixture
def v3_settings(
    auth_app: FastAPI, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings: Settings = auth_app.state.settings
    bank = V3Bank.model_validate_json(Path("bank/private/v3.json").read_bytes())
    report = synthetic_report()
    settings.assessment_bank = Path("bank/private/v3.json")
    settings.assessment_report = tmp_path / "synthetic-unit-report.json"
    settings.assessment_report.write_text(report.model_dump_json())
    monkeypatch.setattr(service, "admitted_bank", lambda settings, mode: (bank, report))


@pytest.mark.parametrize(
    "grade,form", [("junior", "X"), ("middle", "X"), ("junior", "Y"), ("middle", "Y")]
)
async def test_explicit_form_language_and_one_exposure_per_family(
    candidate: httpx.AsyncClient,
    v3_settings: None,
    sessions: async_sessionmaker[AsyncSession],
    grade: str,
    form: str,
) -> None:
    response = await candidate.post(
        "/api/v1/assessment/cycles",
        json={"grade": grade, "form": form, "mode": "credit"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["form"] == form and len(data["tasks"]) == 5
    assert {t["language"] for t in data["tasks"]} == {"python", "sql"}
    assert all(t["common_contract"] and t["input"] is None for t in data["tasks"])
    assert all(
        t["diagnosis_options"] == [] and t["answer_options"] == {}
        for t in data["tasks"]
    )
    assert (
        "developer_notes" not in response.text
        and "parameter_manifests" not in response.text
    )
    cycle_id = UUID(data["id"])
    async with sessions() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert (
            cycle and len(cycle.materials) == 7 and cycle.methodology == V3_METHODOLOGY
        )
        assert cycle.admission["review_passed"] is False
        assert credit_admission_valid(cycle)
        shown = list(
            await db.scalars(
                select(FamilyExposure).where(FamilyExposure.cycle_id == cycle_id)
            )
        )
        assert {r.family for r in shown} == {f"{form}{i}" for i in range(1, 5)}
    rejected = await candidate.post(f"/api/v1/assessment/cycles/{cycle_id}/submit/A")
    assert (
        rejected.status_code == 409 and rejected.json()["code"] == "answers_incomplete"
    )


async def test_deadline_preserves_draft_and_no_zero_with_operator_recovery(
    candidate: httpx.AsyncClient,
    v3_settings: None,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    response = await candidate.post(
        "/api/v1/assessment/cycles",
        json={"grade": "junior", "form": "X", "mode": "demo"},
    )
    data = response.json()
    cycle_id = UUID(data["id"])
    task = data["tasks"][0]
    draft = "def totals(rows, paid_only=False):\n    return []\n"
    saved = await candidate.put(
        f"/api/v1/assessment/cycles/{cycle_id}/answers/{task['family']}",
        json={"revision": 0, "step": "base", "answer": {"source": draft}},
    )
    assert saved.status_code == 200
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        cycle.a_deadline = utc_now() - timedelta(seconds=1)
    expired = await candidate.get(f"/api/v1/assessment/cycles/{cycle_id}")
    assert expired.json()["state"] == "expired"
    assert expired.json()["result"]["outcome"] == "insufficient"
    assert expired.json()["result"]["total"] is None
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        rows = await service.answers(db, cycle_id)
        selected = next(r for r in rows if r.family == task["family"])
        assert selected.draft["source"] == draft and selected.base is None
        assert selected.grading_status == "incomplete" and selected.scores == {}
        await intervene(
            db,
            cycle_id,
            action="extend",
            reason="Confirmed test infrastructure outage",
            reviewer="unit-test-operator",
            now=utc_now(),
            seconds=300,
        )
    reopened = await candidate.get(f"/api/v1/assessment/cycles/{cycle_id}")
    assert reopened.json()["state"] == "A"
    assert (
        next(t for t in reopened.json()["tasks"] if t["family"] == task["family"])[
            "draft"
        ]["source"]
        == draft
    )


@pytest.mark.parametrize(
    "status", ["environment_error", "invalid_item", "review_required", "incomplete"]
)
async def test_non_numeric_task_state_prevents_confirmation(
    candidate: httpx.AsyncClient,
    v3_settings: None,
    sessions: async_sessionmaker[AsyncSession],
    status: str,
) -> None:
    response = await candidate.post(
        "/api/v1/assessment/cycles",
        json={"grade": "middle", "form": "Y", "mode": "credit"},
    )
    cycle_id = UUID(response.json()["id"])
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        cycle.b_submitted_at = utc_now()
        for row in await service.answers(db, cycle_id):
            row.grading_status = "completed"
            row.scores = {r.skill: 4 for r in bank_card(cycle, row.family).requirements}
        rows = await service.answers(db, cycle_id)
        rows[0].grading_status = status
        rows[0].scores = {}
        await service.finalize_result(db, cycle, utc_now())
        assert cycle.outcome in {"insufficient", "review_required"}
        assert service.result_view(cycle).verified is False


def bank_card(cycle: AssessmentCycle, task_id: str) -> V3Card:
    """Типизированный снимок; эти fixture-баллы не используются сквозной приёмкой."""
    card = service.material(cycle, task_id)
    assert isinstance(card, V3Card)
    return card


@pytest.mark.parametrize("dangerous", [False, True])
async def test_v3_requirements_and_flags_survive_commit_and_new_session(
    candidate: httpx.AsyncClient,
    v3_settings: None,
    sessions: async_sessionmaker[AsyncSession],
    dangerous: bool,
) -> None:
    """Fixture только test-БД: проверяет JSONB после autoflush и нового чтения."""
    response = await candidate.post(
        "/api/v1/assessment/cycles",
        json={"grade": "middle", "form": "Y", "mode": "credit"},
    )
    assert response.status_code == 200
    cycle_id = UUID(response.json()["id"])
    flags = ["unsigned_event"] if dangerous else []
    expected_actions: set[tuple[str, str, str]] = set()
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        cycle.b_submitted_at = utc_now()
        rows = await service.answers(db, cycle_id)
        for row in rows:
            card = bank_card(cycle, row.family)
            row.grading_status = "completed"
            row.scores = {r.skill: 4 for r in card.requirements}
            row.grading_detail = {
                "requirement_results": {r.id: True for r in card.requirements}
            }
            expected_actions.update(
                (card.task_id, r.skill, r.action) for r in card.requirements
            )
        rows[0].grading_detail = {
            **rows[0].grading_detail,
            "critical_violations": flags,
        }
        await service.finalize_result(db, cycle, utc_now())

    async with sessions() as db:
        stored = await db.get(AssessmentCycle, cycle_id)
        assert stored
        assert stored.result["critical_violations"] == flags
        assert stored.outcome == ("not_confirmed" if dangerous else "confirmed")
        view = service.result_view(stored)
        assert view.requirements
        assert {
            (r.task_id, r.skill, r.action) for r in view.requirements
        } == expected_actions
        assert all(
            r.passed is True and r.status == "completed" for r in view.requirements
        )

    read_back = await candidate.get(f"/api/v1/assessment/cycles/{cycle_id}")
    assert read_back.status_code == 200
    assert len(read_back.json()["result"]["requirements"]) == len(expected_actions)
    published = await candidate.post(f"/api/v1/assessment/cycles/{cycle_id}/publish")
    if dangerous:
        assert published.status_code == 409
    else:
        assert published.status_code == 200
        assert (
            published.json()["requirements"]
            == read_back.json()["result"]["requirements"]
        )
        profile = await candidate.get("/api/v1/candidate/profile")
        assert (
            profile.json()["assessment"]["requirements"]
            == published.json()["requirements"]
        )


async def test_dangerous_violation_blocks_high_score_and_demo_cannot_become_credit(
    candidate: httpx.AsyncClient,
    v3_settings: None,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    response = await candidate.post(
        "/api/v1/assessment/cycles",
        json={"grade": "junior", "form": "X", "mode": "credit"},
    )
    cycle_id = UUID(response.json()["id"])
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        cycle.b_submitted_at = utc_now()
        for row in await service.answers(db, cycle_id):
            row.grading_status = "completed"
            row.scores = {r.skill: 4 for r in bank_card(cycle, row.family).requirements}
        first = (await service.answers(db, cycle_id))[0]
        first.grading_detail = {"critical_violations": ["foreign_data"]}
        await service.finalize_result(db, cycle, utc_now())
        assert cycle.result["total"] == 100 and cycle.outcome == "not_confirmed"
        assert not service.result_view(cycle).verified
        cycle.admission = {
            **cycle.admission,
            "origin": "live_demo",
            "review_passed": True,
        }
        assert not credit_admission_valid(cycle)


async def test_v3_worker_extends_short_lease_before_execution(
    candidate: httpx.AsyncClient,
    v3_settings: None,
    auth_app: FastAPI,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = await candidate.post(
        "/api/v1/assessment/cycles",
        json={"grade": "junior", "form": "X", "mode": "credit"},
    )
    assert response.status_code == 200
    identifier = UUID(response.json()["id"])
    async with sessions.begin() as db:
        await db.execute(delete(BackgroundJob))
        row = (await service.answers(db, identifier))[0]
        row.base = {"source": "test-only"}
        row.transfer = {"source": "test-only"}
        row.finalized_at = utc_now()
        await service.queue_answer(db, row, utc_now())
        claimed = await claim(db, now=utc_now(), lease_seconds=60, max_attempts=3)
    assert claimed

    async def inspected(*args: object, **kwargs: object) -> V3TaskGrade:
        async with sessions() as db:
            running = await db.get(BackgroundJob, claimed.id)
            assert running and running.lease_until
            assert running.lease_until >= utc_now() + timedelta(seconds=290)
        return V3TaskGrade(status="invalid_item")

    monkeypatch.setattr(jobs, "grade_v3", inspected)
    await jobs.process_assessment(sessions, auth_app.state.settings, claimed)
    async with sessions() as db:
        completed = await db.get(BackgroundJob, claimed.id)
        assert completed and completed.status == "succeeded"
        assert completed.lease_until is None
