"""Настоящий PostgreSQL; ручные тестовые профили не подтверждают квалификацию."""

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.candidate_profile.access import ContactGrant, read_contacts, revoke
from app.candidate_profile.models import CandidateProfile
from app.core.errors import ApiError
from app.invitations import service as invitations
from app.invitations.schemas import Acceptance, SendInput
from app.notifications.models import AuditEvent
from app.vacancies import service
from app.vacancies.models import Application, Vacancy
from app.vacancies.schemas import (
    ApplicationInput,
    ApplicationView,
    VacancyInput,
    VacancyPatch,
)
from tests.test_auth_profiles import auth_app as auth_app
from tests.test_auth_profiles import client as client
from tests.test_auth_profiles import login, register
from tests.test_invitations import pdf_text
from tests.test_matching_api import need_body, synthetic_credit, verified

pytestmark = pytest.mark.integration
CONSENT = {"allowed_fields": ["email"], "consent_version": "contacts-v1"}


def vacancy_body() -> dict[str, object]:
    return {
        "title": "Тестовая вакансия Python",
        "description": "Ручное объявление для проверки этапа 8",
        "salary_from": 170000,
        "salary_to": 190000,
        "work_formats": ["remote"],
        "conditions": "Гибкие часы",
        "representative_contact": "company@example.com",
    }


@dataclass
class Actors:
    candidate: UUID
    employer: UUID
    profile: UUID
    vacancy: UUID
    company: UUID


