import asyncio
import hashlib
import hmac
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import Request
from pwdlib import PasswordHash
from pydantic import ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import (
    AuthActionToken,
    AuthRateBucket,
    AuthSession,
    UsedRefreshToken,
    User,
    UserIdentity,
)
from app.auth.schemas import (
    AccessView,
    Claims,
    Credentials,
    Registration,
    TokenBundle,
    UserView,
)
from app.candidate_profile.models import CandidateContact, CandidateProfile
from app.core.config import Settings
from app.core.errors import ApiError
from app.employer.models import EmployerProfile
from app.notifications.queue import enqueue, utc_now

PASSWORDS = PasswordHash.recommended()
DUMMY_HASH = PASSWORDS.hash("no-such-user-dummy-password")


def digest(value: str) -> str:
    """Хеширует случайные токены; это не алгоритм хранения паролей."""
    return hashlib.sha256(value.encode()).hexdigest()


def view_user(user: User) -> UserView:
    """Даёт собственную карточку учётной записи без закрытых полей."""
    return UserView(
        id=user.id,
        role=user.role,
        email=user.email_normalized,
        email_verified=user.email_verified_at is not None,
        assessment_allowed=user.role == "candidate"
        and user.email_verified_at is not None,
    )


class RefreshReplay(RuntimeError):
    """API должен завершить транзакцию отзыва перед возвратом ошибки."""


