from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Credentials(BaseModel):
    """Вход без полей роли, внутренних ID и произвольных claims."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value: str) -> str:
        """Фиксирует единую локальную идентичность независимо от регистра."""
        return value.lower()


class Registration(Credentials):
    """Публично доступны только две продуктовые роли."""

    role: Literal["candidate", "employer"]


class EmailRequest(BaseModel):
    """Запрос письма без подтверждения существования адреса."""

    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class ActionRequest(BaseModel):
    """Одноразовый ограниченный токен из письма."""

    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=20, max_length=256)


class ResetConfirmation(ActionRequest):
    """Новый пароль передаётся отдельно от одноразового токена."""

    password: SecretStr = Field(min_length=12, max_length=128)


class UserView(BaseModel):
    """Только собственная учётная запись, без пароля и токенов."""

    id: UUID
    role: str
    email: str
    email_verified: bool
    assessment_allowed: bool


class AccessView(BaseModel):
    """Access хранится в памяти браузера, refresh никогда не возвращается JSON."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 900


class Claims(BaseModel):
    """Claims проверяются PyJWT и затем типизируются перед загрузкой сессии."""

    sub: UUID
    sid: UUID
    exp: int
    iss: str
    aud: str


class MessageView(BaseModel):
    """Нейтральное сообщение не раскрывает наличие пользователя."""

    detail: str


class TokenBundle(BaseModel):
    """Внутренняя модель для установки cookie, не выходная модель endpoint."""

    access: AccessView
    refresh: str
    csrf: str
    expires_at: datetime
