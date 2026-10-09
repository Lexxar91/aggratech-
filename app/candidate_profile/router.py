from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select

from app.auth.dependencies import Candidate, Db, Employer
from app.candidate_profile import service
from app.candidate_profile.models import CandidateEmployerBlock
from app.candidate_profile.pdf import render_pdf
from app.candidate_profile.schemas import (
    BlockView,
    ContactsInput,
    ContactsView,
    Privacy,
    ProfileInput,
    ProfileView,
    SafeCard,
)
from app.employer.models import EmployerProfile

router = APIRouter(tags=["candidate_profile"])


@router.get("/candidate/profile", response_model=ProfileView)
async def own_profile(db: Db, principal: Candidate) -> ProfileView:
    """Читает профиль текущего кандидата."""
    return await service.view_profile(
        db, await service.own_profile(db, principal.user.id)
    )


@router.patch("/candidate/profile", response_model=ProfileView)
async def update_profile(
    data: ProfileInput, db: Db, principal: Candidate
) -> ProfileView:
    """Сохраняет ручной ввод владельца."""
    return await service.save_profile(db, principal.user.id, data)


@router.get("/candidate/contacts", response_model=ContactsView)
async def own_contacts(db: Db, principal: Candidate) -> ContactsView:
    """Возвращает закрытые контакты только владельцу."""
    return await service.contacts(db, await service.own_profile(db, principal.user.id))


@router.patch("/candidate/contacts", response_model=ContactsView)
async def update_contacts(
    data: ContactsInput, db: Db, principal: Candidate
) -> ContactsView:
    """Изменяет отдельную контактную таблицу."""
    return await service.contacts(
        db, await service.own_profile(db, principal.user.id, lock=True), data
    )


@router.patch("/candidate/privacy", response_model=ProfileView)
async def update_privacy(data: Privacy, db: Db, principal: Candidate) -> ProfileView:
    """Сохраняет текущие права без раскрытия контактов."""
    row = await service.own_profile(db, principal.user.id, lock=True)
    row.privacy = data.model_dump()
    row.version += 1
    return await service.view_profile(db, row)


@router.get("/candidate/profile.pdf")
async def own_pdf(db: Db, principal: Candidate) -> Response:
    """Владелец получает собственный PDF с контактами."""
    row = await service.own_profile(db, principal.user.id)
    data = await render_pdf(
        await service.card(db, row, owner=True),
        await service.contacts(db, row),
    )
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="profile.pdf"'},
    )


@router.get("/candidates/{candidate_id}", response_model=SafeCard)
async def public_card(candidate_id: UUID, db: Db, principal: Employer) -> SafeCard:
    """Работодатель получает только текущую разрешённую безопасную карточку."""
    return await service.card(
        db, await service.visible_profile(db, candidate_id, principal.user.id)
    )


@router.get("/candidates/{candidate_id}/profile.pdf")
async def public_pdf(candidate_id: UUID, db: Db, principal: Employer) -> Response:
    """Права и проекция совпадают с API безопасной карточки."""
    row = await service.visible_profile(db, candidate_id, principal.user.id)
    data = await render_pdf(await service.card(db, row))
    return Response(
        data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="profile.pdf"'},
    )


@router.get("/candidate/blocks", response_model=list[BlockView])
async def blocks(db: Db, principal: Candidate) -> list[BlockView]:
    """Показывает собственные блокировки по безопасным данным компании."""
    profile = await service.own_profile(db, principal.user.id)
    rows = await db.execute(
        select(EmployerProfile.id, EmployerProfile.company_name)
        .join(
            CandidateEmployerBlock,
            CandidateEmployerBlock.employer_id == EmployerProfile.id,
        )
        .where(CandidateEmployerBlock.candidate_id == profile.id)
    )
    return [BlockView(employer_id=row[0], company_name=row[1]) for row in rows]


@router.put("/candidate/blocks/{employer_id}", status_code=204)
async def block(employer_id: UUID, db: Db, principal: Candidate) -> Response:
    """Закрывает текущую видимость конкретной компании."""
    await service.set_block(db, principal.user.id, employer_id, blocked=True)
    return Response(status_code=204)


@router.delete("/candidate/blocks/{employer_id}", status_code=204)
async def unblock(employer_id: UUID, db: Db, principal: Candidate) -> Response:
    """Удаляет блокировку; приватность карточки остаётся обязательной."""
    await service.set_block(db, principal.user.id, employer_id, blocked=False)
    return Response(status_code=204)
