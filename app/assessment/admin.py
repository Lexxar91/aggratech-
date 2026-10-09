"""Служебные операции доступны только оператору с доступом к CLI/БД."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment.models import AssessmentAppeal, AssessmentCycle
from app.assessment.service import answers, audit, finalize_result, queue_answer
from app.core.errors import ApiError


async def intervene(
    db: AsyncSession,
    cycle_id: UUID,
    *,
    action: str,
    reason: str,
    reviewer: str,
    now: datetime,
    seconds: int = 0,
) -> None:
    """Аудирует мотивированное решение; не меняет грейд, режим или историю показов."""
    if len(reason.strip()) < 10 or not reviewer.strip() or len(reviewer) > 128:
        raise ValueError("reason_and_reviewer_required")
    cycle = await db.scalar(
        select(AssessmentCycle).where(AssessmentCycle.id == cycle_id).with_for_update()
    )
    if cycle is None:
        raise ApiError(404, "cycle_unavailable", "Цикл не найден.")
    if action == "extend":
        if not 1 <= seconds <= 86400 or cycle.state not in {
            "A",
            "B",
            "B_ready",
            "expired",
        }:
            raise ValueError("extension_not_applicable")
        field = {
            "A": "a_deadline",
            "B": "b_deadline",
            "B_ready": "b_start_deadline",
            "expired": "b_start_deadline",
        }[cycle.state]
        deadline = getattr(cycle, field)
        if deadline is None:
            raise ValueError("deadline_missing")
        setattr(cycle, field, max(now, deadline) + timedelta(seconds=seconds))
        if cycle.state == "expired":
            cycle.state = "B_ready"
            cycle.terminal_reason = None
        cycle.technical_exempt = True
    elif action == "retry":
        rows = [
            r
            for r in await answers(db, cycle.id)
            if r.finalized_at is not None and r.grading_status != "completed"
        ]
        if not rows:
            raise ValueError("nothing_to_retry")
        for row in rows:
            row.grade_generation += 1
            row.grading_status = "pending"
            row.grading_detail = {}
            await queue_answer(db, row, now)
        if cycle.state == "technical_error":
            cycle.state = "grading"
        cycle.technical_exempt = True
    elif action in {"uphold", "invalidate", "review"}:
        if action == "review":
            cycle.review_state = "open"
        else:
            opened = list(
                await db.scalars(
                    select(AssessmentAppeal).where(
                        AssessmentAppeal.cycle_id == cycle.id,
                        AssessmentAppeal.state == "open",
                    )
                )
            )
            if cycle.review_state != "open" and not opened:
                raise ValueError("no_open_review")
            cycle.review_state = "clear"
            for appeal_row in opened:
                appeal_row.state = "resolved"
                appeal_row.resolved_at = now
                appeal_row.resolution = reason
                appeal_row.reviewer = reviewer
            if action == "invalidate":
                cycle.state = "invalidated"
                cycle.outcome = "insufficient"
                cycle.terminal_reason = "technical_invalidation"
                cycle.technical_exempt = True
            else:
                await finalize_result(db, cycle, now)
    else:
        raise ValueError("unknown_intervention")
    audit(
        db,
        cycle,
        "assessment_intervention",
        now,
        intervention=action,
        reason=reason,
        reviewer=reviewer,
        seconds=seconds,
    )
