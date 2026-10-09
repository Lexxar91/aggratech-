import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from pydantic import SecretStr
from pypdf import PdfReader
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.dependencies import Principal, require_verified_candidate
from app.auth.models import AuthActionToken, AuthSession, User
from app.core.config import Settings
from app.main import create_app
from app.notifications.models import BackgroundJob
from app.notifications.queue import utc_now

pytestmark = pytest.mark.integration
PASSWORD = "initial-password-12345"
KEY = "test-only-signing-key-long-enough-123456789"
ORIGIN = "https://testserver"


@pytest.fixture
async def auth_app(
    sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[FastAPI]:
    async with sessions.begin() as db:
        await db.execute(text("TRUNCATE users, auth_rate_buckets CASCADE"))
    settings = Settings(
        database_url=SecretStr(os.environ["TEST_DATABASE_URL"]),
        jwt_secret=SecretStr(KEY),
        public_origin=ORIGIN,
        allowed_origins=[],
        auth_rate_limit=100,
    )
    application = create_app(settings)

    async def gated(
        principal: Annotated[Principal, Depends(require_verified_candidate)],
    ) -> dict[str, str]:
        return {"status": "allowed"}

    # Тестирует обязательную dependency без создания заглушки assessment в продукте.
    application.router.add_api_route("/test/verified-gate", gated)
    application.router.routes.insert(0, application.router.routes.pop())
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(auth_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as connection:
        yield connection


async def register(
    client: httpx.AsyncClient,
    email: str = "candidate@example.com",
    role: str = "candidate",
) -> UUID:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "role": role},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def login(
    client: httpx.AsyncClient,
    email: str = "candidate@example.com",
    password: str = PASSWORD,
) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    token = str(response.json()["access_token"])
    client.headers["Authorization"] = f"Bearer {token}"
    return token


async def action_token(
    sessions: async_sessionmaker[AsyncSession], email: str, purpose: str
) -> str:
    async with sessions() as db:
        jobs = list(
            await db.scalars(
                select(BackgroundJob)
                .where(BackgroundJob.kind == "auth_email")
                .order_by(BackgroundJob.available_at.desc())
            )
        )
        return next(
            str(job.payload["token"])
            for job in jobs
            if job.payload.get("email") == email
            and job.payload.get("purpose") == purpose
        )


def csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["csrf_token"]}


async def test_register_confirm_one_use_and_gate(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    identifier = await register(client, "Candidate@EXAMPLE.COM")
    async with sessions() as db:
        user = await db.get(User, identifier)
        assert user and user.email_normalized == "candidate@example.com"
        assert (
            user.password_hash.startswith("$argon2id$")
            and PASSWORD not in user.password_hash
        )
    await login(client)
    assert (await client.get("/test/verified-gate")).status_code == 403
    assert not (await client.get("/api/v1/auth/me")).json()["assessment_allowed"]
    token = await action_token(sessions, "candidate@example.com", "verify_email")
    async with sessions() as db:
        row = await db.scalar(select(AuthActionToken))
        assert row and token not in row.token_hash
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": token})
    ).status_code == 400
    assert (await client.get("/test/verified-gate")).status_code == 200
    assert (await client.get("/api/v1/auth/me")).json()["assessment_allowed"]
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "candidate@example.com",
                "password": PASSWORD,
                "role": "candidate",
            },
        )
    ).status_code == 409
    rejected = await client.post(
        "/api/v1/auth/register",
        json={"email": "staff@example.com", "password": PASSWORD, "role": "staff"},
    )
    assert rejected.status_code == 422 and PASSWORD not in rejected.text


async def test_rotation_replay_revokes_access_and_logout(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    original_access = await login(client)
    original_refresh = client.cookies["refresh_token"]
    csrf = client.cookies["csrf_token"]
    response = await client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
    assert response.status_code == 200
    assert client.cookies["refresh_token"] != original_refresh
    assert "refresh" not in response.json()
    cookie = response.headers.get_list("set-cookie")[0].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    replay = await client.post(
        "/api/v1/auth/refresh",
        headers={
            "Cookie": f"refresh_token={original_refresh}; csrf_token={csrf}",
            "X-CSRF-Token": csrf,
        },
    )
    assert replay.status_code == 401 and replay.json()["code"] == "refresh_replayed"
    assert (
        await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {original_access}"}
        )
    ).status_code == 401
    await login(client)
    assert (
        await client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    ).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_cookie_csrf_and_origin(client: httpx.AsyncClient) -> None:
    await register(client)
    await login(client)
    for path in ("refresh", "logout"):
        assert (await client.post(f"/api/v1/auth/{path}")).status_code == 403
        assert (
            await client.post(
                f"/api/v1/auth/{path}",
                headers={**csrf_headers(client), "Origin": "https://evil.example"},
            )
        ).status_code == 403
        assert (
            await client.post(f"/api/v1/auth/{path}", headers={"X-CSRF-Token": "wrong"})
        ).status_code == 403
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "candidate@example.com", "password": PASSWORD},
            headers={"Origin": "null"},
        )
    ).status_code == 403
    assert (await client.get("/api/v1/auth/me")).status_code == 200


