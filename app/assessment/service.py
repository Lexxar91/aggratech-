"""Транзакционные переходы assessment с общим учётом показанных семейств."""

import asyncio
import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment.bank_models import FullBankVersion
from app.assessment.grading import DIAGNOSIS, VERIFICATION, selected_task
from app.assessment.models import (
    AssessmentAnswer,
    AssessmentAppeal,
    AssessmentCycle,
    AssessmentPublication,
    AssessmentSurvey,
    FamilyExposure,
)
from app.assessment.policy import METHODOLOGY, check_calendar, decide
from app.assessment.runtime_bank import admitted_bank, evaluator_hash
from app.assessment.schemas import (
    AppealView,
    CycleInput,
    CycleView,
    PublicTask,
    ResultView,
    SaveAnswer,
    SurveyInput,
    TaskAnswer,
)
from app.candidate_profile.service import own_profile
from app.core.config import Settings
from app.core.errors import ApiError
from app.notifications.models import AuditEvent
from app.notifications.queue import enqueue

ACTIVE = {"A", "B_ready", "B", "grading", "technical_error"}
LABELS = {
    "confirmed": "Грейд подтверждён в пределах теста",
    "not_confirmed": "Грейд пока не подтверждён",
    "insufficient": "Недостаточно данных",
    "review_required": "Требуется проверка достоверности",
}


def audit(
    db: AsyncSession, cycle: AssessmentCycle, action: str, now: datetime, **data: object
) -> None:
    """Пишет отдельное аудируемое событие без исходников и персональных ответов."""
    db.add(
        AuditEvent(
            id=uuid4(),
            actor_id=None if action == "assessment_intervention" else cycle.user_id,
            action=action,
            entity_type="assessment_event",
            entity_id=uuid4(),
            safe_metadata={"cycle_id": str(cycle.id), **data},
            created_at=now,
        )
    )


async def save_survey(
    db: AsyncSession, user_id: UUID, data: SurveyInput, now: datetime
) -> None:
    """Сохраняет опрос владельца без изменения истории попыток и показов."""
    await own_profile(db, user_id, lock=True)
    await db.execute(
        insert(AssessmentSurvey)
        .values(user_id=user_id, answers=data.model_dump(mode="json"), updated_at=now)
        .on_conflict_do_update(
            index_elements=["user_id"],
            set_={"answers": data.model_dump(mode="json"), "updated_at": now},
        )
    )


async def owned_cycle(
    db: AsyncSession, user_id: UUID, cycle_id: UUID
) -> AssessmentCycle:
    """Блокирует только собственный цикл, не раскрывая существование чужого."""
    row = await db.scalar(
        select(AssessmentCycle)
        .where(AssessmentCycle.id == cycle_id, AssessmentCycle.user_id == user_id)
        .with_for_update()
    )
    if row is None:
        raise ApiError(404, "cycle_unavailable", "Цикл не найден.")
    return row


async def answers(db: AsyncSession, cycle_id: UUID) -> list[AssessmentAnswer]:
    """Читает шесть связанных ответов в зафиксированном порядке."""
    return list(
        await db.scalars(
            select(AssessmentAnswer)
            .where(AssessmentAnswer.cycle_id == cycle_id)
            .order_by(AssessmentAnswer.family)
        )
    )


def material(cycle: AssessmentCycle, family: str) -> FullBankVersion:
    """Восстанавливает сохранённые байты задания, не текущую изменяемую версию банка."""
    value = cycle.materials.get(family)
    if value is None:
        raise ApiError(404, "task_unavailable", "Задание недоступно.")
    return FullBankVersion.model_validate(value)


