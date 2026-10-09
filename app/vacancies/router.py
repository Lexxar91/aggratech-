"""Тонкие HTTP-обработчики вакансий и адресных откликов."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.auth.dependencies import Candidate, Db, Principal, require_verified_candidate
from app.matching.router import Verified
from app.vacancies import service
from app.vacancies.schemas import (
    ApplicationInput,
    ApplicationView,
    VacancyInput,
    VacancyPatch,
    VacancyView,
)

VerifiedCandidate = Annotated[Principal, Depends(require_verified_candidate)]
router = APIRouter(tags=["vacancies"])


@router.post("/employer/vacancies", response_model=VacancyView)
async def create(data: VacancyInput, db: Db, principal: Verified) -> VacancyView:
    """Публикует только вакансию своей компании с обязательной зарплатой."""
    return await service.create(db, principal.user.id, data)


@router.patch("/employer/vacancies/{identifier}", response_model=VacancyView)
async def edit(
    identifier: UUID, data: VacancyPatch, db: Db, principal: Verified
) -> VacancyView:
    """Меняет открытые условия по текущей версии владельца."""
    return await service.edit(db, principal.user.id, identifier, data)


@router.post("/employer/vacancies/{identifier}/close", response_model=VacancyView)
async def close(identifier: UUID, db: Db, principal: Verified) -> VacancyView:
    """Закрывает новые подачи, сохраняя историю."""
    return await service.close(db, principal.user.id, identifier)


@router.get("/employer/vacancies", response_model=list[VacancyView])
async def own_list(db: Db, principal: Verified) -> list[VacancyView]:
    """Возвращает вакансии только своей компании, включая закрытые."""
    return await service.listing(db, principal.user.id)


@router.get("/employer/vacancies/{identifier}", response_model=VacancyView)
async def own_view(identifier: UUID, db: Db, principal: Verified) -> VacancyView:
    """Просмотр для редактирования проверяет владельца."""
    return await service.vacancy_view(
        db, await service.owned_vacancy(db, principal.user.id, identifier)
    )


@router.get("/vacancies", response_model=list[VacancyView])
async def published(db: Db) -> list[VacancyView]:
    """Объявления не содержат профилей или контактов кандидатов."""
    return await service.listing(db)


@router.get("/vacancies/{identifier}", response_model=VacancyView)
async def public_view(identifier: UUID, db: Db) -> VacancyView:
    """Показывает актуальные условия и явный статус вакансии."""
    return await service.public_view(db, identifier)


@router.post("/vacancies/{identifier}/applications", response_model=ApplicationView)
async def apply(
    identifier: UUID, data: ApplicationInput, db: Db, principal: VerifiedCandidate
) -> ApplicationView:
    """Копирует условия и выдаёт выбранное согласие в той же транзакции."""
    return await service.apply(db, principal.user.id, identifier, data)


@router.get("/candidate/applications", response_model=list[ApplicationView])
async def own_applications(db: Db, principal: Candidate) -> list[ApplicationView]:
    """Кандидат читает только собственную историю."""
    return await service.applications(db, principal.user.id, "candidate")


@router.get(
    "/employer/vacancies/{identifier}/applications",
    response_model=list[ApplicationView],
)
async def received(
    identifier: UUID, db: Db, principal: Verified
) -> list[ApplicationView]:
    """Владелец читает отклики только своей вакансии."""
    return await service.applications(db, principal.user.id, "employer", identifier)


@router.get("/candidate/applications/{identifier}", response_model=ApplicationView)
async def candidate_view(
    identifier: UUID, db: Db, principal: Candidate
) -> ApplicationView:
    """Читает одну запись собственной истории без смены статуса."""
    return await service.action(db, principal.user.id, "candidate", identifier, None)


@router.get("/employer/applications/{identifier}", response_model=ApplicationView)
async def employer_view(
    identifier: UUID, db: Db, principal: Verified
) -> ApplicationView:
    """Исторический снимок не заменяет повторную проверку приватности."""
    return await service.action(db, principal.user.id, "employer", identifier, None)


@router.post("/applications/{identifier}/view", response_model=ApplicationView)
async def view(identifier: UUID, db: Db, principal: Verified) -> ApplicationView:
    """Работодатель отмечает просмотр собственного отклика."""
    return await service.action(db, principal.user.id, "employer", identifier, "viewed")


@router.post("/applications/{identifier}/accept", response_model=ApplicationView)
async def accept(identifier: UUID, db: Db, principal: Verified) -> ApplicationView:
    """Принимает отклик; разрешение уже выдано кандидатом при подаче."""
    return await service.action(
        db, principal.user.id, "employer", identifier, "accepted"
    )


@router.post("/applications/{identifier}/reject", response_model=ApplicationView)
async def reject(identifier: UUID, db: Db, principal: Verified) -> ApplicationView:
    """Отклоняет отклик без подмены согласия кандидата."""
    return await service.action(
        db, principal.user.id, "employer", identifier, "rejected"
    )


@router.post("/applications/{identifier}/withdraw", response_model=ApplicationView)
async def withdraw(identifier: UUID, db: Db, principal: Candidate) -> ApplicationView:
    """Отзывает только собственный отклик и только связанное разрешение."""
    return await service.action(
        db, principal.user.id, "candidate", identifier, "withdrawn"
    )