@pytest.fixture
async def actors(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> Actors:
    candidate = await register(client, "stage8-c@example.com")
    await verified(sessions, candidate)
    await login(client, "stage8-c@example.com")
    profile = await client.patch(
        "/api/v1/candidate/profile",
        json={
            "display_name": "Скрытое тестовое имя",
            "summary": "Самоописание, не подтверждённые навыки",
            "consent_version": "profile-v1",
        },
    )
    assert profile.status_code == 200
    await client.patch(
        "/api/v1/candidate/privacy",
        json={"visible_to_employers": True, "show_name": False},
    )
    await client.patch(
        "/api/v1/candidate/contacts",
        json={
            "email": "private-stage8@example.com",
            "phone": "+79990001122",
            "messengers": {"telegram": "secret-stage8"},
        },
    )
    employer = await register(client, "stage8-e@example.com", "employer")
    await verified(sessions, employer)
    await login(client, "stage8-e@example.com")
    response = await client.post("/api/v1/employer/vacancies", json=vacancy_body())
    assert response.status_code == 200, response.text
    return Actors(
        candidate,
        employer,
        UUID(profile.json()["id"]),
        UUID(response.json()["id"]),
        UUID(response.json()["employer_id"]),
    )


async def submitted(
    client: httpx.AsyncClient,
    actors: Actors,
    *,
    fields: list[str] | None = None,
    vacancy: UUID | None = None,
) -> ApplicationView:
    await login(client, "stage8-c@example.com")
    response = await client.post(
        f"/api/v1/vacancies/{vacancy or actors.vacancy}/applications",
        json={
            "allowed_fields": fields or ["email"],
            "consent_version": "contacts-v1",
            "message": "Тестовый отклик",
        },
    )
    assert response.status_code == 200, response.text
    return ApplicationView.model_validate(response.json())


async def test_lifecycle_snapshot_selected_contacts_pdf_and_history(
    client: httpx.AsyncClient,
    actors: Actors,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    assert (
        await client.get(f"/api/v1/candidates/{actors.profile}/contacts")
    ).status_code == 404
    row = await submitted(client, actors)
    again = await submitted(client, actors, fields=["phone"])
    assert again.id == row.id and again.allowed_fields == ["email"]
    await login(client, "stage8-e@example.com")
    contacts = await client.get(f"/api/v1/candidates/{actors.profile}/contacts")
    assert contacts.json() == {"email": "private-stage8@example.com"}
    card = await client.get(f"/api/v1/employer/applications/{row.id}")
    assert card.json()["candidate_card"]["display_name"] == "Кандидат"
    assert card.json()["candidate_card"]["assessment"] is None
    assert "private-stage8" not in card.text and "secret-stage8" not in card.text
    pdf = pdf_text(await client.get(f"/api/v1/candidates/{actors.profile}/profile.pdf"))
    assert "private-stage8@example.com" in pdf and "+79990001122" not in pdf
    assert "Скрытое тестовое имя" not in pdf
    edited = await client.patch(
        f"/api/v1/employer/vacancies/{actors.vacancy}",
        json={
            "version": 1,
            "salary_from": 180000,
            "salary_to": 210000,
            "conditions": "Новые условия",
        },
    )
    assert edited.status_code == 200 and edited.json()["version"] == 2
    for target in ("view", "accept"):
        result = await client.post(f"/api/v1/applications/{row.id}/{target}")
        assert result.status_code == 200
    assert result.json()["vacancy_snapshot"]["conditions"] == "Гибкие часы"
    assert result.json()["vacancy_snapshot"]["salary_to"] == 190000
    assert (
        await client.post(f"/api/v1/applications/{row.id}/reject")
    ).status_code == 409
    for _ in range(2):
        assert (
            await client.post(f"/api/v1/employer/vacancies/{actors.vacancy}/close")
        ).status_code == 200
    assert (await client.get("/api/v1/vacancies")).json() == []
    assert (await client.get(f"/api/v1/vacancies/{actors.vacancy}")).json()[
        "status"
    ] == "closed"
    await login(client, "stage8-c@example.com")
    assert len((await client.get("/api/v1/candidate/applications")).json()) == 1
    for _ in range(2):
        assert (await client.post(f"/api/v1/applications/{row.id}/withdraw")).json()[
            "status"
        ] == "withdrawn"
    repeated = await client.post(
        f"/api/v1/vacancies/{actors.vacancy}/applications", json=CONSENT
    )
    assert (
        repeated.json()["id"] == str(row.id) and not repeated.json()["contact_access"]
    )
    await login(client, "stage8-e@example.com")
    assert (
        await client.get(f"/api/v1/candidates/{actors.profile}/contacts")
    ).status_code == 404
    assert "private-stage8" not in pdf_text(
        await client.get(f"/api/v1/candidates/{actors.profile}/profile.pdf")
    )
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Application)) == 1
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"salary_from": None},
        {"salary_to": None},
        {"salary_from": 0},
        {"salary_to": 100},
        {"currency": "USD"},
        {"salary_from": "170000"},
        {"title": " "},
        {"salary_from": True},
    ],
)
async def test_publication_requires_salary(
    client: httpx.AsyncClient, actors: Actors, changes: dict[str, object]
) -> None:
    assert (
        await client.post(
            "/api/v1/employer/vacancies", json={**vacancy_body(), **changes}
        )
    ).status_code == 422
    assert (await client.get("/api/v1/employer/vacancies")).json()[0]["id"] == str(
        actors.vacancy
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"salary_from": None},
        {"salary_to": 100},
        {"currency": None},
        {"description": " "},
    ],
)
async def test_edit_revalidates_whole_vacancy(
    client: httpx.AsyncClient, actors: Actors, changes: dict[str, object]
) -> None:
    assert (
        await client.patch(
            f"/api/v1/employer/vacancies/{actors.vacancy}",
            json={"version": 1, **changes},
        )
    ).status_code == 422
    assert (await client.get(f"/api/v1/employer/vacancies/{actors.vacancy}")).json()[
        "version"
    ] == 1


@pytest.mark.parametrize("target", ["viewed", "accepted", "rejected", "withdrawn"])
async def test_statuses_and_repeated_actions(
    actors: Actors, sessions: async_sessionmaker[AsyncSession], target: str
) -> None:
    async with sessions.begin() as db:
        row = await service.apply(
            db,
            actors.candidate,
            actors.vacancy,
            ApplicationInput.model_validate(CONSENT),
        )
    role, user = (
        ("candidate", actors.candidate)
        if target == "withdrawn"
        else ("employer", actors.employer)
    )
    for _ in range(2):
        async with sessions.begin() as db:
            changed = await service.action(db, user, role, row.id, target)
            assert changed.status == target
    assert changed.version == 2