async def test_reset_expiry_one_use_all_sessions(
    client: httpx.AsyncClient,
    auth_app: FastAPI,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await register(client)
    access = await login(client)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as other:
        second_access = await login(other)
    for email in ("candidate@example.com", "unknown@example.com"):
        response = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": email}
        )
        assert response.status_code == 202
    token = await action_token(sessions, "candidate@example.com", "password_reset")
    assert (
        await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "replacement-password-123"},
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "replacement-password-123"},
        )
    ).status_code == 400
    for value in (access, second_access):
        assert (
            await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {value}"}
            )
        ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "candidate@example.com", "password": PASSWORD},
        )
    ).status_code == 401
    await login(client, password="replacement-password-123")
    verification = await action_token(sessions, "candidate@example.com", "verify_email")
    async with sessions.begin() as db:
        await db.execute(
            update(AuthActionToken)
            .where(AuthActionToken.purpose == "verify_email")
            .values(expires_at=utc_now() - timedelta(seconds=1))
        )
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": verification})
    ).status_code == 400


async def test_access_claims_current_status_and_rate_limit(
    client: httpx.AsyncClient,
    auth_app: FastAPI,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    identifier = await register(client)
    access = await login(client)
    decoded = jwt.decode(
        access, KEY, algorithms=["HS256"], audience="aggratech-api", issuer="aggratech"
    )
    for changes in (
        {"aud": "other"},
        {"iss": "other"},
        {"exp": 1},
        {"sub": str(uuid4())},
        {"sid": str(uuid4())},
    ):
        bad = jwt.encode({**decoded, **changes}, KEY, algorithm="HS256")
        assert (
            await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"}
            )
        ).status_code == 401
    bad_alg = jwt.encode(decoded, KEY, algorithm="HS384")
    assert (
        await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {bad_alg}"}
        )
    ).status_code == 401
    async with sessions.begin() as db:
        await db.execute(
            update(User).where(User.id == identifier).values(status="disabled")
        )
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
    ).status_code == 401
    auth_app.state.settings.auth_rate_limit = 2
    async with sessions.begin() as db:
        await db.execute(text("TRUNCATE auth_rate_buckets"))
    for i in range(2):
        assert (
            await client.post(
                "/api/v1/auth/login",
                json={"email": f"unknown{i}@example.com", "password": PASSWORD},
            )
        ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "other@example.com", "password": PASSWORD},
        )
    ).status_code == 429