async def create_cycle(
    db: AsyncSession, user_id: UUID, data: CycleInput, settings: Settings, now: datetime
) -> AssessmentCycle:
    """Сериализует создание; сохраняет допуск, форму, параметры и версии."""
    await own_profile(db, user_id, lock=True)
    previous = list(
        await db.scalars(
            select(AssessmentCycle)
            .where(AssessmentCycle.user_id == user_id)
            .order_by(AssessmentCycle.created_at)
            .with_for_update()
        )
    )
    for row in previous:
        await advance_deadlines(db, row, now)
        if row.state in ACTIVE:
            if row.grade == data.grade and row.mode == data.mode:
                return row
            raise ApiError(409, "cycle_active", "Сначала завершите текущий цикл.")
    if await db.get(AssessmentSurvey, user_id) is None:
        raise ApiError(
            409, "survey_required", "Сначала заполните опрос и примите правила."
        )
    publication = await db.get(AssessmentPublication, (user_id, data.mode))
    check_calendar(
        now,
        grade=data.grade,
        completed=[
            (c.grade, c.completed_at, c.technical_exempt)
            for c in previous
            if c.completed_at is not None
        ],
        published_grade=publication.grade if publication else None,
        published_at=publication.published_at if publication else None,
    )
    bank, report = await asyncio.to_thread(admitted_bank, settings, data.mode)
    shown = set(
        await db.scalars(
            select(FamilyExposure.family).where(FamilyExposure.user_id == user_id)
        )
    )
    available = [
        form for form in "XY" if not any(f"{form}{i}" in shown for i in range(1, 7))
    ]
    if not available:
        raise ApiError(
            409, "bank_exhausted", "Нужны новые задания для следующей попытки."
        )
    seed = secrets.randbits(31)
    form = available[seed % len(available)]
    chosen = [
        v for v in bank.versions if v.grade == data.grade and v.family.startswith(form)
    ]
    row = AssessmentCycle(
        id=uuid4(),
        user_id=user_id,
        mode=data.mode,
        grade=data.grade,
        form=form,
        state="A",
        outcome="insufficient",
        review_state="clear",
        created_at=now,
        a_deadline=now + timedelta(minutes=30),
        seed=seed,
        methodology=METHODOLOGY,
        evaluator_hash=await asyncio.to_thread(evaluator_hash),
        bank_hash=report.bank_hash,
        admission={
            "technical_status": report.technical_status,
            "bank_hash": report.bank_hash,
            "review_passed": data.mode == "credit",
            "origin": "live_demo" if data.mode == "demo" else "live_credit",
        },
        materials={v.family: v.model_dump(mode="json") for v in chosen},
        result={},
        technical_exempt=False,
    )
    db.add(row)
    await db.flush()
    for v in chosen:
        db.add(
            AssessmentAnswer(
                cycle_id=row.id,
                family=v.family,
                phase="A" if v.family[1] in "1234" else "B",
                parameter_index=seed % 3,
                step="base",
                draft={},
                revision=0,
                grading_status="pending",
                scores={},
                grading_detail={},
                grade_generation=0,
            )
        )
    audit(db, row, "assessment_created", now, mode=data.mode, bank_hash=row.bank_hash)
    await db.flush()
    return row


async def queue_answer(db: AsyncSession, row: AssessmentAnswer, now: datetime) -> None:
    """Очередь содержит только идентификаторы; окончательные ответы читаются из БД."""
    await enqueue(
        db,
        kind="assessment_grade",
        payload={
            "cycle_id": str(row.cycle_id),
            "family": row.family,
            "generation": row.grade_generation,
        },
        deduplication_key=f"assessment:{row.cycle_id}:{row.family}:{row.grade_generation}",
        now=now,
    )


async def submit_phase(
    db: AsyncSession, cycle: AssessmentCycle, phase: str, now: datetime
) -> None:
    """Атомарно фиксирует черновики и открывает B без ожидания оценщика A."""
    if phase not in ("A", "B"):
        raise ApiError(422, "invalid_phase", "Неизвестный этап.")
    if (phase == "A" and cycle.a_submitted_at) or (
        phase == "B" and cycle.b_submitted_at
    ):
        return
    if cycle.state != phase:
        raise ApiError(409, "phase_closed", "Этап недоступен или уже закрыт.")
    for row in await answers(db, cycle.id):
        if row.phase != phase:
            continue
        if row.finalized_at is None:
            if row.step == "base":
                row.base = dict(row.draft)
            else:
                row.transfer = dict(row.draft)
            row.draft = {}
            row.step = "done"
            row.finalized_at = now
            row.revision += 1
        await queue_answer(db, row, now)
    if phase == "A":
        cycle.a_submitted_at = now
        cycle.b_start_deadline = now + timedelta(hours=24)
        cycle.state = "B_ready"
    else:
        cycle.b_submitted_at = now
        cycle.state = "grading"
    audit(db, cycle, "assessment_phase_submitted", now, phase=phase)
    await db.flush()
    await finalize_result(db, cycle, now)


