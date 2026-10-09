from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.matching.schemas import ContractModel, Money

ContactField = Literal["email", "phone", "messengers"]
Status = Literal["sent", "viewed", "accepted", "rejected", "expired", "withdrawn"]


class Offer(ContractModel):
    """Только конкретные условия предложения, без данных контактов кандидата."""

    description: str = Field(min_length=1, max_length=4000)
    salary_from: Money = Field(gt=0)
    salary_to: Money = Field(gt=0)
    currency: Literal["RUB"] = "RUB"
    salary_basis: Literal["gross"] = "gross"
    work_formats: list[Literal["remote", "hybrid", "office"]] = Field(
        min_length=1, max_length=3
    )
    location: str | None = Field(default=None, max_length=120)
    desired_start_date: date | None = None
    start_date_required: bool = False
    conditions: str = Field(min_length=1, max_length=4000)
    representative_contact: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def valid_offer(self) -> Offer:
        """Проверяет диапазон, существенные условия и непустой текст."""
        if self.salary_to < self.salary_from:
            raise ValueError("salary_range")
        if len(set(self.work_formats)) != len(self.work_formats):
            raise ValueError("duplicate_formats")
        if (
            any(f in self.work_formats for f in ("office", "hybrid"))
            and not self.location
        ):
            raise ValueError("location_required")
        if self.start_date_required and not self.desired_start_date:
            raise ValueError("date_required")
        if not all(
            s.strip()
            for s in (self.description, self.conditions, self.representative_contact)
        ):
            raise ValueError("text_required")
        return self


class SendInput(ContractModel):
    need_id: UUID
    candidate_id: UUID
    idempotency_key: str = Field(
        min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    offer: Offer


class Acceptance(ContractModel):
    allowed_fields: list[ContactField] = Field(min_length=1, max_length=3)
    consent_version: Literal["contacts-v1"]

    @model_validator(mode="after")
    def distinct_fields(self) -> Acceptance:
        """Согласие относится к конкретному набору полей."""
        if len(set(self.allowed_fields)) != len(self.allowed_fields):
            raise ValueError("duplicate_fields")
        return self


class InvitationView(ContractModel):
    id: UUID
    employer_id: UUID
    candidate_id: UUID
    need_id: UUID
    status: Status
    offer_snapshot: dict[str, object]
    sent_at: datetime
    viewed_at: datetime | None
    expires_at: datetime
    decided_at: datetime | None
    contact_access: bool