async def test_roles_ownership_closed_and_linked_need(
    client: httpx.AsyncClient,
    actors: Actors,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    row = await submitted(client, actors)
    assert (
        await client.post("/api/v1/employer/vacancies", json=vacancy_body())
    ).status_code == 403
    for action in ("view", "accept", "reject"):
        assert (
            await client.post(f"/api/v1/applications/{row.id}/{action}")
        ).status_code == 403
    foreign_c = await register(client, "foreign-c@example.com")
    await verified(sessions, foreign_c)
    await login(client, "foreign-c@example.com")
    assert (
        await client.post(f"/api/v1/applications/{row.id}/withdraw")
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/candidate/applications/{row.id}")
    ).status_code == 404
    foreign = await register(client, "foreign-e@example.com", "employer")
    await verified(sessions, foreign)
    await login(client, "foreign-e@example.com")
    for path in (
        f"/employer/vacancies/{actors.vacancy}",
        f"/employer/vacancies/{actors.vacancy}/applications",
        f"/employer/applications/{row.id}",
        f"/candidates/{actors.profile}/contacts",
    ):
        assert (await client.get("/api/v1" + path)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/employer/vacancies/{actors.vacancy}",
            json={"version": 1, "title": "Чужая"},
        )
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/employer/vacancies/{actors.vacancy}/close")
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/applications/{row.id}/accept")
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/applications/{row.id}/withdraw")
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/vacancies/{actors.vacancy}/applications", json=CONSENT
        )
    ).status_code == 403
    foreign_need = (
        await client.post("/api/v1/employer/needs", json=need_body())
    ).json()
    await login(client, "stage8-e@example.com")
    assert (
        await client.post(
            "/api/v1/employer/vacancies",
            json={**vacancy_body(), "need_id": foreign_need["need_id"]},
        )
    ).status_code == 404
    await client.post(f"/api/v1/employer/vacancies/{actors.vacancy}/close")
    assert (
        await client.patch(
            f"/api/v1/employer/vacancies/{actors.vacancy}",
            json={"version": 2, "title": "Новая"},
        )
    ).status_code == 409
    await login(client, "foreign-c@example.com")
    assert (
        await client.post(
            f"/api/v1/vacancies/{actors.vacancy}/applications", json=CONSENT
        )
    ).status_code == 409


async def test_consent_and_privacy_are_current(
    client: httpx.AsyncClient,
    actors: Actors,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    row = await submitted(client, actors)
    await client.patch(
        "/api/v1/candidate/privacy",
        json={"visible_to_employers": False, "show_name": False},
    )
    await login(client, "stage8-e@example.com")
    history = await client.get(f"/api/v1/employer/applications/{row.id}")
    assert history.json()["candidate_card"] is None
    assert (
        await client.get(f"/api/v1/candidates/{actors.profile}/profile.pdf")
    ).status_code == 404
    await login(client, "stage8-c@example.com")
    await client.patch("/api/v1/candidate/profile", json={"consent_version": None})
    await login(client, "stage8-e@example.com")
    assert (
        await client.get(f"/api/v1/candidates/{actors.profile}/contacts")
    ).status_code == 404
    assert not (await client.get(f"/api/v1/employer/applications/{row.id}")).json()[
        "contact_access"
    ]
    vacancy = (
        await client.post("/api/v1/employer/vacancies", json=vacancy_body())
    ).json()
    await login(client, "stage8-c@example.com")
    assert (
        await client.post(
            f"/api/v1/vacancies/{vacancy['id']}/applications", json=CONSENT
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/vacancies/{vacancy['id']}/applications",
            json={"allowed_fields": [], "consent_version": "contacts-v1"},
        )
    ).status_code == 422
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Application)) == 1


