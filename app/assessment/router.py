"""API assessment: роль, подтверждённый email, владение и закрытые этапы."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.assessment import service
from app.assessment.models import AssessmentAppeal, AssessmentCycle, AssessmentSurvey
from app.assessment.schemas import (
    AppealInput,
    AppealView,
    CycleInput,
    CycleView,
    ResultView,
    SaveAnswer,
    SurveyInput,
)
from app.auth.dependencies import Candidate, Db, Principal, require_verified_candidate
from app.core.config import Settings
from app.notifications.queue import utc_now

router = APIRouter(prefix="/assessment", tags=["assessment"])
VerifiedCandidate = Annotated[Principal, Depends(require_verified_candidate)]


@router.get("/survey", response_model=SurveyInput | None)
async def get_survey(db: Db, principal: Candidate) -> SurveyInput | None:
    """Показывает сохранённый опрос текущего кандидата."""
    row = await db.get(AssessmentSurvey, principal.user.id)
    return SurveyInput.model_validate(row.answers) if row else None


@router.put("/survey", response_model=SurveyInput)
async def put_survey(data: SurveyInput, db: Db, principal: Candidate) -> SurveyInput:
    """Сохраняет опрос и принятие заранее показанных правил."""
    await service.save_survey(db, principal.user.id, data, utc_now())
    return data


@router.post("/cycles", response_model=CycleView)
async def create(
    data: CycleInput, db: Db, principal: VerifiedCandidate, request: Request
) -> CycleView:
    """Создаёт либо восстанавливает активный цикл с обязательным допуском режима."""
    settings: Settings = request.app.state.settings
    now = utc_now()
    row = await service.create_cycle(db, principal.user.id, data, settings, now)
    return await service.cycle_view(db, row, now)


@router.get("/cycles", response_model=list[CycleView])
async def history(db: Db, principal: Candidate) -> list[CycleView]:
    """Возвращает историю и текущий этап, не показывая закрытые семейства."""
    rows = list(
        await db.scalars(
            select(AssessmentCycle)
            .where(AssessmentCycle.user_id == principal.user.id)
            .order_by(AssessmentCycle.created_at)
            .with_for_update()
        )
    )
    return [await service.cycle_view(db, row, utc_now()) for row in reversed(rows)]


@router.get("/cycles/{cycle_id}", response_model=CycleView)
async def read(cycle_id: UUID, db: Db, principal: Candidate) -> CycleView:
    """Восстанавливает текущий этап из БД после обновления или рестарта API."""
    return await service.cycle_view(
        db, await service.owned_cycle(db, principal.user.id, cycle_id), utc_now()
    )


@router.put("/cycles/{cycle_id}/answers/{family}", response_model=CycleView)
async def draft(
    cycle_id: UUID, family: str, data: SaveAnswer, db: Db, principal: VerifiedCandidate
) -> CycleView:
    """Сохраняет только текущий черновик с защитой от потерянного обновления."""
    row = await service.owned_cycle(db, principal.user.id, cycle_id)
    await service.save_answer(db, row, family, data, utc_now())
    return await service.cycle_view(db, row, utc_now())


@router.post("/cycles/{cycle_id}/answers/{family}/fix", response_model=CycleView)
async def fix(
    cycle_id: UUID, family: str, data: SaveAnswer, db: Db, principal: VerifiedCandidate
) -> CycleView:
    """Необратимо фиксирует базу до открытия переноса либо окончательный ответ."""
    row = await service.owned_cycle(db, principal.user.id, cycle_id)
    await service.save_answer(db, row, family, data, utc_now(), finalize=True)
    return await service.cycle_view(db, row, utc_now())


@router.post("/cycles/{cycle_id}/submit/{phase}", response_model=CycleView)
async def submit(
    cycle_id: UUID, phase: str, db: Db, principal: VerifiedCandidate
) -> CycleView:
    """Фиксирует A/B, не ожидая фонового оценивания для открытия B."""
    row = await service.owned_cycle(db, principal.user.id, cycle_id)
    await service.advance_deadlines(db, row, utc_now())
    await service.submit_phase(db, row, phase, utc_now())
    return await service.cycle_view(db, row, utc_now())


@router.post("/cycles/{cycle_id}/start-b", response_model=CycleView)
async def begin_b(cycle_id: UUID, db: Db, principal: VerifiedCandidate) -> CycleView:
    """Начинает отдельные 15 минут B в пределах срока начала."""
    row = await service.owned_cycle(db, principal.user.id, cycle_id)
    await service.start_b(db, row, utc_now())
    return await service.cycle_view(db, row, utc_now())


@router.post("/cycles/{cycle_id}/publish", response_model=ResultView)
async def publish(cycle_id: UUID, db: Db, principal: VerifiedCandidate) -> ResultView:
    """Сохраняет добровольный выбор категории с неизменным происхождением результата."""
    return await service.publish(db, principal.user.id, cycle_id, utc_now())


@router.post("/cycles/{cycle_id}/appeals", response_model=AppealView)
async def appeal(
    cycle_id: UUID, data: AppealInput, db: Db, principal: Candidate
) -> AppealView:
    """Регистрирует обращение без автоматического обвинения или изменения баллов."""
    row = await service.owned_cycle(db, principal.user.id, cycle_id)
    return await service.appeal(db, row, data.message, utc_now())


@router.get("/appeals", response_model=list[AppealView])
async def appeals(db: Db, principal: Candidate) -> list[AppealView]:
    """Показывает владельцу решения по его обращениям."""
    rows = await db.scalars(
        select(AssessmentAppeal)
        .where(AssessmentAppeal.user_id == principal.user.id)
        .order_by(AssessmentAppeal.created_at.desc())
    )
    return [
        AppealView(
            id=r.id,
            cycle_id=r.cycle_id,
            state=r.state,
            created_at=r.created_at,
            resolution=r.resolution,
        )
        for r in rows
    ]