async def advance_deadlines(
    db: AsyncSession, cycle: AssessmentCycle, now: datetime
) -> None:
    """Лимиты проверяются сервером; просроченная B даёт недостаточность данных."""
    if cycle.state == "A" and now >= cycle.a_deadline:
        await submit_phase(db, cycle, "A", cycle.a_deadline)
    if (
        cycle.state == "B_ready"
        and cycle.b_start_deadline
        and now >= cycle.b_start_deadline
    ):
        cycle.state = "expired"
        cycle.outcome = "insufficient"
        cycle.terminal_reason = "b_not_started"
        audit(db, cycle, "assessment_b_expired", now)
    if cycle.state == "B" and cycle.b_deadline and now >= cycle.b_deadline:
        await submit_phase(db, cycle, "B", cycle.b_deadline)


async def start_b(db: AsyncSession, cycle: AssessmentCycle, now: datetime) -> None:
    """Открывает подтверждающие задания только после фиксации A."""
    await advance_deadlines(db, cycle, now)
    if cycle.state == "B":
        return
    if cycle.state != "B_ready":
        raise ApiError(
            409, "b_not_available", "B доступна после сдачи A в течение 24 часов."
        )
    cycle.b_started_at = now
    cycle.b_deadline = now + timedelta(minutes=15)
    cycle.state = "B"
    audit(db, cycle, "assessment_b_started", now)


async def save_answer(
    db: AsyncSession,
    cycle: AssessmentCycle,
    family: str,
    data: SaveAnswer,
    now: datetime,
    *,
    finalize: bool = False,
) -> None:
    """Версия и блокировка цикла защищают базу после открытия переноса."""
    await advance_deadlines(db, cycle, now)
    row = await db.get(AssessmentAnswer, (cycle.id, family))
    if row is None or row.phase != cycle.state:
        raise ApiError(409, "task_closed", "Задание закрыто или ещё не открыто.")
    if row.revision != data.revision or row.step != data.step:
        raise ApiError(
            409, "answer_revision_conflict", "Обновите страницу: ответ уже изменён."
        )
    row.draft = data.answer.model_dump(mode="json")
    row.revision += 1
    if finalize:
        if row.step == "base":
            row.base = dict(row.draft)
            row.step = "transfer"
        else:
            row.transfer = dict(row.draft)
            row.step = "done"
            row.finalized_at = now
        row.draft = {}
        audit(db, cycle, "assessment_answer_fixed", now, family=family, step=data.step)


async def finalize_result(
    db: AsyncSession, cycle: AssessmentCycle, now: datetime
) -> None:
    """Объединяет независимые семейства только после B и завершения всех проверок."""
    if cycle.b_submitted_at is None or cycle.state == "invalidated":
        return
    rows = await answers(db, cycle.id)
    if any(r.grading_status != "completed" for r in rows):
        if any(r.grading_status == "technical_error" for r in rows):
            cycle.state = "technical_error"
        return
    evidence: dict[str, dict[str, int]] = {}
    for row in rows:
        if row.scores:
            evidence[row.family] = {
                k: v
                for k, v in row.scores.items()
                if isinstance(v, int) and not isinstance(v, bool)
            }
    outcome, total, skills = decide(
        cycle.grade,
        evidence,
        b_completed=True,
        review_required=cycle.review_state != "clear",
    )
    cycle.outcome = outcome
    cycle.result = {"total": total, "skills": skills}
    cycle.completed_at = cycle.completed_at or now
    cycle.state = "completed"


