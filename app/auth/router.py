from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.dependencies import (
    Current,
    Db,
    Service,
    cookie_credentials,
    require_origin,
)
from app.auth.models import User
from app.auth.schemas import (
    AccessView,
    ActionRequest,
    Credentials,
    EmailRequest,
    MessageView,
    Registration,
    ResetConfirmation,
    TokenBundle,
    UserView,
)
from app.auth.service import RefreshReplay, rate_limit, view_user
from app.core.errors import ApiError
from app.notifications.queue import utc_now

router = APIRouter(prefix="/auth", tags=["auth"])


def set_cookies(response: Response, bundle: TokenBundle) -> None:
    """Refresh недоступен JavaScript, обе cookie Secure и SameSite=Strict."""
    seconds = max(0, int((bundle.expires_at - utc_now()).total_seconds()))
    response.set_cookie(
        "refresh_token",
        bundle.refresh,
        max_age=seconds,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/api/v1/auth",
    )
    response.set_cookie(
        "csrf_token",
        bundle.csrf,
        max_age=seconds,
        httponly=False,
        secure=True,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_cookies(response: Response) -> None:
    """Удаляет cookie с теми же path/security параметрами."""
    response.delete_cookie(
        "refresh_token",
        path="/api/v1/auth",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie("csrf_token", path="/", secure=True, samesite="strict")


@router.post("/register", response_model=UserView, status_code=201)
async def register(
    data: Registration, request: Request, db: Db, service: Service
) -> UserView:
    """Публичная регистрация создаёт профиль и ставит подтверждение в очередь."""
    require_origin(request)
    await rate_limit(request, "register", str(data.email))
    try:
        return await service.register(db, data)
    except IntegrityError:
        raise ApiError(
            409, "registration_conflict", "Регистрация с этим адресом недоступна."
        ) from None


@router.post("/login", response_model=AccessView)
async def login(
    data: Credentials, request: Request, response: Response, db: Db, service: Service
) -> AccessView:
    """Возвращает access JWT, refresh сохраняет только в защищённой cookie."""
    require_origin(request)
    await rate_limit(request, "login", str(data.email))
    bundle = await service.login(db, data)
    set_cookies(response, bundle)
    return bundle.access


@router.post("/refresh", response_model=AccessView)
async def refresh(
    request: Request, response: Response, db: Db, service: Service
) -> AccessView:
    """Ротирует refresh; настоящий replay сначала коммитит отзыв сессии."""
    raw, csrf = cookie_credentials(request)
    await rate_limit(request, "refresh")
    try:
        bundle = await service.rotate(db, raw, csrf)
    except RefreshReplay:
        await db.commit()
        raise ApiError(
            401, "refresh_replayed", "Сессия отозвана. Войдите снова."
        ) from None
    set_cookies(response, bundle)
    return bundle.access


@router.post("/logout", response_model=MessageView)
async def logout(
    request: Request, response: Response, db: Db, service: Service
) -> MessageView:
    """Прекращает серверную сессию; старый access больше не действует."""
    raw, csrf = cookie_credentials(request)
    try:
        session = await service.cookie_session(db, raw, csrf)
    except RefreshReplay:
        await db.commit()
    else:
        session.revoked_at = utc_now()
    clear_cookies(response)
    return MessageView(detail="Вы вышли из аккаунта.")


@router.get("/me", response_model=UserView)
async def me(principal: Current) -> UserView:
    """Возвращает только учётную запись текущего владельца."""
    return view_user(principal.user)


@router.post("/verify-email", response_model=MessageView)
async def verify_email(
    data: ActionRequest, request: Request, db: Db, service: Service
) -> MessageView:
    """Подтверждает адрес одноразовым ограниченным по времени токеном."""
    await rate_limit(request, "verify_email")
    await service.action(db, data.token.get_secret_value(), "verify_email")
    return MessageView(detail="Email подтверждён.")


@router.post("/resend-verification", response_model=MessageView, status_code=202)
async def resend(
    data: EmailRequest, request: Request, db: Db, service: Service
) -> MessageView:
    """Нейтральный ответ одинаков для неизвестного и уже подтверждённого адреса."""
    await rate_limit(request, "resend", str(data.email))
    user = await db.scalar(
        select(User)
        .where(User.email_normalized == str(data.email).lower())
        .with_for_update()
    )
    if user and user.status == "active" and user.email_verified_at is None:
        await service.issue_action(db, user, "verify_email")
    return MessageView(detail="Если подтверждение требуется, письмо будет отправлено.")


@router.post("/password-reset/request", response_model=MessageView, status_code=202)
async def reset_request(
    data: EmailRequest, request: Request, db: Db, service: Service
) -> MessageView:
    """Не раскрывает наличие аккаунта, ставит настоящее письмо через worker."""
    await rate_limit(request, "password_reset", str(data.email))
    user = await db.scalar(
        select(User)
        .where(User.email_normalized == str(data.email).lower())
        .with_for_update()
    )
    if user and user.status == "active":
        await service.issue_action(db, user, "password_reset")
    return MessageView(detail="Если адрес зарегистрирован, письмо будет отправлено.")


@router.post("/password-reset/confirm", response_model=MessageView)
async def reset_confirm(
    data: ResetConfirmation,
    request: Request,
    response: Response,
    db: Db,
    service: Service,
) -> MessageView:
    """Одноразово меняет пароль и отзывает все сессии владельца."""
    await rate_limit(request, "password_reset_confirm")
    await service.action(
        db,
        data.token.get_secret_value(),
        "password_reset",
        data.password.get_secret_value(),
    )
    clear_cookies(response)
    return MessageView(detail="Пароль изменён. Войдите снова.")