class AuthService:
    """Локальная авторизация с серверной проверкой каждой сессии."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key = settings.jwt_secret.get_secret_value()
        if not self.key:
            self.key = settings.jwt_secret_file.read_text().strip()
        if len(self.key) < 32:
            raise ApiError(503, "auth_not_configured", "Авторизация не настроена.")

    def access(self, user: User, session: AuthSession) -> AccessView:
        """Подписывает только необходимые claims фиксированным HS256."""
        now = utc_now()
        token = jwt.encode(
            {
                "iss": self.settings.jwt_issuer,
                "aud": self.settings.jwt_audience,
                "sub": str(user.id),
                "sid": str(session.id),
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=15)).timestamp()),
            },
            self.key,
            algorithm="HS256",
        )
        return AccessView(access_token=token)

    async def issue_action(
        self, session: AsyncSession, user: User, purpose: str
    ) -> None:
        """Атомарно сохраняет хеш токена и ставит письмо в долговечную очередь."""
        now = utc_now()
        await session.execute(
            update(AuthActionToken)
            .where(
                AuthActionToken.user_id == user.id,
                AuthActionToken.purpose == purpose,
                AuthActionToken.used_at.is_(None),
            )
            .values(used_at=now)
        )
        identifier = uuid4()
        raw = f"{identifier}.{secrets.token_urlsafe(32)}"
        session.add(
            AuthActionToken(
                id=identifier,
                user_id=user.id,
                purpose=purpose,
                token_hash=digest(raw),
                expires_at=now
                + timedelta(minutes=60 if purpose == "verify_email" else 30),
            )
        )
        await enqueue(
            session,
            kind="auth_email",
            deduplication_key=f"auth-email:{identifier}",
            payload={"email": user.email_normalized, "token": raw, "purpose": purpose},
            now=now,
        )

    async def register(self, session: AsyncSession, data: Registration) -> UserView:
        """Создаёт учётную запись, ролевой профиль и письмо в одной транзакции."""
        hashed = await asyncio.to_thread(
            PASSWORDS.hash, data.password.get_secret_value()
        )
        user = User(
            email_normalized=str(data.email),
            password_hash=hashed,
            role=data.role,
            created_at=utc_now(),
        )
        session.add(user)
        await session.flush()
        session.add(
            UserIdentity(
                user_id=user.id,
                issuer="local",
                subject=str(data.email),
                linked_at=utc_now(),
            )
        )
        if data.role == "candidate":
            profile = CandidateProfile(user_id=user.id)
            session.add(profile)
            await session.flush()
            session.add(
                CandidateContact(
                    candidate_id=profile.id, email=str(data.email), updated_at=utc_now()
                )
            )
        else:
            session.add(EmployerProfile(user_id=user.id))
        await self.issue_action(session, user, "verify_email")
        return view_user(user)

    async def login(self, session: AsyncSession, data: Credentials) -> TokenBundle:
        """Проверяет Argon2id вне event loop и создаёт сохраняемую сессию."""
        user = await session.scalar(
            select(User)
            .where(User.email_normalized == str(data.email))
            .with_for_update()
        )
        valid = await asyncio.to_thread(
            PASSWORDS.verify,
            data.password.get_secret_value(),
            user.password_hash if user else DUMMY_HASH,
        )
        if not valid or not user or user.status != "active":
            raise ApiError(401, "invalid_credentials", "Неверные данные для входа.")
        identifier = uuid4()
        raw = f"{identifier}.{secrets.token_urlsafe(32)}"
        csrf = secrets.token_urlsafe(32)
        row = AuthSession(
            id=identifier,
            user_id=user.id,
            refresh_token_hash=digest(raw),
            csrf_hash=digest(csrf),
            expires_at=utc_now() + timedelta(days=7),
        )
        session.add(row)
        await session.flush()
        return TokenBundle(
            access=self.access(user, row),
            refresh=raw,
            csrf=csrf,
            expires_at=row.expires_at,
        )

    async def principal(
        self, session: AsyncSession, token: str
    ) -> tuple[User, AuthSession]:
        """JWT недостаточно: повторно проверяет статус пользователя и сессии в БД."""
        try:
            claims = Claims.model_validate(
                jwt.decode(
                    token,
                    self.key,
                    algorithms=["HS256"],
                    issuer=self.settings.jwt_issuer,
                    audience=self.settings.jwt_audience,
                    options={"require": ["iss", "aud", "exp", "sub", "sid"]},
                )
            )
        except jwt.InvalidTokenError, ValidationError:
            raise ApiError(401, "invalid_access", "Войдите в аккаунт.") from None
        row = await session.get(AuthSession, claims.sid)
        user = await session.get(User, claims.sub)
        if (
            not row
            or not user
            or row.user_id != user.id
            or row.revoked_at
            or row.expires_at <= utc_now()
            or user.status != "active"
        ):
            raise ApiError(401, "session_inactive", "Сессия завершена. Войдите снова.")
        return user, row

    async def cookie_session(
        self, session: AsyncSession, raw: str, csrf: str
    ) -> AuthSession:
        """Блокирует текущую сессию; случайный неверный токен её не отзывает."""
        try:
            identifier = UUID(raw.split(".", 1)[0])
        except ValueError:
            raise ApiError(401, "invalid_refresh", "Войдите снова.") from None
        row = await session.scalar(
            select(AuthSession).where(AuthSession.id == identifier).with_for_update()
        )
        if not row or row.revoked_at or row.expires_at <= utc_now():
            raise ApiError(401, "invalid_refresh", "Войдите снова.")
        if not hmac.compare_digest(row.csrf_hash, digest(csrf)):
            raise ApiError(
                403, "csrf_failed", "Обновите страницу и повторите действие."
            )
        hashed = digest(raw)
        if not hmac.compare_digest(row.refresh_token_hash, hashed):
            old = await session.get(UsedRefreshToken, hashed)
            if old and old.session_id == row.id:
                row.revoked_at = utc_now()
                raise RefreshReplay
            raise ApiError(401, "invalid_refresh", "Войдите снова.")
        return row

    async def rotate(self, session: AsyncSession, raw: str, csrf: str) -> TokenBundle:
        """Ротация и сохранение старого хеша атомарны под блокировкой сессии."""
        row = await self.cookie_session(session, raw, csrf)
        user = await session.get(User, row.user_id)
        if not user or user.status != "active":
            raise ApiError(401, "session_inactive", "Войдите снова.")
        session.add(
            UsedRefreshToken(token_hash=row.refresh_token_hash, session_id=row.id)
        )
        replacement = f"{row.id}.{secrets.token_urlsafe(32)}"
        row.refresh_token_hash = digest(replacement)
        row.rotation_version += 1
        return TokenBundle(
            access=self.access(user, row),
            refresh=replacement,
            csrf=csrf,
            expires_at=row.expires_at,
        )

    async def action(
        self, session: AsyncSession, raw: str, purpose: str, password: str | None = None
    ) -> None:
        """Одноразовое действие блокирует владельца, затем токен в едином порядке."""
        hashed = digest(raw)
        found = await session.scalar(
            select(AuthActionToken).where(AuthActionToken.token_hash == hashed)
        )
        if not found:
            raise ApiError(
                400, "invalid_action_token", "Ссылка недействительна или устарела."
            )
        user = await session.scalar(
            select(User).where(User.id == found.user_id).with_for_update()
        )
        row = await session.scalar(
            select(AuthActionToken)
            .where(AuthActionToken.id == found.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not user
            or user.status != "active"
            or not row
            or row.purpose != purpose
            or row.used_at
            or row.expires_at <= utc_now()
        ):
            raise ApiError(
                400, "invalid_action_token", "Ссылка недействительна или устарела."
            )
        row.used_at = utc_now()
        if purpose == "verify_email":
            user.email_verified_at = utc_now()
        else:
            assert password is not None
            user.password_hash = await asyncio.to_thread(PASSWORDS.hash, password)
            await session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=utc_now())
            )
            await session.execute(
                update(AuthActionToken)
                .where(
                    AuthActionToken.user_id == user.id,
                    AuthActionToken.purpose == purpose,
                    AuthActionToken.used_at.is_(None),
                )
                .values(used_at=utc_now())
            )


async def rate_limit(request: Request, purpose: str, identity: str = "") -> None:
    """Лимит коммитится отдельно: ошибки входа не откатывают число попыток."""
    settings: Settings = request.app.state.settings
    now = utc_now()
    minute = int(now.timestamp()) // 60
    address = request.client.host if request.client else "unknown"
    keys = {digest(f"{purpose}:ip:{address}:{minute}")}
    if identity:
        keys.add(digest(f"{purpose}:identity:{identity.lower()}:{minute}"))
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessions
    counts: list[int] = []
    async with sessions.begin() as session:
        await session.execute(
            delete(AuthRateBucket).where(AuthRateBucket.expires_at < now)
        )
        for key in sorted(keys):
            count = await session.scalar(
                insert(AuthRateBucket)
                .values(key=key, count=1, expires_at=now + timedelta(minutes=2))
                .on_conflict_do_update(
                    index_elements=[AuthRateBucket.key],
                    set_={"count": AuthRateBucket.count + 1},
                )
                .returning(AuthRateBucket.count)
            )
            counts.append(count or 0)
    if not counts or max(counts) > settings.auth_rate_limit * (
        6 if purpose == "refresh" else 1
    ):
        raise ApiError(
            429, "rate_limited", "Слишком много запросов. Попробуйте через минуту."
        )
