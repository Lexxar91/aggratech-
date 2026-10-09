"""Настоящий PostgreSQL, синтетические квалификации только в aggratech_test."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import UUID, uuid4

import httpx
import pytest
from pypdf import PdfReader
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.candidate_profile.access import ContactGrant, revoke
from app.candidate_profile.models import CandidateProfile
from app.core.errors import ApiError
from app.invitations import service
from app.invitations.models import Invitation
from app.invitations.schemas import Acceptance, InvitationView, SendInput
from app.notifications.models import AuditEvent, BackgroundJob
from app.notifications.queue import utc_now
from tests.test_auth_profiles import auth_app as auth_app
from tests.test_auth_profiles import client as client
from tests.test_auth_profiles import login, register
from tests.test_matching_api import need_body, synthetic_credit, verified

pytestmark = pytest.mark.integration
CONSENT = {"allowed_fields": ["email"], "consent_version": "contacts-v1"}


@pytest.fixture
async def actors(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> dict[str, object]:
    candidate = await register(client, "c-fixture@example.com")
    await verified(sessions, candidate)
    cid = await synthetic_credit(sessions, candidate)
    await login(client, "c-fixture@example.com")
    await client.patch(
        "/api/v1/candidate/contacts",
        json={
            "email": "private-contact@example.com",
            "phone": "+79995550123",
            "messengers": {"telegram": "private-handle"},
        },
    )
    employer = await register(client, "e-fixture@example.com", "employer")
    await verified(sessions, employer)
    await login(client, "e-fixture@example.com")
    need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    return {
        "candidate_user": candidate,
        "employer_user": employer,
        "candidate_id": cid,
        "need": need,
        "body": {
            "candidate_id": str(cid),
            "need_id": need["need_id"],
            "idempotency_key": "first",
            "offer": {
                "description": "Тестовое предложение, не реальная вакансия",
                "salary_from": 170000,
                "salary_to": 190000,
                "work_formats": ["remote"],
                "conditions": "Гибкие часы",
                "representative_contact": "representative@example.com",
            },
        },
    }


def body_of(actors: dict[str, object]) -> SendInput:
    return SendInput.model_validate(actors["body"])


async def sent(
    client: httpx.AsyncClient, actors: dict[str, object]
) -> dict[str, object]:
    response = await client.post("/api/v1/employer/invitations", json=actors["body"])
    assert response.status_code == 200, response.text
    return InvitationView.model_validate(response.json()).model_dump(mode="json")


def pdf_text(response: httpx.Response) -> str:
    assert response.status_code == 200, (
        response.text[:100] if response.status_code != 200 else ""
    )
    return "".join(
        page.extract_text() for page in PdfReader(BytesIO(response.content)).pages
    )


async def test_offer_idempotency_snapshot_privacy_and_contact_selection(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    invitation = await sent(client, actors)
    identifier = invitation["id"]
    assert invitation["status"] == "sent" and not invitation["contact_access"]
    assert datetime.fromisoformat(
        str(invitation["expires_at"])
    ) - datetime.fromisoformat(str(invitation["sent_at"])) == timedelta(days=7)
    assert (await sent(client, actors))["id"] == identifier
    different = body_of(actors).model_dump(mode="json")
    different["offer"]["description"] = "Другое предложение"
    assert (
        await client.post("/api/v1/employer/invitations", json=different)
    ).status_code == 409
    different["idempotency_key"] = "second"
    assert (
        await client.post("/api/v1/employer/invitations", json=different)
    ).status_code == 409
    need = actors["need"]
    assert isinstance(need, dict)
    updated = {k: v for k, v in need.items() if k not in ("need_id", "employer_id")}
    updated["task_description"] = "Новые задачи"
    updated["salary_from"] = 210000
    updated["salary_to"] = 230000
    assert (
        await client.patch(f"/api/v1/employer/needs/{need['need_id']}", json=updated)
    ).status_code == 200
    assert (await client.get(f"/api/v1/employer/invitations/{identifier}")).json()[
        "offer_snapshot"
    ] == invitation["offer_snapshot"]
    cid = actors["candidate_id"]
    for response in [
        await client.get(f"/api/v1/candidates/{cid}"),
        await client.get(f"/api/v1/employer/invitations/{identifier}"),
    ]:
        assert "private-contact" not in response.text and "7999555" not in response.text
    assert (await client.get(f"/api/v1/candidates/{cid}/contacts")).status_code == 404
    assert "private-contact" not in pdf_text(
        await client.get(f"/api/v1/candidates/{cid}/profile.pdf")
    )
    await login(client, "c-fixture@example.com")
    assert (await client.get("/api/v1/candidate/invitations")).json()[0][
        "status"
    ] == "sent"
    assert (await client.get(f"/api/v1/candidate/invitations/{identifier}")).json()[
        "status"
    ] == "viewed"
    response = await client.post(
        f"/api/v1/candidate/invitations/{identifier}/accept", json=CONSENT
    )
    assert response.json()["status"] == "accepted" and response.json()["contact_access"]
    assert (
        await client.post(
            f"/api/v1/candidate/invitations/{identifier}/accept", json=CONSENT
        )
    ).json()["status"] == "accepted"
    await login(client, "e-fixture@example.com")
    assert (await client.get(f"/api/v1/candidates/{cid}/contacts")).json() == {
        "email": "private-contact@example.com"
    }
    document = pdf_text(await client.get(f"/api/v1/candidates/{cid}/profile.pdf"))
    assert (
        "private-contact@example.com" in document
        and "7999555" not in document
        and "private-handle" not in document
    )
    assert (
        await client.post(
            f"/api/v1/employer/invitations/{identifier}/withdraw", json={}
        )
    ).json()["status"] == "accepted"
    async with sessions.begin() as db:
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == 1
        jobs = list(
            await db.scalars(
                select(BackgroundJob).where(BackgroundJob.kind == "invitation_email")
            )
        )
        assert len(jobs) == 2
        assert all(
            "private-contact" not in str(job.payload)
            and "7999555" not in str(job.payload)
            for job in jobs
        )
    other = await register(client, "other@example.com", "employer")
    await verified(sessions, other)
    await login(client, "other@example.com")
    assert (await client.get(f"/api/v1/candidates/{cid}/contacts")).status_code == 404
    assert (
        await client.get(f"/api/v1/employer/invitations/{identifier}")
    ).status_code == 404
    assert "private-contact" not in pdf_text(
        await client.get(f"/api/v1/candidates/{cid}/profile.pdf")
    )
    await login(client, "c-fixture@example.com")
    for _ in range(2):
        assert (
            await client.delete(
                f"/api/v1/candidate/contact-grants/{invitation['employer_id']}"
            )
        ).status_code == 204
    await login(client, "e-fixture@example.com")
    assert (await client.get(f"/api/v1/candidates/{cid}/contacts")).status_code == 404
    assert "private-contact" not in pdf_text(
        await client.get(f"/api/v1/candidates/{cid}/profile.pdf")
    )
    assert (await client.get(f"/api/v1/employer/invitations/{identifier}")).json()[
        "status"
    ] == "accepted"


@pytest.mark.parametrize(
    "source", ["sent", "viewed", "accepted", "rejected", "expired", "withdrawn"]
)
@pytest.mark.parametrize("target", ["viewed", "accepted", "rejected", "withdrawn"])
async def test_transition_table(
    sessions: async_sessionmaker[AsyncSession],
    actors: dict[str, object],
    source: str,
    target: str,
) -> None:
    employer = UUID(str(actors["employer_user"]))
    candidate = UUID(str(actors["candidate_user"]))
    async with sessions.begin() as db:
        original = await service.send(db, employer, body_of(actors))
        # Построение каждого исходного состояния через законные переходы.
        if source != "sent":
            clock = original.expires_at if source == "expired" else None
            role = "employer" if source == "withdrawn" else "candidate"
            await service.action(
                db,
                employer if role == "employer" else candidate,
                role,
                original.id,
                None if source == "expired" else source,
                Acceptance.model_validate(CONSENT) if source == "accepted" else None,
                now=clock,
            )
    async with sessions.begin() as db:
        role = "employer" if target == "withdrawn" else "candidate"
        result = await service.action(
            db,
            employer if role == "employer" else candidate,
            role,
            original.id,
            target,
            Acceptance.model_validate(CONSENT) if target == "accepted" else None,
        )
        expected = (
            target if source in ("sent", "viewed") and target != "viewed" else source
        )
        if source == "sent" and target == "viewed":
            expected = "viewed"
        assert result.status == expected
        count = await db.scalar(select(func.count()).select_from(ContactGrant))
        assert count == int(expected == "accepted")


@pytest.mark.parametrize(
    "offset,expected", [(-1, "accepted"), (0, "expired"), (1, "expired")]
)
async def test_exact_expiry_boundary(
    sessions: async_sessionmaker[AsyncSession],
    actors: dict[str, object],
    offset: int,
    expected: str,
) -> None:
    async with sessions.begin() as db:
        invitation = await service.send(
            db, UUID(str(actors["employer_user"])), body_of(actors)
        )
    async with sessions.begin() as db:
        result = await service.action(
            db,
            UUID(str(actors["candidate_user"])),
            "candidate",
            invitation.id,
            "accepted",
            Acceptance.model_validate(CONSENT),
            now=invitation.expires_at + timedelta(microseconds=offset),
        )
        assert result.status == expected
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == int(
            expected == "accepted"
        )


@pytest.mark.parametrize("race", ["withdraw", "expire", "accept", "revoke"])
async def test_postgres_races(
    sessions: async_sessionmaker[AsyncSession], actors: dict[str, object], race: str
) -> None:
    employer = UUID(str(actors["employer_user"]))
    candidate = UUID(str(actors["candidate_user"]))
    async with sessions.begin() as db:
        invitation = await service.send(db, employer, body_of(actors))
    barrier = asyncio.Barrier(2)
    completed: list[str] = []

    async def first() -> None:
        await barrier.wait()
        async with sessions.begin() as db:
            await service.action(
                db,
                candidate,
                "candidate",
                invitation.id,
                "accepted",
                Acceptance.model_validate(CONSENT),
                now=invitation.expires_at - timedelta(microseconds=1)
                if race == "expire"
                else None,
            )
        completed.append("accept")

    async def second() -> None:
        await barrier.wait()
        async with sessions.begin() as db:
            if race == "withdraw":
                await service.action(
                    db, employer, "employer", invitation.id, "withdrawn"
                )
            elif race == "expire":
                await service.expire_due(db, now=invitation.expires_at)
            elif race == "accept":
                await service.action(
                    db,
                    candidate,
                    "candidate",
                    invitation.id,
                    "accepted",
                    Acceptance.model_validate(CONSENT),
                )
            else:
                profile = await db.scalar(
                    select(CandidateProfile)
                    .where(CandidateProfile.id == invitation.candidate_id)
                    .with_for_update()
                )
                assert profile
                await revoke(db, profile.id, invitation.employer_id)
        completed.append(race)

    async with asyncio.timeout(15):
        await asyncio.gather(first(), second())
    async with sessions.begin() as db:
        row = await db.get(Invitation, invitation.id)
        assert row
        assert row.status in {
            "accepted",
            {
                "withdraw": "withdrawn",
                "expire": "expired",
                "accept": "accepted",
                "revoke": "accepted",
            }[race],
        }
        grants = list(await db.scalars(select(ContactGrant)))
        assert len(grants) == int(row.status == "accepted")
        if race == "revoke":
            assert bool(grants[0].revoked_at) == (completed[0] == "accept")


@pytest.mark.parametrize(
    "field,value",
    [
        ("salary_from", None),
        ("salary_to", None),
        ("salary_from", 0),
        ("salary_to", -1),
        ("salary_from", True),
        ("salary_from", 200000),
        ("work_formats", ["office"]),
    ],
)
async def test_required_salary_and_conditions(
    client: httpx.AsyncClient, actors: dict[str, object], field: str, value: object
) -> None:
    body = body_of(actors).model_dump(mode="json")
    body["offer"][field] = value
    assert (
        await client.post("/api/v1/employer/invitations", json=body)
    ).status_code == 422


@pytest.mark.parametrize(
    "reason", ["salary", "hidden", "blocked", "demo", "not_admitted", "unknown"]
)
async def test_send_rechecks_current_conditions_and_gate(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
    reason: str,
) -> None:
    from app.assessment.models import AssessmentCycle
    from app.candidate_profile.models import CandidateEmployerBlock
    from app.employer.models import EmployerProfile

    async with sessions.begin() as db:
        profile = await db.get(CandidateProfile, UUID(str(actors["candidate_id"])))
        assert profile
        if reason == "salary":
            profile.salary_min = profile.salary_max = Decimal(300000)
        elif reason == "hidden":
            profile.privacy = {"visible_to_employers": False, "show_name": False}
        elif reason == "blocked":
            employer = await db.scalar(
                select(EmployerProfile).where(
                    EmployerProfile.user_id == actors["employer_user"]
                )
            )
            assert employer
            db.add(
                CandidateEmployerBlock(
                    candidate_id=profile.id,
                    employer_id=employer.id,
                    created_at=utc_now(),
                )
            )
        elif reason in ("demo", "not_admitted"):
            cycle = await db.scalar(
                select(AssessmentCycle).where(
                    AssessmentCycle.user_id == actors["candidate_user"]
                )
            )
            assert cycle
            if reason == "demo":
                cycle.mode = "demo"
            else:
                cycle.admission = {**cycle.admission, "review_passed": False}
        else:
            profile.salary_min = profile.salary_max = None
            profile.work_preferences = {"formats": [], "location": None}
    response = await client.post("/api/v1/employer/invitations", json=actors["body"])
    if reason == "unknown":
        assert response.status_code == 200, response.text
        assert (
            response.json()["offer_snapshot"]["compatibility_group"]
            == "needs_clarification"
        )
    else:
        assert response.status_code == 409, response.text


async def test_block_consent_and_hidden_search_after_send(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    invitation = await sent(client, actors)
    await login(client, "c-fixture@example.com")
    assert (
        await client.patch(
            "/api/v1/candidate/privacy",
            json={"visible_to_employers": False, "show_name": False},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/candidate/invitations/{invitation['id']}/accept", json=CONSENT
        )
    ).json()["status"] == "accepted"
    await login(client, "e-fixture@example.com")
    assert (
        await client.get(f"/api/v1/candidates/{actors['candidate_id']}")
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/candidates/{actors['candidate_id']}/contacts")
    ).status_code == 200
    await login(client, "c-fixture@example.com")
    assert (
        await client.put(f"/api/v1/candidate/blocks/{invitation['employer_id']}")
    ).status_code == 204
    assert (
        await client.delete(f"/api/v1/candidate/blocks/{invitation['employer_id']}")
    ).status_code == 204
    await login(client, "e-fixture@example.com")
    assert (
        await client.get(f"/api/v1/candidates/{actors['candidate_id']}/contacts")
    ).status_code == 404
    async with sessions.begin() as db:
        grant = await db.scalar(select(ContactGrant))
        assert grant and grant.revoked_at


async def test_consent_revocation_closes_all_sources(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    invitation = await sent(client, actors)
    await login(client, "c-fixture@example.com")
    await client.post(
        f"/api/v1/candidate/invitations/{invitation['id']}/accept", json=CONSENT
    )
    profile = (await client.get("/api/v1/candidate/profile")).json()
    body = {
        key: profile[key]
        for key in [
            "display_name",
            "summary",
            "experience",
            "salary_min",
            "salary_max",
            "salary_basis",
            "available_from",
            "work_preferences",
            "technology_ids",
        ]
    }
    assert (
        await client.patch(
            "/api/v1/candidate/profile", json={**body, "consent_version": None}
        )
    ).status_code == 200
    assert (
        await client.patch(
            "/api/v1/candidate/profile", json={**body, "consent_version": "profile-v1"}
        )
    ).status_code == 200
    await login(client, "e-fixture@example.com")
    assert (
        await client.get(f"/api/v1/candidates/{actors['candidate_id']}/contacts")
    ).status_code == 404
    async with sessions.begin() as db:
        grant = await db.scalar(select(ContactGrant))
        assert grant and grant.revoked_at


async def test_database_guards_and_atomic_rollback(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    invitation = await sent(client, actors)
    for sql in [
        "UPDATE invitations SET salary_from=1 WHERE id=:id",
        "UPDATE invitations SET salary_to=NULL WHERE id=:id",
        "INSERT INTO contact_grants(id,candidate_id,employer_id,invitation_id,"
        "allowed_fields,consent_version,granted_at) SELECT :grant,candidate_id,"
        "employer_id,id,'[\"email\"]','contacts-v1',now() "
        "FROM invitations WHERE id=:id",
    ]:
        with pytest.raises(DBAPIError):
            async with sessions.begin() as db:
                await db.execute(
                    text(sql), {"id": UUID(str(invitation["id"])), "grant": uuid4()}
                )
    with pytest.raises(RuntimeError):
        async with sessions.begin() as db:
            await service.action(
                db,
                UUID(str(actors["candidate_user"])),
                "candidate",
                UUID(str(invitation["id"])),
                "accepted",
                Acceptance.model_validate(CONSENT),
            )
            raise RuntimeError("rollback_after_acceptance")
    async with sessions.begin() as db:
        row = await db.get(Invitation, UUID(str(invitation["id"])))
        assert row and row.status == "sent"
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == 0
        with pytest.raises(ApiError):
            await service.action(
                db,
                UUID(str(actors["employer_user"])),
                "employer",
                row.id,
                "accepted",
                Acceptance.model_validate(CONSENT),
            )


async def test_concurrent_send_and_expired_resend(
    sessions: async_sessionmaker[AsyncSession], actors: dict[str, object]
) -> None:
    employer = UUID(str(actors["employer_user"]))
    barrier = asyncio.Barrier(2)

    async def operation() -> UUID:
        await barrier.wait()
        async with sessions.begin() as db:
            return (await service.send(db, employer, body_of(actors))).id

    first, second = await asyncio.gather(operation(), operation())
    assert first == second
    async with sessions.begin() as db:
        assert await db.scalar(select(func.count()).select_from(Invitation)) == 1
        old = await db.get(Invitation, first)
        assert old
        deadline = old.expires_at
    async with sessions.begin() as db:
        new = await service.send(
            db,
            employer,
            body_of(actors).model_copy(update={"idempotency_key": "after-expiry"}),
            now=deadline,
        )
        assert new.id != first and new.status == "sent"
        old = await db.get(Invitation, first)
        assert old and old.status == "expired"


async def test_block_withdraws_unfinished_and_foreign_candidate(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    invitation = await sent(client, actors)
    await register(client, "foreign-candidate@example.com")
    await login(client, "foreign-candidate@example.com")
    assert (
        await client.get(f"/api/v1/candidate/invitations/{invitation['id']}")
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/candidate/invitations/{invitation['id']}/accept", json=CONSENT
        )
    ).status_code == 404
    await login(client, "c-fixture@example.com")
    await client.put(f"/api/v1/candidate/blocks/{invitation['employer_id']}")
    result = await client.post(
        f"/api/v1/candidate/invitations/{invitation['id']}/accept", json=CONSENT
    )
    assert (
        result.json()["status"] == "withdrawn" and not result.json()["contact_access"]
    )
    async with sessions.begin() as db:
        assert await db.scalar(select(func.count()).select_from(ContactGrant)) == 0


async def test_revoke_all_sources_preserves_invitation_history(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = await sent(client, actors)
    second_need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    body = body_of(actors).model_dump(mode="json")
    body.update(need_id=second_need["need_id"], idempotency_key="other-need")
    second = (await client.post("/api/v1/employer/invitations", json=body)).json()
    await login(client, "c-fixture@example.com")
    for invitation in (first, second):
        assert (
            await client.post(
                f"/api/v1/candidate/invitations/{invitation['id']}/accept", json=CONSENT
            )
        ).json()["status"] == "accepted"
    await client.delete(f"/api/v1/candidate/contact-grants/{first['employer_id']}")
    async with sessions.begin() as db:
        grants = list(await db.scalars(select(ContactGrant)))
        assert len(grants) == 2 and all(grant.revoked_at for grant in grants)
        events = list(
            await db.scalars(
                select(AuditEvent).where(AuditEvent.action == "contacts_revoked")
            )
        )
        assert len(events) == 2
        assert all(event.actor_id == actors["candidate_user"] for event in events)
        assert set(await db.scalars(select(Invitation.status))) == {"accepted"}


@pytest.mark.parametrize("accepted", [False, True])
async def test_disabled_company_closes_all_current_access(
    client: httpx.AsyncClient,
    actors: dict[str, object],
    sessions: async_sessionmaker[AsyncSession],
    accepted: bool,
) -> None:
    from app.employer.models import EmployerProfile

    invitation = await sent(client, actors)
    if accepted:
        await login(client, "c-fixture@example.com")
        await client.post(
            f"/api/v1/candidate/invitations/{invitation['id']}/accept", json=CONSENT
        )
    async with sessions.begin() as db:
        employer = await db.get(EmployerProfile, UUID(str(invitation["employer_id"])))
        assert employer
        employer.status = "blocked"
    await login(client, "e-fixture@example.com")
    cid = actors["candidate_id"]
    for suffix in ("", "/contacts", "/profile.pdf"):
        assert (
            await client.get(f"/api/v1/candidates/{cid}{suffix}")
        ).status_code == 404
    await login(client, "c-fixture@example.com")
    result = (
        await client.get(f"/api/v1/candidate/invitations/{invitation['id']}")
    ).json()
    assert result["status"] == ("accepted" if accepted else "withdrawn")
    assert not result["contact_access"]


async def test_viewed_deadline_uses_same_expiry_transition(
    sessions: async_sessionmaker[AsyncSession], actors: dict[str, object]
) -> None:
    candidate = UUID(str(actors["candidate_user"]))
    async with sessions.begin() as db:
        invitation = await service.send(
            db, UUID(str(actors["employer_user"])), body_of(actors)
        )
        await service.action(db, candidate, "candidate", invitation.id, "viewed")
    async with sessions.begin() as db:
        await service.expire_due(db, now=invitation.expires_at)
        result = await service.action(
            db,
            candidate,
            "candidate",
            invitation.id,
            "accepted",
            Acceptance.model_validate(CONSENT),
            now=invitation.expires_at,
        )
        assert result.status == "expired" and not result.contact_access
