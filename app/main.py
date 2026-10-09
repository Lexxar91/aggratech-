import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.responses import Response

from app.auth.router import router as auth_router
from app.candidate_profile.router import router as candidate_router
from app.catalog.router import router as catalog_router
from app.core.config import Settings
from app.core.database import create_database, create_sessions
from app.core.errors import ApiError
from app.core.logging import configure_logging
from app.employer.router import router as employer_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт API и веб-каркас одного origin без запуска пользовательского кода."""
    config = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        application.state.engine = create_database(config)
        application.state.sessions = create_sessions(application.state.engine)
        application.state.settings = config
        try:
            yield
        finally:
            await application.state.engine.dispose()

    application = FastAPI(title="Aggratech", version="0.1.0", lifespan=lifespan)

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        """Возвращает Problem Details без внутренних исключений и секретов."""
        return JSONResponse(
            status_code=error.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Ошибка запроса",
                "status": error.status_code,
                "code": error.code if isinstance(error, ApiError) else "http_error",
                "detail": error.detail,
                "request_id": request.state.request_id,
            },
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        """Не отражает введённые пароли и токены в ошибках валидации."""
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Ошибка ввода",
                "status": 422,
                "code": "validation_failed",
                "detail": "Проверьте поля формы.",
                "fields": [
                    ".".join(str(part) for part in item["loc"])
                    for item in error.errors()
                ],
                "request_id": request.state.request_id,
            },
        )

    for router in (auth_router, candidate_router, employer_router, catalog_router):
        application.include_router(router, prefix="/api/v1")

    @application.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Назначает безопасный request_id и пишет только технические поля запроса."""
        try:
            request_id = str(UUID(request.headers.get("x-request-id", "")))
        except ValueError:
            request_id = str(uuid4())
        request.state.request_id = request_id
        started = perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        logger.info(
            "request_finished",
            extra={
                "event": "request_finished",
                "request_id": request_id,
                "http_status": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @application.get("/health/live", include_in_schema=True)
    async def live() -> dict[str, str]:
        """Проверяет жизнеспособность API независимо от PostgreSQL."""
        return {"status": "alive"}

    @application.get("/health/ready", response_model=None)
    async def ready(request: Request) -> JSONResponse:
        """Проверяет соединение и применённую миграцию с ограниченным ожиданием."""
        try:
            async with asyncio.timeout(config.database_timeout_seconds):
                async with request.app.state.engine.connect() as connection:
                    version = await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    if version is None:
                        raise RuntimeError("migration_missing")
        except SQLAlchemyError, OSError, TimeoutError, RuntimeError:
            return JSONResponse(
                status_code=503,
                content={
                    "type": "about:blank",
                    "title": "База данных не готова",
                    "status": 503,
                    "code": "database_not_ready",
                    "detail": "Проверьте PostgreSQL и применение миграций.",
                    "request_id": request.state.request_id,
                },
                media_type="application/problem+json",
            )
        return JSONResponse({"status": "ready"})

    application.mount(
        "/",
        StaticFiles(directory=Path(__file__).parent / "web", html=True),
        name="web",
    )
    return application


app = create_app()