def result_view(cycle: AssessmentCycle) -> ResultView:
    """Маркирует демо даже при выполнении порогов и не публикует закрытые основания."""
    outcome = "review_required" if cycle.review_state != "clear" else cycle.outcome
    label = LABELS[outcome]
    if cycle.mode == "demo":
        label = (
            "Демонстрационный результат: "
            + {
                "confirmed": "требования выполнены; это не верифицированная категория",
                "not_confirmed": "требования пока не выполнены",
                "insufficient": "недостаточно данных",
                "review_required": "требуется проверка",
            }[outcome]
        )
    return ResultView.model_validate(
        {
            "outcome": outcome,
            "mode": cycle.mode,
            "grade": cycle.grade,
            "label": label,
            "verified": cycle.mode == "credit"
            and outcome == "confirmed"
            and cycle.admission.get("review_passed") is True,
            "total": cycle.result.get("total"),
            "skills": cycle.result.get("skills", []),
            "methodology": cycle.methodology,
            "assessed_at": cycle.completed_at,
        }
    )


async def cycle_view(
    db: AsyncSession, cycle: AssessmentCycle, now: datetime
) -> CycleView:
    """Возвращает только текущие условия; база не раскрывает перенос или семейства B."""
    await advance_deadlines(db, cycle, now)
    tasks: list[PublicTask] = []
    for row in await answers(db, cycle.id):
        if row.phase != cycle.state:
            continue
        v = material(cycle, row.family)
        phase = "transfer" if row.step == "transfer" else "base"
        structured = selected_task(v, phase, row.parameter_index)
        code_cases = [c for c in v.cases if c.phase == phase]
        chosen_input: JsonValue = (
            code_cases[row.parameter_index % len(code_cases)].input
            if code_cases
            else (structured.input if structured else None)
        )
        await db.execute(
            insert(FamilyExposure)
            .values(
                user_id=cycle.user_id,
                family=row.family,
                cycle_id=cycle.id,
                shown_at=now,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "family"])
        )
        tasks.append(
            PublicTask(
                family=row.family,
                phase=row.phase,
                step=row.step,
                revision=row.revision,
                condition=v.transfer if phase == "transfer" else v.condition,
                diagnosis_prompt=v.diagnosis,
                diagnosis_options=sorted(set(DIAGNOSIS.values()) | {"unknown"})
                if v.solutions
                else [],
                verification_options=VERIFICATION if v.solutions else [],
                input=chosen_input,
                structured_condition=structured.condition if structured else None,
                structured_input=structured.input if structured else None,
                answer_options=structured.answer_options if structured else {},
                python_required=bool(v.solutions),
                candidate_test_contract=(
                    "2–3 JSON-случая [{input,expected}] по базовому условию. "
                    "До 12 страниц и 20 записей на странице для X4; "
                    "до 8 HTTP-ответов, max_attempts 1..5 для Y4. "
                    "Каждый expected — полный ожидаемый объект результата. "
                    "Обязательные классы: "
                    + ", ".join(v.test_policy.mandatory)
                    + "; дополнительный: "
                    + v.test_policy.additional
                )
                if v.test_policy and phase == "base"
                else None,
                draft=TaskAnswer.model_validate(row.draft),
                finalized=row.finalized_at is not None,
            )
        )
    return CycleView(
        id=cycle.id,
        grade=cycle.grade,
        mode=cycle.mode,
        state=cycle.state,
        a_deadline=cycle.a_deadline,
        b_start_deadline=cycle.b_start_deadline,
        b_deadline=cycle.b_deadline,
        tasks=tasks,
        result=result_view(cycle),
        technical_issue=any(
            r.grading_status == "technical_error" for r in await answers(db, cycle.id)
        ),
        bank_hash=cycle.bank_hash,
        created_at=cycle.created_at,
        completed_at=cycle.completed_at,
    )