async def test_two_applications_and_invitation_keep_independent_grants(
    client: httpx.AsyncClient,
    actors: Actors,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await submitted(client, actors)
    await login(client, "stage8-e@example.com")
    vacancy = UUID(
        (await client.post("/api/v1/employer/vacancies", json=vacancy_body())).json()[
            "id"
        ]
    )
    second = await submitted(client, actors, vacancy=vacancy, fields=["phone"])
    # Единственная техническая квалификация этого теста помечена существующим
    # helper как fixture; используется только в отдельной aggratech_test.
    await synthetic_credit(sessions, actors.candidate)
    await login(client, "stage8-e@example.com")
    need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    async with sessions.begin() as db:
        invite = await invitations.send(
            db,
            actors.employer,
            SendInput.model_validate(
                {
                    "candidate_id": str(actors.profile),
                    "need_id": need["need_id"],
                    "idempotency_key": "stage8-mixed",
                    "offer": {k: v for k, v in vacancy_body().items() if k != "title"},
                }
            ),
        )
    async with sessions.begin() as db:
        await invitations.action(
            db,
            actors.candidate,
            "candidate",
            invite.id,
            "accepted",
            Acceptance(allowed_fields=["messengers"], consent_version="contacts-v1"),
        )
    async with sessions.begin() as db:
        await service.action(db, actors.candidate, "candidate", first.id, "withdrawn")
        assert (await read_contacts(db, actors.profile, actors.employer)).model_dump(
            exclude_none=True
        ) == {"phone": "+79990001122", "messengers": {"telegram": "secret-stage8"}}
    async with sessions.begin() as db:
        await service.action(db, actors.candidate, "candidate", second.id, "withdrawn")
        assert (await read_contacts(db, actors.profile, actors.employer)).model_dump(
            exclude_none=True
        ) == {"messengers": {"telegram": "secret-stage8"}}
    async with sessions.begin() as db:
        await revoke(db, actors.profile, actors.company, actor_id=actors.candidate)
    async with sessions() as db:
        with pytest.raises(ApiError):
            await read_contacts(db, actors.profile, actors.employer)


async def test_atomic_rollback_and_database_immutability(
    actors: Actors, sessions: async_sessionmaker[AsyncSession]
) -> None:
    with pytest.raises(RuntimeError, match="forced_rollback"):
        async with sessions.begin() as db:
            await service.apply(
                db,
                actors.candidate,
                actors.vacancy,
                ApplicationInput.model_validate(CONSENT),
            )
            raise RuntimeError("forced_rollback")
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Application)) == 0
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == 0
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "application_submitted")
            )
            == 0
        )
    async with sessions.begin() as db:
        row = await service.apply(
            db,
            actors.candidate,
            actors.vacancy,
            ApplicationInput.model_validate(CONSENT),
        )
    for sql in (
        "UPDATE applications SET vacancy_snapshot = '{}'::jsonb WHERE id = :id",
        "UPDATE applications SET candidate_id = :id WHERE id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with sessions.begin() as db:
                await db.execute(text(sql), {"id": row.id})
    for sql in (
        "UPDATE contact_grants SET allowed_fields = '[\"phone\"]'::jsonb "
        "WHERE application_id = :id",
        "UPDATE contact_grants SET invitation_id = :id WHERE application_id = :id",
    ):
        with pytest.raises(DBAPIError):
            async with sessions.begin() as db:
                await db.execute(text(sql), {"id": row.id})


async def test_postgresql_double_submit_edit_and_close_races(
    actors: Actors, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async def apply() -> ApplicationView:
        async with sessions.begin() as db:
            return await service.apply(
                db,
                actors.candidate,
                actors.vacancy,
                ApplicationInput.model_validate(CONSENT),
            )

    a, b = await asyncio.gather(apply(), apply())
    assert a.id == b.id

    async def edit(title: str) -> str:
        try:
            async with sessions.begin() as db:
                await service.edit(
                    db,
                    actors.employer,
                    actors.vacancy,
                    VacancyPatch(version=1, title=title),
                )
            return "edited"
        except ApiError as error:
            return error.code

    assert sorted(await asyncio.gather(edit("Первое"), edit("Второе"))) == [
        "edited",
        "vacancy_changed",
    ]
    async with sessions.begin() as db:
        assert await db.scalar(select(func.count()).select_from(Application)) == 1
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == 1
        row = await db.get(Vacancy, actors.vacancy)
        assert row and row.version == 2
        other = await service.create(
            db, actors.employer, VacancyInput.model_validate(vacancy_body())
        )

    async def close() -> None:
        async with sessions.begin() as db:
            await service.close(db, actors.employer, other.id)

    async def apply_other() -> str:
        try:
            async with sessions.begin() as db:
                await service.apply(
                    db,
                    actors.candidate,
                    other.id,
                    ApplicationInput.model_validate(CONSENT),
                )
            return "applied"
        except ApiError as error:
            return error.code

    closed, outcome = await asyncio.gather(close(), apply_other())
    assert closed is None and outcome in ("applied", "vacancy_closed")
    async with sessions() as db:
        row = await db.get(Vacancy, other.id)
        assert row and row.status == "closed"


async def test_postgresql_withdraw_accept_and_global_revocation_races(
    actors: Actors, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions.begin() as db:
        row = await service.apply(
            db,
            actors.candidate,
            actors.vacancy,
            ApplicationInput.model_validate(CONSENT),
        )

    async def change(user: UUID, role: str, target: str) -> str:
        try:
            async with sessions.begin() as db:
                result = await service.action(db, user, role, row.id, target)
            return result.status
        except ApiError as error:
            return error.code

    await asyncio.gather(
        change(actors.employer, "employer", "accepted"),
        change(actors.candidate, "candidate", "withdrawn"),
    )
    async with sessions() as db:
        actual = await db.get(Application, row.id)
        grant = await db.scalar(
            select(ContactGrant).where(ContactGrant.application_id == row.id)
        )
        assert actual and actual.status == "withdrawn" and grant and grant.revoked_at
    async with sessions.begin() as db:
        other = await service.create(
            db, actors.employer, VacancyInput.model_validate(vacancy_body())
        )

    async def apply() -> None:
        try:
            async with sessions.begin() as db:
                await service.apply(
                    db,
                    actors.candidate,
                    other.id,
                    ApplicationInput.model_validate(CONSENT),
                )
        except ApiError as error:
            assert error.code == "consent_required"

    async def revoke_all() -> None:
        async with sessions.begin() as db:
            profile = await db.get(
                CandidateProfile, actors.profile, with_for_update=True
            )
            assert profile
            profile.consented_at = None
            await revoke(db, actors.profile, actor_id=actors.candidate)

    await asyncio.gather(apply(), revoke_all())
    async with sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(ContactGrant)
                .where(ContactGrant.revoked_at.is_(None))
            )
            == 0
        )


async def test_verified_email_and_application_payload(
    client: httpx.AsyncClient, actors: Actors
) -> None:
    await register(client, "unverified-stage8@example.com")
    await login(client, "unverified-stage8@example.com")
    assert (
        await client.post(
            f"/api/v1/vacancies/{actors.vacancy}/applications", json=CONSENT
        )
    ).status_code == 403
    await login(client, "stage8-c@example.com")
    for data in (
        {"allowed_fields": [], "consent_version": "contacts-v1"},
        {"allowed_fields": ["email", "email"], "consent_version": "contacts-v1"},
        {**CONSENT, "salary_to": 900000},
        {"allowed_fields": ["email"], "consent_version": "obsolete"},
    ):
        assert (
            await client.post(
                f"/api/v1/vacancies/{actors.vacancy}/applications", json=data
            )
        ).status_code == 422


async def test_postgresql_edit_and_submit_snapshot_race(
    actors: Actors, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async def edit() -> None:
        async with sessions.begin() as db:
            await service.edit(
                db,
                actors.employer,
                actors.vacancy,
                VacancyPatch.model_validate(
                    {
                        "version": 1,
                        "conditions": "Новые",
                        "salary_from": 180000,
                        "salary_to": 210000,
                    }
                ),
            )

    async def apply() -> ApplicationView:
        async with sessions.begin() as db:
            return await service.apply(
                db,
                actors.candidate,
                actors.vacancy,
                ApplicationInput.model_validate(CONSENT),
            )

    _, row = await asyncio.gather(edit(), apply())
    assert (
        row.vacancy_snapshot.version,
        int(row.vacancy_snapshot.salary_to),
        row.vacancy_snapshot.conditions,
    ) in {(1, 190000, "Гибкие часы"), (2, 210000, "Новые")}


async def test_database_source_pair_constraint(
    actors: Actors, sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with sessions.begin() as db:
        row = await service.apply(
            db,
            actors.candidate,
            actors.vacancy,
            ApplicationInput.model_validate(CONSENT),
        )
        await service.action(db, actors.candidate, "candidate", row.id, "withdrawn")
    with pytest.raises(DBAPIError):
        async with sessions.begin() as db:
            # Отозванный источник не может создать новое согласие даже в обход API.
            await db.execute(
                text("""INSERT INTO
contact_grants(id,candidate_id,employer_id,application_id,
allowed_fields,consent_version,granted_at)
VALUES(:id,:candidate,:employer,:source,'["email"]'::jsonb,'contacts-v1',now())"""),
                {
                    "id": uuid4(),
                    "candidate": actors.profile,
                    "employer": actors.company,
                    "source": row.id,
                },
            )
