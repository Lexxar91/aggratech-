"""Потребности владельца и безопасные версии выдачи без отдельного compare API."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.dependencies import Db, Employer, Principal
from app.candidate_profile.service import visible_profile
from app.core.errors import ApiError
from app.matching import service
from app.matching.catalog import dictionary
from app.matching.models import CandidateNeedMark, EmployerNeed, MatchingSnapshot
from app.matching.schemas import Need, Ranking

router = APIRouter(tags=["matching"])


async def verified_employer(principal: Employer) -> Principal:
    """Потребности доступны работодателю после подтверждения email."""
    if principal.user.email_verified_at is None:
        raise ApiError(403, "email_verification_required", "Сначала подтвердите email.")
    return principal


Verified = Annotated[Principal, Depends(verified_employer)]


class NeedInput(Need):
    """Идентификаторы владельца назначает сервер; вход их не принимает."""

    need_id: str = Field(default="server", exclude=True)
    employer_id: str = Field(default="server", exclude=True)

    @classmethod
    def model_validate_input(cls, data: NeedInput) -> Need:
        return Need.model_validate(
            {**data.model_dump(), "need_id": "server", "employer_id": "server"}
        )


class MarkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    saved: bool = False
    hidden: bool = False
    reason: str = Field(default="", max_length=500)


@router.get("/catalog/matching-dictionary")
async def matching_dictionary() -> dict[str, object]:
    """Публичный словарь не содержит профилей и закрытых материалов."""
    return dictionary()


@router.get("/employer/need-templates")
async def templates(principal: Verified) -> list[dict[str, object]]:
    """Три редактируемых шаблона без угаданных бюджета и требований."""
    return service.templates()


@router.get("/employer/needs")
async def needs(db: Db, principal: Verified) -> list[Need]:
    """Перечисляет только потребности активной компании владельца."""
    company = await service.company(db, principal.user.id)
    rows = await db.scalars(
        select(EmployerNeed)
        .where(EmployerNeed.employer_id == company.id)
        .order_by(EmployerNeed.id)
    )
    return [Need.model_validate(row.definition) for row in rows]


@router.post("/employer/needs")
async def create(data: NeedInput, db: Db, principal: Verified) -> Need:
    """Создаёт потребность независимо от наличия доступных категорий."""
    if "need_id" in data.model_fields_set or "employer_id" in data.model_fields_set:
        raise ApiError(422, "server_identifier", "Идентификаторы назначаются сервером.")
    return await service.save_need(
        db, principal.user.id, NeedInput.model_validate_input(data)
    )


@router.get("/employer/needs/{need_id}")
async def get_need(need_id: UUID, db: Db, principal: Verified) -> Need:
    """Читает актуальную версию потребности владельца."""
    return Need.model_validate(
        (await service.owned_need(db, principal.user.id, need_id)).definition
    )


@router.patch("/employer/needs/{need_id}")
async def update(need_id: UUID, data: NeedInput, db: Db, principal: Verified) -> Need:
    """Сохраняет следующую версию, сохраняя прежние снимки."""
    if "need_id" in data.model_fields_set or "employer_id" in data.model_fields_set:
        raise ApiError(422, "server_identifier", "Идентификаторы назначаются сервером.")
    row = await service.owned_need(db, principal.user.id, need_id, lock=True)
    return await service.save_need(
        db, principal.user.id, NeedInput.model_validate_input(data), row
    )


@router.post("/employer/needs/{need_id}/recommendations")
async def build(need_id: UUID, db: Db, principal: Verified) -> service.SnapshotView:
    """Новая выдача использует актуальные доказательства и версию потребности."""
    row = await service.owned_need(db, principal.user.id, need_id, lock=True)
    return await service.snapshot_view(
        db, await service.build_snapshot(db, row), principal.user.id
    )


@router.get("/employer/needs/{need_id}/recommendations")
async def history(
    need_id: UUID, db: Db, principal: Verified
) -> list[dict[str, object]]:
    """Перечисляет версии подборок только своей компании."""
    await service.owned_need(db, principal.user.id, need_id)
    rows = await db.scalars(
        select(MatchingSnapshot)
        .where(MatchingSnapshot.need_id == need_id)
        .order_by(MatchingSnapshot.created_at.desc())
    )
    return [
        {
            "id": str(row.id),
            "need_version": row.need_version,
            "as_of": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/employer/recommendations/{snapshot_id}")
async def snapshot(
    snapshot_id: UUID, db: Db, principal: Verified
) -> service.SnapshotView:
    """Перечитывает снимок с актуальной проверкой доступа."""
    row = await db.get(MatchingSnapshot, snapshot_id)
    if row is None:
        raise ApiError(404, "snapshot_unavailable", "Подборка недоступна.")
    return await service.snapshot_view(db, row, principal.user.id)


@router.put("/employer/needs/{need_id}/candidates/{candidate_id}")
async def mark(
    need_id: UUID, candidate_id: UUID, data: MarkInput, db: Db, principal: Verified
) -> MarkInput:
    """Отметка меняется только для доступной в этой потребности карточки."""
    await service.owned_need(db, principal.user.id, need_id, lock=True)
    candidate_profile = await visible_profile(db, candidate_id, principal.user.id)
    if await service.published_cycle(db, candidate_profile.user_id) is None:
        raise ApiError(404, "candidate_unavailable", "Карточка недоступна.")
    snapshots = await db.scalars(
        select(MatchingSnapshot).where(MatchingSnapshot.need_id == need_id)
    )
    if not any(
        any(
            r.candidate_id == str(candidate_id) and r.group != "excluded"
            for r in Ranking.model_validate(s.ranking).recommendations
        )
        for s in snapshots
    ):
        raise ApiError(
            404,
            "candidate_unavailable",
            "Карточка отсутствует в подборках потребности.",
        )
    row = await db.get(CandidateNeedMark, (need_id, candidate_id))
    if row is None:
        row = CandidateNeedMark(need_id=need_id, candidate_id=candidate_id)
        db.add(row)
    row.saved = data.saved
    row.hidden = data.hidden
    row.reason = data.reason
    row.updated_at = datetime.now(UTC)
    return data