async def publish(
    db: AsyncSession, user_id: UUID, cycle_id: UUID, now: datetime
) -> ResultView:
    """Публикует выбранный последний успешный результат, не максимум баллов истории."""
    await own_profile(db, user_id, lock=True)
    cycle = await owned_cycle(db, user_id, cycle_id)
    if (
        cycle.state != "completed"
        or cycle.outcome != "confirmed"
        or cycle.review_state != "clear"
    ):
        raise ApiError(
            409,
            "result_not_publishable",
            "Опубликовать можно завершённый успешный результат без открытого review.",
        )
    if cycle.mode == "credit" and cycle.admission.get("review_passed") is not True:
        raise ApiError(409, "bank_not_admitted", "Зачётный допуск банка отсутствует.")
    newer = await db.scalar(
        select(AssessmentCycle.id).where(
            AssessmentCycle.user_id == user_id,
            AssessmentCycle.mode == cycle.mode,
            AssessmentCycle.outcome == "confirmed",
            AssessmentCycle.created_at > cycle.created_at,
        )
    )
    if newer:
        raise ApiError(
            409,
            "newer_success_exists",
            "Существует более новое успешное подтверждение.",
        )
    previous = await db.get(AssessmentPublication, (user_id, cycle.mode))
    if previous and previous.cycle_id == cycle.id:
        return result_view(cycle)
    if (
        previous
        and previous.grade != cycle.grade
        and now < previous.published_at + timedelta(days=30)
    ):
        raise ApiError(
            409,
            "grade_cooldown",
            "Смена опубликованного грейда доступна через 30 дней.",
        )
    await db.execute(
        insert(AssessmentPublication)
        .values(
            user_id=user_id,
            mode=cycle.mode,
            cycle_id=cycle.id,
            grade=cycle.grade,
            published_at=now,
        )
        .on_conflict_do_update(
            index_elements=["user_id", "mode"],
            set_={"cycle_id": cycle.id, "grade": cycle.grade, "published_at": now},
        )
    )
    audit(
        db,
        cycle,
        "assessment_published",
        now,
        mode=cycle.mode,
        verified=cycle.mode == "credit",
    )
    return result_view(cycle)


async def published_result(
    db: AsyncSession, user_id: UUID, *, owner: bool
) -> ResultView | None:
    """Подтверждённая проекция работодателя исключает любые демо и незакрытые review."""
    query = (
        select(AssessmentCycle)
        .join(
            AssessmentPublication, AssessmentPublication.cycle_id == AssessmentCycle.id
        )
        .where(
            AssessmentPublication.user_id == user_id,
            AssessmentCycle.outcome == "confirmed",
            AssessmentCycle.review_state == "clear",
            AssessmentCycle.state == "completed",
        )
    )
    if not owner:
        query = query.where(
            AssessmentPublication.mode == "credit", AssessmentCycle.mode == "credit"
        )
    row = await db.scalar(
        query.order_by(AssessmentPublication.published_at.desc()).limit(1)
    )
    if row is None or (
        row.mode == "credit" and row.admission.get("review_passed") is not True
    ):
        return None
    return result_view(row)


async def appeal(
    db: AsyncSession, cycle: AssessmentCycle, message: str, now: datetime
) -> AppealView:
    """Открывает апелляцию и исключает результат из подтверждённой проекции."""
    existing = await db.scalar(
        select(AssessmentAppeal).where(
            AssessmentAppeal.cycle_id == cycle.id, AssessmentAppeal.state == "open"
        )
    )
    if existing is None:
        existing = AssessmentAppeal(
            id=uuid4(),
            cycle_id=cycle.id,
            user_id=cycle.user_id,
            message=message,
            state="open",
            created_at=now,
        )
        db.add(existing)
        audit(db, cycle, "assessment_appeal_opened", now, appeal_id=str(existing.id))
    cycle.review_state = "open"
    return AppealView(
        id=existing.id,
        cycle_id=existing.cycle_id,
        state=existing.state,
        created_at=existing.created_at,
        resolution=existing.resolution,
    )
