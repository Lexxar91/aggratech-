import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment import jobs, router, service
from app.assessment.admin import intervene
from app.assessment.bank_models import FullBankVersion
from app.assessment.grading import FamilyGrade
from app.assessment.models import AssessmentAnswer, AssessmentCycle, FamilyExposure
from app.assessment.runner import RunnerUnavailable
from app.auth.models import User
from app.core.config import Settings
from app.notifications.models import AuditEvent, BackgroundJob
from app.notifications.queue import claim, utc_now
from app.worker import process_one
from tests.test_auth_profiles import auth_app as _auth_app
from tests.test_auth_profiles import client as _client
from tests.test_auth_profiles import login, register
from tests.test_stage4_grading import prepared_answer

auth_app = _auth_app
client = _client

pytestmark = pytest.mark.integration
SURVEY = {
    "industry": "IT",
    "specialization": "backend",
    "stack": ["Python", "SQL"],
    "experience_years": 1,
    "instructions_accepted": True,
}


@pytest.fixture
async def candidate(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> AsyncIterator[httpx.AsyncClient]:
    user_id = await register(client)
    async with sessions.begin() as db:
        await db.execute(
            update(User).where(User.id == user_id).values(email_verified_at=utc_now())
        )
        # Почта не относится к этим проверкам; регистрационные задания исключены.
        await db.execute(update(BackgroundJob).values(status="succeeded"))
    await login(client)
    assert (
        await client.put("/api/v1/assessment/survey", json=SURVEY)
    ).status_code == 200
    yield client


async def create(client: httpx.AsyncClient, grade: str = "junior") -> dict[str, object]:
    response = await client.post(
        "/api/v1/assessment/cycles", json={"grade": grade, "mode": "demo"}
    )
    assert response.status_code == 200, response.text
    result: dict[str, object] = response.json()
    return result


async def fix_all(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    cycle_id: UUID,
    phase: str,
) -> None:
    async with sessions() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        rows = [r for r in await service.answers(db, cycle_id) if r.phase == phase]
        payloads = [
            (r.family, r.parameter_index, service.material(cycle, r.family))
            for r in rows
        ]
    for family, index, version in payloads:
        for revision, step in enumerate(["base", "transfer"]):
            answer = prepared_answer(version, step, index)
            response = await client.post(
                f"/api/v1/assessment/cycles/{cycle_id}/answers/{family}/fix",
                json={
                    "revision": revision,
                    "step": step,
                    "answer": answer.model_dump(mode="json"),
                },
            )
            assert response.status_code == 200, response.text
    response = await client.post(f"/api/v1/assessment/cycles/{cycle_id}/submit/{phase}")
    assert response.status_code == 200, response.text


async def finish_fixture(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    cycle_id: UUID,
    *,
    successful: bool = True,
) -> None:
    # Тест состояния: оценки — fixture; реальный runner проверяется отдельно.
    await client.post(f"/api/v1/assessment/cycles/{cycle_id}/submit/A")
    await client.post(f"/api/v1/assessment/cycles/{cycle_id}/start-b")
    await client.post(f"/api/v1/assessment/cycles/{cycle_id}/submit/B")
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        assert cycle
        for row in await service.answers(db, cycle_id):
            version = service.material(cycle, row.family)
            assert isinstance(version, FullBankVersion)
            row.grading_status = "completed"
            row.scores = {s: 4 if successful else 2 for s in version.skills}
        await db.flush()
        await service.finalize_result(db, cycle, utc_now())
        await db.execute(update(BackgroundJob).values(status="succeeded"))


async def test_concurrent_creation_snapshot_private_stages_and_draft(
    candidate: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    first, second = await asyncio.gather(create(candidate), create(candidate))
    assert first["id"] == second["id"]
    cid = UUID(str(first["id"]))
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AssessmentCycle)) == 1
        assert await db.scalar(select(func.count()).select_from(FamilyExposure)) == 4
        cycle = await db.get(AssessmentCycle, cid)
        assert (
            cycle
            and len(cycle.materials) == 6
            and cycle.admission["origin"] == "live_demo"
        )
        assert len(cycle.evaluator_hash) == 64
        row = (await service.answers(db, cid))[0]
        family = row.family
    raw = (await candidate.get(f"/api/v1/assessment/cycles/{cid}")).text
    for forbidden in (
        "solutions",
        "expected_scores",
        "rubric",
        "reference",
        "candidate_tests",
        '"phase":"B"',
    ):
        assert forbidden not in raw
    data = {
        "revision": 0,
        "step": "base",
        "answer": {"source": "def solve(data):\n    return data"},
    }
    response = await candidate.put(
        f"/api/v1/assessment/cycles/{cid}/answers/{family}", json=data
    )
    assert response.status_code == 200, response.text
    restored = (await candidate.get(f"/api/v1/assessment/cycles/{cid}")).json()
    task = next(t for t in restored["tasks"] if t["family"] == family)
    assert (
        task["draft"]["source"] == "def solve(data):\n    return data"
        and task["revision"] == 1
    )
    assert (
        await candidate.put(
            f"/api/v1/assessment/cycles/{cid}/answers/{family}", json=data
        )
    ).status_code == 409
    data["revision"] = 1
    assert (
        await candidate.post(
            f"/api/v1/assessment/cycles/{cid}/answers/{family}/fix", json=data
        )
    ).status_code == 200
    data["revision"] = 2
    assert (
        await candidate.put(
            f"/api/v1/assessment/cycles/{cid}/answers/{family}", json=data
        )
    ).status_code == 409
    hidden = family[0] + "5"
    assert (
        await candidate.put(
            f"/api/v1/assessment/cycles/{cid}/answers/{hidden}", json=data
        )
    ).status_code == 409
    assert (
        await candidate.post(f"/api/v1/assessment/cycles/{cid}/start-b")
    ).status_code == 409
    assert (
        await candidate.post("/api/v1/assessment/cycles", json={"grade": "middle"})
    ).status_code == 409


