"""Mock требует подтверждённый email и код, а ID не служит доказательством."""

import hmac
import json
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.dependencies import Db, Principal, require_verified_candidate
from app.candidate_profile.service import own_profile
from app.core.errors import ApiError
from app.fsp.models import FspLink
from app.notifications.queue import utc_now

router = APIRouter(prefix="/candidate/fsp", tags=["fsp"])
Verified = Annotated[Principal, Depends(require_verified_candidate)]


class LinkInput(BaseModel):
    """Публичный demo-код не предназначен для настоящего реестра."""

    model_config = ConfigDict(extra="forbid")
    external_id: str = Field(min_length=1, max_length=128)
    claim_code: str = Field(min_length=1, max_length=128)


class FspView(BaseModel):
    external_id: str | None = None
    source: str = "fsp_mock"
    verified_real_achievement: bool = False
    status: str = "not_linked"
    achievements: list[dict[str, object]] = Field(default_factory=list)
    notice: str = (
        "ФСП mock: демонстрационные записи, не подтверждение "
        "реальных достижений; F=0 в продуктовой "
        "подборке."
    )


# Фиксированный mock JSON содержит разнородные поля участника и событий.
_PARTICIPANTS = json.loads(
    Path("fixtures/demo/fsp_mock.json").read_text(encoding="utf-8")
)["participants"]


def participants() -> list[dict[str, Any]]:
    """Читает фиксированный публичный mock, не подключается к внешнему реестру."""
    return list(_PARTICIPANTS)


def view(row: FspLink | None) -> FspView:
    """Проецирует только собственную демонстрационную историю."""
    return (
        FspView(
            external_id=row.external_id,
            status=row.status,
            achievements=row.achievements,
        )
        if row
        else FspView()
    )


@router.get("/achievements")
async def achievements(db: Db, principal: Verified) -> FspView:
    """Возвращает только собственный кэш с явным mock-происхождением."""
    profile = await own_profile(db, principal.user.id)
    return view(await db.get(FspLink, profile.id))


@router.post("/link")
async def link(data: LinkInput, db: Db, principal: Verified) -> FspView:
    """Проверяет принадлежность по подтверждённому email и mock-коду."""
    profile = await own_profile(db, principal.user.id, lock=True)
    participant = next((p for p in participants() if p["id"] == data.external_id), None)
    if participant is None:
        raise ApiError(404, "fsp_not_found", "Участник mock не найден.")
    if (
        participant["email"].casefold() != principal.user.email_normalized.casefold()
        or not hmac.compare_digest(
            data.claim_code.encode(), participant["claim_code"].encode()
        )
    ):
        raise ApiError(
            403, "fsp_ownership_failed", "Принадлежность mock-записи не подтверждена."
        )
    # Блокируем пользователя-владельца записи, сериализуя повторную привязку.
    occupied = await db.scalar(
        select(FspLink).where(FspLink.external_id == data.external_id)
    )
    if occupied and occupied.candidate_id != profile.id:
        raise ApiError(409, "fsp_already_linked", "Запись уже привязана.")
    row = await db.get(FspLink, profile.id)
    if row is None:
        row = FspLink(
            candidate_id=profile.id,
            external_id=data.external_id,
            source="fsp_mock",
            status="linked",
            achievements=[],
            linked_at=utc_now(),
        )
        db.add(row)
    else:
        row.external_id = data.external_id
        row.status = "linked"
        row.achievements = []
        row.linked_at = utc_now()
        row.synced_at = None
    await db.flush()
    return view(row)


@router.post("/sync")
async def sync(db: Db, principal: Verified) -> FspView:
    """Различает пустую историю, исчезнувшую запись и временную недоступность."""
    profile = await own_profile(db, principal.user.id, lock=True)
    row = await db.get(FspLink, profile.id)
    if row is None:
        raise ApiError(409, "fsp_not_linked", "Сначала привяжите mock-запись.")
    participant = next((p for p in participants() if p["id"] == row.external_id), None)
    row.synced_at = utc_now()
    if participant is None:
        row.status = "not_found"
        row.achievements = []
    elif participant["email"].casefold() != principal.user.email_normalized.casefold():
        row.status = "ownership_failed"
        row.achievements = []
    elif participant["status"] == "unavailable":
        row.status = "temporarily_unavailable"
    else:
        unique = {p["event_id"]: p for p in participant["achievements"]}
        row.achievements = list(unique.values())
        row.status = "synced" if unique else "no_achievements"
    return view(row)


@router.delete("/link")
async def unlink(db: Db, principal: Verified) -> FspView:
    """Отзывает связь и весь mock-кэш владельца."""
    profile = await own_profile(db, principal.user.id, lock=True)
    row = await db.get(FspLink, profile.id)
    if row:
        await db.delete(row)
    return FspView()
