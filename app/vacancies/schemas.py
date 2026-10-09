from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.candidate_profile.schemas import SafeCard
from app.invitations.schemas import Acceptance, Offer
from app.matching.schemas import ContractModel, Money


class VacancyInput(Offer):
    """Зарплата и условия задаются работодателем, при желании с его потребностью."""

    title: str = Field(min_length=1, max_length=160)
    need_id: UUID | None = None

    @model_validator(mode="after")
    def nonblank_title(self) -> VacancyInput:
        if not self.title.strip():
            raise ValueError("title_required")
        return self


class VacancyPatch(ContractModel):
    """Частичное изменение проверяется вместе с текущим снимком и версией."""

    version: StrictInt = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, min_length=1, max_length=4000)
    salary_from: Money | None = Field(default=None, gt=0)
    salary_to: Money | None = Field(default=None, gt=0)
    currency: Literal["RUB"] | None = None
    salary_basis: Literal["gross"] | None = None
    work_formats: list[Literal["remote", "hybrid", "office"]] | None = None
    location: str | None = Field(default=None, max_length=120)
    desired_start_date: date | None = None
    start_date_required: bool | None = None
    conditions: str | None = Field(default=None, min_length=1, max_length=4000)
    representative_contact: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    need_id: UUID | None = None


class VacancyView(VacancyInput):
    id: UUID
    employer_id: UUID
    company_name: str
    status: Literal["published", "closed"]
    published_at: datetime
    closed_at: datetime | None
    version: int


class ApplicationInput(Acceptance):
    """Явное согласие на выбранные контакты, а не произвольные условия вакансии."""

    message: str = Field(default="", max_length=4000)


class ApplicationView(ContractModel):
    id: UUID
    vacancy_id: UUID
    candidate_id: UUID
    employer_id: UUID
    status: Literal["submitted", "viewed", "accepted", "rejected", "withdrawn"]
    vacancy_snapshot: VacancyView
    message: str
    submitted_at: datetime
    updated_at: datetime
    version: int
    contact_access: bool
    allowed_fields: list[str]
    candidate_card: SafeCard | None
    card_notice: str | None