async def test_credit_gate_verified_email_and_owner(
    candidate: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    response = await candidate.post(
        "/api/v1/assessment/cycles", json={"grade": "junior", "mode": "credit"}
    )
    assert (
        response.status_code == 409 and response.json()["code"] == "bank_not_admitted"
    )
    original = await create(candidate)
    await register(candidate, "other@example.com")
    await login(candidate, "other@example.com")
    assert (
        await candidate.get(f"/api/v1/assessment/cycles/{original['id']}")
    ).status_code == 404
    assert (
        await candidate.post("/api/v1/assessment/cycles", json={"grade": "junior"})
    ).status_code == 403
    assert (await candidate.get("/api/v1/assessment/cycles")).json() == []
    await register(candidate, "employer@example.com", "employer")
    await login(candidate, "employer@example.com")
    assert (await candidate.get("/api/v1/assessment/cycles")).status_code == 403


async def test_deadlines_a_b_and_expiry(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = utc_now()
    monkeypatch.setattr(router, "utc_now", lambda: start)
    cycle = await create(candidate)
    path = f"/api/v1/assessment/cycles/{cycle['id']}"
    monkeypatch.setattr(
        router, "utc_now", lambda: start + timedelta(minutes=30, microseconds=-1)
    )
    assert (await candidate.get(path)).json()["state"] == "A"
    monkeypatch.setattr(router, "utc_now", lambda: start + timedelta(minutes=30))
    response = (await candidate.get(path)).json()
    assert response["state"] == "B_ready" and response["tasks"] == []
    # B доступна несмотря на все шесть ещё не оценённых ответов.
    assert (await candidate.post(path + "/start-b")).json()["state"] == "B"
    monkeypatch.setattr(
        router, "utc_now", lambda: start + timedelta(minutes=45, microseconds=-1)
    )
    assert (await candidate.get(path)).json()["state"] == "B"
    monkeypatch.setattr(router, "utc_now", lambda: start + timedelta(minutes=45))
    assert (await candidate.get(path)).json()["state"] == "grading"
    async with sessions() as db:
        cycle_db = await db.get(AssessmentCycle, UUID(str(cycle["id"])))
        assert cycle_db and cycle_db.a_submitted_at == start + timedelta(minutes=30)
        assert cycle_db.b_submitted_at == start + timedelta(minutes=45)
        assert await db.scalar(select(func.count()).select_from(FamilyExposure)) == 6
    assert (await candidate.post(path + "/submit/B")).status_code == 200


async def test_b_start_24h_extension_keeps_exposure(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = utc_now()
    monkeypatch.setattr(router, "utc_now", lambda: now)
    cycle = await create(candidate)
    cid = UUID(str(cycle["id"]))
    path = f"/api/v1/assessment/cycles/{cid}"
    await candidate.post(path + "/submit/A")
    monkeypatch.setattr(
        router, "utc_now", lambda: now + timedelta(hours=24, microseconds=-1)
    )
    assert (await candidate.get(path)).json()["state"] == "B_ready"
    later = now + timedelta(hours=24)
    monkeypatch.setattr(router, "utc_now", lambda: later)
    expired = (await candidate.get(path)).json()
    assert (
        expired["state"] == "expired" and expired["result"]["outcome"] == "insufficient"
    )
    assert (await candidate.post(path + "/start-b")).status_code == 409
    async with sessions.begin() as db:
        await intervene(
            db,
            cid,
            action="extend",
            reason="Confirmed infrastructure incident",
            reviewer="test-operator",
            now=later,
            seconds=300,
        )
        assert await db.scalar(select(func.count()).select_from(FamilyExposure)) == 4
    assert (await candidate.post(path + "/start-b")).json()["state"] == "B"


@pytest.mark.parametrize(
    "first_grade,second_grade", [("junior", "middle"), ("middle", "junior")]
)
async def test_transition_other_form_failed_preserves_success_and_exhaustion(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    first_grade: str,
    second_grade: str,
) -> None:
    one = await create(candidate, first_grade)
    one_id = UUID(str(one["id"]))
    await finish_fixture(candidate, sessions, one_id)
    async with sessions() as db:
        row = await db.get(AssessmentCycle, one_id)
        assert row
        assert await service.published_result(db, row.user_id, owner=True) is None
    two = await create(candidate, second_grade)
    two_id = UUID(str(two["id"]))
    async with sessions() as db:
        rows = list(await db.scalars(select(AssessmentCycle)))
        assert len({r.form for r in rows}) == 2
    await finish_fixture(candidate, sessions, two_id, successful=False)
    publication = await candidate.post(f"/api/v1/assessment/cycles/{one_id}/publish")
    assert publication.status_code == 200 and publication.json()["verified"] is False
    assert (
        await candidate.post(f"/api/v1/assessment/cycles/{two_id}/publish")
    ).status_code == 409
    async with sessions() as db:
        row = await db.get(AssessmentCycle, one_id)
        assert row
        own = await service.published_result(db, row.user_id, owner=True)
        assert own and own.grade == first_grade and own.mode == "demo"
        assert await service.published_result(db, row.user_id, owner=False) is None
        assert await db.scalar(select(func.count()).select_from(FamilyExposure)) == 12
    own_profile = (await candidate.get("/api/v1/candidate/profile")).json()
    assert own_profile["assessment"]["verified"] is False
    future = utc_now() + timedelta(days=31)
    monkeypatch.setattr(router, "utc_now", lambda: future)
    response = await candidate.post(
        "/api/v1/assessment/cycles", json={"grade": second_grade}
    )
    assert response.status_code == 409 and response.json()["code"] == "bank_exhausted"


async def test_appeal_resolution_audit_and_late_job_cannot_revive(
    candidate: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    cycle = await create(candidate)
    cid = UUID(str(cycle["id"]))
    path = f"/api/v1/assessment/cycles/{cid}"
    await finish_fixture(candidate, sessions, cid)
    await candidate.post(path + "/publish")
    for _ in range(2):
        response = await candidate.post(
            path + "/appeals", json={"message": "Проверьте технический сбой оценивания"}
        )
        assert response.status_code == 200
    assert len((await candidate.get("/api/v1/assessment/appeals")).json()) == 1
    assert (await candidate.get(path)).json()["result"]["outcome"] == "review_required"
    assert (await candidate.post(path + "/publish")).status_code == 409
    async with sessions.begin() as db:
        await intervene(
            db,
            cid,
            action="uphold",
            reason="Checked logs: original result upheld",
            reviewer="operator",
            now=utc_now(),
        )
    assert (await candidate.get(path)).json()["result"]["outcome"] == "confirmed"
    async with sessions.begin() as db:
        await intervene(
            db,
            cid,
            action="review",
            reason="Second technical incident discovered",
            reviewer="operator",
            now=utc_now(),
        )
        await intervene(
            db,
            cid,
            action="invalidate",
            reason="Confirmed lost runtime image version",
            reviewer="operator",
            now=utc_now(),
        )
        row = await db.get(AssessmentCycle, cid)
        assert row
        await service.finalize_result(db, row, utc_now())
        assert row.state == "invalidated" and row.technical_exempt
        assert await service.published_result(db, row.user_id, owner=True) is None
        events = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "assessment_intervention")
            )
        )
        assert len(events) == 3 and all(e.safe_metadata["reason"] for e in events)


async def test_queue_redelivery_version_snapshot_and_technical_retry(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    auth_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle = await create(candidate)
    cid = UUID(str(cycle["id"]))
    path = f"/api/v1/assessment/cycles/{cid}"
    await fix_all(candidate, sessions, cid, "A")
    await candidate.post(path + "/start-b")
    await fix_all(candidate, sessions, cid, "B")
    settings: Settings = auth_app.state.settings

    # Проверяет инфраструктурный путь отказа, не подставляя балл 0.
    async def unavailable(*args: object, **kwargs: object) -> FamilyGrade:
        raise RunnerUnavailable("deliberate_test_outage")

    monkeypatch.setattr(jobs, "grade_family", unavailable)
    async with sessions.begin() as db:
        first = await claim(db, now=utc_now(), lease_seconds=60, max_attempts=3)
    assert first
    await jobs.process_assessment(sessions, settings, first)
    failed = (await candidate.get(path)).json()
    assert failed["technical_issue"] and failed["state"] == "technical_error"
    async with sessions.begin() as db:
        answer = await db.get(AssessmentAnswer, (cid, str(first.payload["family"])))
        assert answer and answer.scores == {}
        await intervene(
            db,
            cid,
            action="retry",
            reason="Runner restored after test interruption",
            reviewer="test-operator",
            now=utc_now(),
        )

    async def correct(version: object, *args: object, **kwargs: object) -> FamilyGrade:
        from app.assessment.bank_models import FullBankVersion

        assert isinstance(version, FullBankVersion)
        return FamilyGrade(
            scores={s: 4 for s in version.skills},
            base_correct=True,
            transfer_correct=True,
        )

    monkeypatch.setattr(jobs, "grade_family", correct)
    # Старый claim после retry не должен затереть новое поколение.
    await jobs.process_assessment(sessions, settings, first)
    for _ in range(15):
        if not await process_one(sessions, settings):
            break
    completed = (await candidate.get(path)).json()
    assert (
        completed["state"] == "completed"
        and completed["result"]["outcome"] == "confirmed"
    )
    async with sessions.begin() as db:
        row = await db.get(AssessmentCycle, cid)
        assert row and row.technical_exempt
        assert len(await service.answers(db, cid)) == 6
        assert await db.scalar(select(func.count()).select_from(FamilyExposure)) == 6


async def test_expired_worker_lease_recovers_same_answer(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    auth_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cycle = await create(candidate)
    cid = UUID(str(cycle["id"]))
    await fix_all(candidate, sessions, cid, "A")
    now = utc_now()
    async with sessions.begin() as db:
        lost = await claim(db, now=now, lease_seconds=5, max_attempts=3)
        assert lost
        await db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == lost.id)
            .values(lease_until=now - timedelta(seconds=1))
        )
    async with sessions.begin() as db:
        recovered = await claim(db, now=now, lease_seconds=60, max_attempts=3)
    assert (
        recovered
        and recovered.id == lost.id
        and recovered.claim_token != lost.claim_token
    )

    async def correct(version: object, *args: object, **kwargs: object) -> FamilyGrade:
        return FamilyGrade(scores={"language_algorithms": 3, "sql_data": 3})

    monkeypatch.setattr(jobs, "grade_family", correct)
    await jobs.process_assessment(sessions, auth_app.state.settings, recovered)
    await jobs.process_assessment(sessions, auth_app.state.settings, lost)
    async with sessions() as db:
        row = await db.get(BackgroundJob, lost.id)
        assert row and row.status == "succeeded" and row.attempt_count == 2
        events = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "assessment_family_evaluated"
                )
            )
        )
        assert len(events) == 1


