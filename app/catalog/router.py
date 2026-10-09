from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import Current, Db
from app.catalog.models import Category, Grade, Skill, Specialization, Technology

router = APIRouter(prefix="/catalog", tags=["catalog"])


class NamedItem(BaseModel):
    id: UUID
    code: str
    name: str


class CategoryItem(BaseModel):
    id: UUID
    specialization_id: UUID
    grade_id: UUID


async def named_items[NamedModel: (Specialization, Grade, Skill, Technology)](
    db: Db, model: type[NamedModel]
) -> list[NamedItem]:
    """Возвращает активные строки справочника по явной DTO."""
    rows = await db.scalars(
        select(model).where(model.active.is_(True)).order_by(model.code)
    )
    return [NamedItem(id=row.id, code=row.code, name=row.name) for row in rows]


@router.get("/specializations", response_model=list[NamedItem])
async def specializations(db: Db, principal: Current) -> list[NamedItem]:
    """Специализации не присваивают категорию пользователю."""
    return await named_items(db, Specialization)


@router.get("/grades", response_model=list[NamedItem])
async def grades(db: Db, principal: Current) -> list[NamedItem]:
    """Возвращает Junior и Middle из справочника."""
    return await named_items(db, Grade)


@router.get("/skills", response_model=list[NamedItem])
async def skills(db: Db, principal: Current) -> list[NamedItem]:
    """Пять согласованных навыков backend."""
    return await named_items(db, Skill)


@router.get("/technologies", response_model=list[NamedItem])
async def technologies(db: Db, principal: Current) -> list[NamedItem]:
    """Технологии используются только для ручного заявления."""
    return await named_items(db, Technology)


@router.get("/categories", response_model=list[CategoryItem])
async def categories(db: Db, principal: Current) -> list[CategoryItem]:
    """Категории справочника не являются оценкой кандидата."""
    rows = await db.scalars(select(Category).order_by(Category.id))
    return [
        CategoryItem(
            id=row.id, specialization_id=row.specialization_id, grade_id=row.grade_id
        )
        for row in rows
    ]
