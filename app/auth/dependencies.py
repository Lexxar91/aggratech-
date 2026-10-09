import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User
from app.auth.service import AuthService
from app.core.config import Settings
from app.core.errors import ApiError


async def transaction(request: Request) -> AsyncIterator[AsyncSession]:
    """Фиксирует транзакцию до ответа, включая созданную сессию авторизации."""
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with sessions.begin() as session:
        yield session


Db = Annotated[AsyncSession, Depends(transaction, scope="function")]


def auth_service(request: Request) -> AuthService:
    """Читает секрет в синхронном dependency, исполняемом FastAPI в thread pool."""
    settings: Settings = request.app.state.settings
    try:
        return AuthService(settings)
    except OSError:
        raise ApiError(
            503, "auth_not_configured", "Авторизация не настроена."
        ) from None


Service = Annotated[AuthService, Depends(auth_service)]


@dataclass(frozen=True)
class Principal:
    """Внутренний пользователь одинаков для локальной и будущей внешней auth."""

    user: User
    session_id: UUID


bearer = HTTPBearer(auto_error=False)


async def authenticated(
    db: Db,
    service: Service,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    """Каждый bearer-запрос проверяет актуальные User и AuthSession."""
    if credentials is None or len(credentials.credentials) > 4096:
        raise ApiError(401, "authentication_required", "Войдите в аккаунт.")
    user, session = await service.principal(db, credentials.credentials)
    return Principal(user, session.id)


Current = Annotated[Principal, Depends(authenticated)]


async def candidate(principal: Current) -> Principal:
    """Допускает только владельца роли candidate."""
    if principal.user.role != "candidate":
        raise ApiError(403, "candidate_required", "Доступно только кандидату.")
    return principal


async def employer(principal: Current) -> Principal:
    """Допускает только владельца роли employer."""
    if principal.user.role != "employer":
        raise ApiError(403, "employer_required", "Доступно только работодателю.")
    return principal


Candidate = Annotated[Principal, Depends(candidate)]
Employer = Annotated[Principal, Depends(employer)]


async def require_verified_candidate(principal: Candidate) -> Principal:
    """Обязательный gate для зачётного assessment будущего этапа 4."""
    if principal.user.email_verified_at is None:
        raise ApiError(403, "email_verification_required", "Сначала подтвердите email.")
    return principal


def require_origin(request: Request) -> None:
    """Для установки/использования cookie допустимы только заданные origins."""
    settings: Settings = request.app.state.settings
    if request.headers.get("origin") not in {
        settings.public_origin,
        *settings.allowed_origins,
    }:
        raise ApiError(403, "origin_forbidden", "Недопустимый источник запроса.")


def cookie_credentials(request: Request) -> tuple[str, str]:
    """Double submit CSRF дополняется привязкой nonce к сессии в БД."""
    require_origin(request)
    csrf = request.cookies.get("csrf_token", "")
    header = request.headers.get("x-csrf-token", "")
    if (
        not csrf
        or len(csrf) > 256
        or not hmac.compare_digest(csrf.encode(), header.encode())
    ):
        raise ApiError(403, "csrf_failed", "Обновите страницу и повторите действие.")
    raw = request.cookies.get("refresh_token", "")
    if not raw or len(raw) > 256:
        raise ApiError(401, "authentication_required", "Войдите снова.")
    return raw, csrf