async def test_failed_lease_sweep_and_version_mismatch(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    auth_app: FastAPI,
) -> None:
    cycle = await create(candidate)
    cid = UUID(str(cycle["id"]))
    await fix_all(candidate, sessions, cid, "A")
    await candidate.post(f"/api/v1/assessment/cycles/{cid}/start-b")
    await fix_all(candidate, sessions, cid, "B")
    async with sessions.begin() as db:
        row = await db.get(AssessmentCycle, cid)
        assert row
        row.evaluator_hash = "unavailable-old-evaluator"
        job = await claim(db, now=utc_now(), lease_seconds=60, max_attempts=3)
    assert job
    await jobs.process_assessment(sessions, auth_app.state.settings, job)
    async with sessions.begin() as db:
        row = await db.get(AssessmentCycle, cid)
        assert row and row.state == "technical_error"
        other = await db.scalar(
            select(BackgroundJob).where(BackgroundJob.status == "queued").limit(1)
        )
        assert other
        other.status = "failed"
        other.last_error_code = "lease_exhausted"
        await db.flush()
        await jobs.expire_due_cycles(db)
        answer = await db.get(AssessmentAnswer, (cid, str(other.payload["family"])))
        assert (
            answer
            and answer.grading_status == "technical_error"
            and answer.scores == {}
        )
