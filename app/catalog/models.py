from uuid import UUID

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Specialization(Base):
    """Активная специализация из согласованного справочника."""

    __tablename__ = "specializations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool]


class Grade(Base):
    """Уровень справочника; наличие строки не присваивает грейд кандидату."""

    __tablename__ = "grades"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    sort_order: Mapped[int]
    active: Mapped[bool]


class Category(Base):
    """Связь специализации с грейдом без пользовательских подтверждений."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("specialization_id", "grade_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    specialization_id: Mapped[UUID] = mapped_column(ForeignKey("specializations.id"))
    grade_id: Mapped[UUID] = mapped_column(ForeignKey("grades.id"))


class Skill(Base):
    """Согласованный навык backend со статусом активности."""

    __tablename__ = "skills"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    specialization_id: Mapped[UUID] = mapped_column(ForeignKey("specializations.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool]


class Technology(Base):
    """Технология для ручного заявления, без присвоения подтверждённого навыка."""

    __tablename__ = "technologies"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool]
