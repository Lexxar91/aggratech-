from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


class Privacy(BaseModel):
    """Публикация карточки не даёт права на контакт или скрытое имя."""

    model_config = ConfigDict(extra="forbid")
    visible_to_employers: bool = False
    show_name: bool = False


class WorkPreferences(BaseModel):
    """Отсутствующие предпочтения сохраняются неизвестными."""

    model_config = ConfigDict(extra="forbid")
    formats: list[Literal["remote", "hybrid", "office"]] = Field(
        default_factory=list, max_length=3
    )
    location: str | None = Field(default=None, max_length=120)


class ProfileInput(BaseModel):
    """Полный ручной ввод без присвоения категории и подтверждённых навыков."""

    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=4000)
    experience: str = Field(default="", max_length=8000)
    salary_min: Decimal | None = Field(
        default=None, ge=0, le=9999999999, decimal_places=2
    )
    salary_max: Decimal | None = Field(
        default=None, ge=0, le=9999999999, decimal_places=2
    )
    salary_basis: Literal["gross"] = "gross"
    available_from: date | None = None
    work_preferences: WorkPreferences = Field(default_factory=WorkPreferences)
    technology_ids: list[UUID] = Field(default_factory=list, max_length=30)
    confirm_preferences: bool = False
    consent_version: Literal["profile-v1"] | None = None

    @model_validator(mode="after")
    def salary_range(self) -> ProfileInput:
        """Не допускает неполный или обратный диапазон зарплаты."""
        if (self.salary_min is None) != (self.salary_max is None):
            raise ValueError("Укажите обе границы зарплаты или оставьте обе пустыми.")
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_max < self.salary_min
        ):
            raise ValueError("Верхняя граница меньше нижней.")
        if self.confirm_preferences and (
            self.salary_min is None or not self.work_preferences.formats
        ):
            raise ValueError("Для подтверждения нужны зарплата и формат работы.")
        if len(set(self.technology_ids)) != len(self.technology_ids):
            raise ValueError("Технологии не должны повторяться.")
        return self


class SafeCard(BaseModel):
    """Единая безопасная проекция для работодателя и его PDF."""

    id: UUID
    display_name: str
    summary: str
    experience: str
    salary_min: Decimal | None
    salary_max: Decimal | None
    salary_basis: str
    available_from: date | None
    work_preferences: WorkPreferences
    technology_ids: list[UUID]
    technology_names: list[str]


class ProfileView(SafeCard):
    """Собственный профиль дополнен настройками, но не контактами."""

    privacy: Privacy
    preferences_confirmed_at: datetime | None
    consent_version: str | None
    consented_at: datetime | None
    version: int


class ContactsInput(BaseModel):
    """Закрытые контакты отдельно от карточки."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    phone: str = Field(default="", max_length=32)
    messengers: dict[str, str] = Field(default_factory=dict, max_length=5)

    @model_validator(mode="after")
    def messenger_lengths(self) -> ContactsInput:
        """Ограничивает размер названий и адресов мессенджеров."""
        if any(len(k) > 32 or len(v) > 160 for k, v in self.messengers.items()):
            raise ValueError("Слишком длинный адрес мессенджера.")
        return self


class ContactsView(ContactsInput):
    updated_at: datetime


class BlockView(BaseModel):
    employer_id: UUID
    company_name: str
