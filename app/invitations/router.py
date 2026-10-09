from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.auth.dependencies import Candidate, Db
from app.auth.service import rate_limit
from app.candidate_profile import access
from app.candidate_profile import service as profiles
from app.invitations import service
from app.invitations.schemas import Acceptance, InvitationView, SendInput
from app.matching.router import Verified

router = APIRouter(tags=["invitations"])


@router.post("/employer/invitations", response_model=InvitationView)
async def send(
    data: SendInput, request: Request, db: Db, principal: Verified
) -> InvitationView:
    """Создаёт адресное приглашение с обязательной зарплатой."""
    await rate_limit(request, "invitation_send", str(principal.user.id))
    return await service.send(db, principal.user.id, data)


@router.get("/employer/invitations", response_model=list[InvitationView])
async def employer_list(db: Db, principal: Verified) -> list[InvitationView]:
    """Читает историю только своей компании."""
    return await service.listing(db, principal.user.id, "employer")


@router.get("/employer/invitations/{identifier}", response_model=InvitationView)
async def employer_view(
    identifier: UUID, db: Db, principal: Verified
) -> InvitationView:
    """Чтение работодателем не устанавливает viewed."""
    return await service.action(db, principal.user.id, "employer", identifier, None)


@router.post(
    "/employer/invitations/{identifier}/withdraw", response_model=InvitationView
)
async def withdraw(identifier: UUID, db: Db, principal: Verified) -> InvitationView:
    """Отзывает только незавершённое приглашение."""
    return await service.action(
        db, principal.user.id, "employer", identifier, "withdrawn"
    )


@router.get("/candidate/invitations", response_model=list[InvitationView])
async def candidate_list(db: Db, principal: Candidate) -> list[InvitationView]:
    """Читает адресованные предложения без отметки просмотра."""
    return await service.listing(db, principal.user.id, "candidate")


@router.get("/candidate/invitations/{identifier}", response_model=InvitationView)
async def candidate_view(
    identifier: UUID, db: Db, principal: Candidate
) -> InvitationView:
    """Осознанное открытие авторизованным кандидатом устанавливает viewed."""
    return await service.action(
        db, principal.user.id, "candidate", identifier, "viewed"
    )


@router.post(
    "/candidate/invitations/{identifier}/accept", response_model=InvitationView
)
async def accept(
    identifier: UUID, data: Acceptance, db: Db, principal: Candidate
) -> InvitationView:
    """Принимает предложение и согласие атомарно."""
    return await service.action(
        db, principal.user.id, "candidate", identifier, "accepted", data
    )


@router.post(
    "/candidate/invitations/{identifier}/reject", response_model=InvitationView
)
async def reject(identifier: UUID, db: Db, principal: Candidate) -> InvitationView:
    """Отказ не запускает повторную рассылку."""
    return await service.action(
        db, principal.user.id, "candidate", identifier, "rejected"
    )


@router.delete("/candidate/contact-grants/{employer_id}", status_code=204)
async def revoke(employer_id: UUID, db: Db, principal: Candidate) -> Response:
    """Кандидат закрывает все разрешения конкретному работодателю."""
    profile = await profiles.own_profile(db, principal.user.id, lock=True)
    await access.revoke(db, profile.id, employer_id, actor_id=principal.user.id)
    return Response(status_code=204)
