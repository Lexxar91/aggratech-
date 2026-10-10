"""Фоновая оценка с владением очередью и восстановлением того же снимка ответов."""

import asyncio
from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment.grading import FamilyGrade, grade_family
from app.assessment.models import AssessmentAnswer, AssessmentCycle
from app.assessment.runner import RunnerClient, RunnerUnavailable
from app.assessment.runtime_bank import evaluator_hash
from app.assessment.schemas import TaskAnswer
from app.assessment.service import advance_deadlines, audit, finalize_result, material
from app.assessment.v3_admission import evaluator_hash_v3
from app.assessment.v3_grading import grade_v3
from app.assessment.v3_models import V3Card, V3TaskGrade
from app.core.config import Settings
from app.notifications.models import BackgroundJob
from app.notifications.queue import ClaimedJob, owned_job, utc_now


async def expire_due_cycles(db: AsyncSession) -> None:
    """Применяет серверные дедлайны даже после закрытия браузера кандидата."""
    now = utc_now()
    rows = await db.scalars(
        select(AssessmentCycle)
        .where(
            or_(
                and_(AssessmentCycle.state == "A", AssessmentCycle.a_deadline <= now),
                and_(
                    AssessmentCycle.state == "B_ready",
                    AssessmentCycle.b_start_deadline <= now,
                ),
                and_(AssessmentCycle.state == "B", AssessmentCycle.b_deadline <= now),
            )
        )
        .order_by(AssessmentCycle.created_at)
        .with_for_update(skip_locked=True)
        .limit(100)
    )
    for row in rows:
        await advance_deadlines(db, row, now)
    # Исчерпание lease после падений worker — техническая проблема, не балл 0.
    failed = await db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.kind == "assessment_grade", BackgroundJob.status == "failed"
        )
    )
    for job in failed:
        cycle = await db.scalar(
            select(AssessmentCycle)
            .where(AssessmentCycle.id == UUID(str(job.payload["cycle_id"])))
            .with_for_update()
        )
        answer = await db.get(
            AssessmentAnswer,
            (UUID(str(job.payload["cycle_id"])), str(job.payload["family"])),
        )
        if (
            cycle
            and answer
            and answer.grade_generation == job.payload["generation"]
            and answer.grading_status == "pending"
        ):
            answer.grading_status = "technical_error"
            answer.grading_detail = {"error": "worker_recovery_exhausted"}
            await db.flush()
            await finalize_result(db, cycle, now)


async def process_assessment(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, job: ClaimedJob
) -> None:
    """Исполняет вне транзакции; запись разрешена только текущему worker."""
    cycle_id = UUID(str(job.payload["cycle_id"]))
    family = str(job.payload["family"])
    generation = job.payload["generation"]
    async with sessions() as db:
        cycle = await db.get(AssessmentCycle, cycle_id)
        row = await db.get(AssessmentAnswer, (cycle_id, family))
        if cycle is None or row is None or row.finalized_at is None:
            raise ValueError("invalid_assessment_job")
        version = material(cycle, family)
        base = TaskAnswer.model_validate(row.base or {})
        transfer = TaskAnswer.model_validate(row.transfer or {})
        index = row.parameter_index
        expected_hash = cycle.evaluator_hash
    if isinstance(version, V3Card):
        # Несколько ограниченных batch-запусков могут превышать прежний lease 60 s.
        # Продлеваем только действующего владельца, не оживляя чужую/истёкшую работу.
        async with sessions.begin() as db:
            owned = await owned_job(db, job, utc_now())
            if owned is None:
                return
            owned.lease_until = utc_now() + timedelta(
                seconds=max(300, settings.job_lease_seconds)
            )
    result = FamilyGrade()
    v3_result: V3TaskGrade | None = None
    error: str | None = None
    runner: RunnerClient | None = None
    try:
        if expected_hash != await asyncio.to_thread(
            evaluator_hash_v3 if isinstance(version, V3Card) else evaluator_hash
        ):
            raise RunnerUnavailable("evaluator_version_unavailable")
        if isinstance(version, V3Card):
            runner = RunnerClient(settings)
            v3_result = await grade_v3(
                version,
                base.source,
                transfer.source,
                version.seeds[index % len(version.seeds)],
                runner.execute_v3,
            )
            if v3_result.status == "environment_error":
                error = "assessment_infrastructure_unavailable"
        elif any(
            (
                base.source,
                base.structured,
                base.diagnosis,
                base.verification,
                base.tests,
            )
        ):
            runner = RunnerClient(settings)
            result = await grade_family(version, base, transfer, index, runner.execute)
    except RunnerUnavailable, OSError:
        error = "assessment_infrastructure_unavailable"
    finally:
        if runner:
            await runner.close()
    async with sessions.begin() as db:
        owned = await owned_job(db, job, utc_now())
        if owned is None:
            return
        cycle = await db.scalar(
            select(AssessmentCycle)
            .where(AssessmentCycle.id == cycle_id)
            .with_for_update()
        )
        row = await db.get(AssessmentAnswer, (cycle_id, family))
        if cycle is None or row is None or row.grade_generation != generation:
            owned.status = "succeeded"
        else:
            if isinstance(version, V3Card):
                v3_result = v3_result or V3TaskGrade(status="environment_error")
                row.grading_status = v3_result.status
                row.scores = dict(v3_result.scores)
                row.grading_detail = v3_result.model_dump(
                    mode="json", exclude={"scores"}
                )
            else:
                row.grading_status = "technical_error" if error else "completed"
                row.scores = {} if error else dict(result.scores)
                row.grading_detail = (
                    {"error": error}
                    if error
                    else result.model_dump(mode="json", exclude={"scores"})
                )
            owned.status = "failed" if error else "succeeded"
            owned.last_error_code = error
            audit(
                db,
                cycle,
                "assessment_family_evaluated",
                utc_now(),
                family=family,
                status=row.grading_status,
            )
            await db.flush()
            await finalize_result(db, cycle, utc_now())
        owned.lease_until = None
        owned.claim_token = None