async def test_role_owner_privacy_blocks_pdf_and_catalogs(
    client: httpx.AsyncClient, auth_app: FastAPI
) -> None:
    await register(client)
    await login(client)
    technologies = (await client.get("/api/v1/catalog/technologies")).json()
    for name, count in (
        ("specializations", 1),
        ("grades", 2),
        ("categories", 2),
        ("skills", 5),
    ):
        assert len((await client.get(f"/api/v1/catalog/{name}")).json()) == count
    blueprint = json.loads(
        await asyncio.to_thread(Path("bank/blueprints.json").read_text)
    )
    expected_skills = {
        skill for family in blueprint["families"] for skill in family["skills"]
    }
    actual_skills = {
        item["code"] for item in (await client.get("/api/v1/catalog/skills")).json()
    }
    assert actual_skills == expected_skills
    data = {
        "display_name": "Скрытое Имя",
        "summary": "Работа с данными <tag>",
        "experience": "Два года",
        "salary_min": "100000.00",
        "salary_max": "150000.00",
        "work_preferences": {"formats": ["remote"], "location": "Москва"},
        "confirm_preferences": True,
        "consent_version": "profile-v1",
        "technology_ids": [technologies[0]["id"]],
    }
    response = await client.patch("/api/v1/candidate/profile", json=data)
    assert response.status_code == 200, response.text
    candidate_id = response.json()["id"]
    for bad in (
        {**data, "user_id": str(uuid4())},
        {**data, "salary_max": "999"},
        {**data, "salary_max": None},
        {**data, "technology_ids": [str(uuid4())]},
    ):
        assert (
            await client.patch("/api/v1/candidate/profile", json=bad)
        ).status_code == 422
    assert (
        await client.patch(
            "/api/v1/candidate/contacts",
            json={
                "email": "private@example.com",
                "phone": "+79991234567",
                "messengers": {"telegram": "private-handle"},
            },
        )
    ).status_code == 200
    own_pdf = await client.get("/api/v1/candidate/profile.pdf")
    own_text = "".join(
        page.extract_text() for page in PdfReader(BytesIO(own_pdf.content)).pages
    )
    assert (
        "Скрытое Имя" in own_text
        and "Москва" in own_text
        and "private@example.com" in own_text
    )
    assert (await client.get("/api/v1/employer/profile")).status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as employer:
        await register(employer, "employer@example.com", "employer")
        await login(employer, "employer@example.com")
        company = await employer.patch(
            "/api/v1/employer/profile",
            json={
                "company_name": "Компания",
                "representative_contact": "secret-representative@example.com",
            },
        )
        assert company.status_code == 200
        employer_id = company.json()["id"]
        for path in (
            "candidate/profile",
            "candidate/contacts",
            "candidate/profile.pdf",
            "candidate/blocks",
        ):
            assert (await employer.get(f"/api/v1/{path}")).status_code == 403
        assert (
            await employer.get(f"/api/v1/candidates/{candidate_id}")
        ).status_code == 404
        assert (
            await client.patch(
                "/api/v1/candidate/privacy",
                json={"visible_to_employers": True, "show_name": False},
            )
        ).status_code == 200
        card = await employer.get(f"/api/v1/candidates/{candidate_id}")
        assert card.status_code == 200 and card.json()["display_name"] == "Кандидат"
        for secret in (
            "Скрытое Имя",
            "private@example.com",
            "+79991234567",
            "private-handle",
            "user_id",
        ):
            assert secret not in card.text
        public_pdf = await employer.get(
            f"/api/v1/candidates/{candidate_id}/profile.pdf"
        )
        public_text = "".join(
            page.extract_text() for page in PdfReader(BytesIO(public_pdf.content)).pages
        )
        assert "Москва" in public_text and "Работа с данными <tag>" in public_text
        for secret in (
            "Скрытое Имя",
            "private@example.com",
            "+79991234567",
            "private-handle",
        ):
            assert secret not in public_text
        assert (
            "secret-representative" not in (await client.get("/api/v1/employers")).text
        )
        for _ in range(2):
            assert (
                await client.put(f"/api/v1/candidate/blocks/{employer_id}")
            ).status_code == 204
        for suffix in ("", "/profile.pdf"):
            assert (
                await employer.get(f"/api/v1/candidates/{candidate_id}{suffix}")
            ).status_code == 404
        assert (
            await client.delete(f"/api/v1/candidate/blocks/{employer_id}")
        ).status_code == 204
        assert (
            await employer.get(f"/api/v1/candidates/{candidate_id}")
        ).status_code == 200
        await client.patch(
            "/api/v1/candidate/privacy",
            json={"visible_to_employers": False, "show_name": True},
        )
        assert (
            await employer.get(f"/api/v1/candidates/{candidate_id}/profile.pdf")
        ).status_code == 404
        assert (
            await client.patch(
                "/api/v1/candidate/profile", json={**data, "consent_version": None}
            )
        ).status_code == 200
        await client.patch(
            "/api/v1/candidate/privacy",
            json={"visible_to_employers": True, "show_name": True},
        )
        assert (
            await employer.get(f"/api/v1/candidates/{candidate_id}")
        ).status_code == 404
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
    ) as second:
        await register(second, "second@example.com")
        await login(second, "second@example.com")
        assert (await second.get("/api/v1/candidate/profile")).json()[
            "id"
        ] != candidate_id
        assert (
            "private@example.com"
            not in (await second.get("/api/v1/candidate/contacts")).text
        )
        assert (
            await second.get(f"/api/v1/candidates/{candidate_id}")
        ).status_code == 403
        assert (
            await second.patch(
                "/api/v1/candidate/profile",
                json={"id": candidate_id, "display_name": "Подмена"},
            )
        ).status_code == 422


async def test_resend_invalidates_previous_and_concurrent_use(
    client: httpx.AsyncClient,
    auth_app: FastAPI,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await register(client)
    old = await action_token(sessions, "candidate@example.com", "verify_email")
    assert (
        await client.post(
            "/api/v1/auth/resend-verification", json={"email": "candidate@example.com"}
        )
    ).status_code == 202
    fresh = await action_token(sessions, "candidate@example.com", "verify_email")
    assert fresh != old
    assert (
        await client.post("/api/v1/auth/verify-email", json={"token": old})
    ).status_code == 400
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=auth_app), base_url=ORIGIN
    ) as other:
        results = await asyncio.gather(
            client.post("/api/v1/auth/verify-email", json={"token": fresh}),
            other.post("/api/v1/auth/verify-email", json={"token": fresh}),
        )
    assert sorted(result.status_code for result in results) == [200, 400]


async def test_session_expiry_and_api_restart(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    identifier = await register(client)
    access = await login(client)
    # Независимый экземпляр приложения и пула сохраняет действующую серверную сессию.
    settings = Settings(
        database_url=SecretStr(os.environ["TEST_DATABASE_URL"]),
        jwt_secret=SecretStr(KEY),
        public_origin=ORIGIN,
        allowed_origins=[],
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url=ORIGIN
        ) as restarted:
            response = await restarted.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
            )
            assert response.status_code == 200 and response.json()["id"] == str(
                identifier
            )
    async with sessions.begin() as db:
        await db.execute(
            update(AuthSession)
            .where(AuthSession.user_id == identifier)
            .values(expires_at=utc_now() - timedelta(seconds=1))
        )
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", headers=csrf_headers(client))
    ).status_code == 401
