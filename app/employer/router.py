from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.auth.dependencies import Candidate, Db, Employer
from app.core.errors import ApiError
from app.employer.models import EmployerProfile

router = APIRouter(tags=["employer"])


class EmployerInput(BaseModel):
    """Ручной профиль компании без потребностей и вакансий следующих этапов."""

    model_config = ConfigDict(extra="forbid")
    company_name: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=4000)
    industry: str = Field(default="", max_length=120)
    representative_contact: str = Field(default="", max_length=254)


class EmployerView(EmployerInput):
    id: UUID
    version: int


class CompanyCard(BaseModel):
    id: UUID
    company_name: str


async def profile(db: Db, user_id: UUID, *, lock: bool = False) -> EmployerProfile:
    """Ищет компанию исключительно по текущему владельцу."""
    query = select(EmployerProfile).where(EmployerProfile.user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if not row:
        raise ApiError(404, "profile_missing", "Компания не найдена.")
    return row


def view(row: EmployerProfile) -> EmployerView:
    """Создаёт собственный ответ из явного набора полей."""
    return EmployerView(
        id=row.id,
        company_name=row.company_name,
        description=row.description,
        industry=row.industry,
        representative_contact=row.representative_contact,
        version=row.version,
    )


@router.get("/employer/profile", response_model=EmployerView)
async def own_profile(db: Db, principal: Employer) -> EmployerView:
    """Читает компанию текущего работодателя."""
    return view(await profile(db, principal.user.id))


@router.patch("/employer/profile", response_model=EmployerView)
async def update_profile(
    data: EmployerInput, db: Db, principal: Employer
) -> EmployerView:
    """Сохраняет ручной профиль владельца."""
    row = await profile(db, principal.user.id, lock=True)
    for name, value in data.model_dump().items():
        setattr(row, name, value)
    row.version += 1
    return view(row)


@router.get("/employers", response_model=list[CompanyCard])
async def companies(db: Db, principal: Candidate) -> list[CompanyCard]:
    """Список для блокировок не содержит контакт представителя."""
    rows = await db.scalars(
        select(EmployerProfile)
        .where(EmployerProfile.status == "active")
        .order_by(EmployerProfile.company_name)
        .limit(200)
    )
    return [CompanyCard(id=row.id, company_name=row.company_name) for row in rows]
