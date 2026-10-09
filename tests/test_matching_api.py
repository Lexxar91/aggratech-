"""Изолированные PostgreSQL fixture-записи; не реальные квалификации."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment.models import AssessmentCycle, AssessmentPublication
from app.auth.models import User
from app.candidate_profile.models import CandidateEmployerBlock, CandidateProfile
from app.employer.models import EmployerProfile
from app.fsp.models import FspLink
from app.matching.fixtures import candidates_from_fixture, example_dataset, model_input
from app.matching.models import MatchingSnapshot, NeedVersion
from app.matching.schemas import Dataset
from app.matching.service import compute
from app.tools.matching_check import main
from tests.test_auth_profiles import auth_app as auth_app
from tests.test_auth_profiles import client as client
from tests.test_auth_profiles import login, register

pytestmark = pytest.mark.integration


async def verified(sessions: async_sessionmaker[AsyncSession], user_id: UUID) -> None:
    async with sessions.begin() as db:
        user = await db.get(User, user_id)
        assert user
        user.email_verified_at = datetime.now(UTC)


def need_body() -> dict[str, object]:
    data = model_input(Dataset, example_dataset()).needs[0].model_dump(mode="json")
    del data["need_id"]
    del data["employer_id"]
    return data


async def synthetic_credit(
    sessions: async_sessionmaker[AsyncSession],
    user_id: UUID,
    *,
    mode: str = "credit",
    admitted: bool = True,
) -> UUID:
    # Записи создаются только в aggratech_test; HTTP не предоставляет этот обход.
    now = datetime.now(UTC)
    identifier = uuid4()
    async with sessions.begin() as db:
        profile = await db.scalar(
            select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        )
        assert profile
        profile.display_name = "Тестовая Анна"
        profile.consented_at = now
        profile.consent_version = "profile-v1"
        profile.privacy = {"visible_to_employers": True, "show_name": True}
        profile.salary_min = Decimal(160000)
        profile.salary_max = Decimal(200000)
        profile.work_preferences = {"formats": ["remote"], "location": None}
        profile.preferences_confirmed_at = now
        profile.available_from = now.date()
        db.add(
            AssessmentCycle(
                id=identifier,
                user_id=user_id,
                mode=mode,
                grade="middle",
                form="X",
                state="completed",
                outcome="confirmed",
                review_state="clear",
                created_at=now - timedelta(days=1),
                a_deadline=now,
                completed_at=now,
                seed=1,
                methodology="backend-assessment-v1",
                evaluator_hash="test-only",
                bank_hash="test-only",
                admission={
                    "review_passed": admitted,
                    "origin": "live_credit" if mode == "credit" else "live_demo",
                    "fixture_notice": "isolated test, not an actual review",
                },
                materials={},
                result={
                    "total": 90,
                    "skills": [
                        {"skill": s, "score": 90, "status": "met", "families": 3}
                        for s in [
                            "language_algorithms",
                            "sql_data",
                            "http_api",
                            "debug_reliability",
                            "security_validation",
                        ]
                    ],
                },
            )
        )
        await db.flush()
        db.add(
            AssessmentPublication(
                user_id=user_id,
                mode=mode,
                cycle_id=identifier,
                grade="middle",
                published_at=now,
            )
        )
        return profile.id


async def test_needs_versions_templates_and_ownership(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employer = await register(client, "employer@example.com", "employer")
    await login(client, "employer@example.com")
    assert (await client.get("/api/v1/employer/needs")).status_code == 403
    await verified(sessions, employer)
    response = await client.get("/api/v1/employer/need-templates")
    assert response.status_code == 200
    templates = response.json()
    assert len(templates) == 3 and all(
        "trace" not in t and "salary_from" not in t for t in templates
    )
    body = need_body()
    body.update(
        template_code=templates[0]["code"],
        template_version=templates[0]["version"],
        task_description="Отредактировано вручную",
    )
    response = await client.post("/api/v1/employer/needs", json=body)
    assert response.status_code == 200, response.text
    need = response.json()
    nid = need["need_id"]
    assert (
        need["task_description"] == "Отредактировано вручную" and need["version"] == 1
    )
    snapshot = await client.post(
        f"/api/v1/employer/needs/{nid}/recommendations", json={}
    )
    assert snapshot.status_code == 200, snapshot.text
    shot = snapshot.json()
    assert shot["entries"] == []
    body["title"] = "Вторая версия"
    response = await client.patch(f"/api/v1/employer/needs/{nid}", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert (
        await client.patch(f"/api/v1/employer/needs/{nid}", json=body)
    ).status_code == 409
    old = (await client.get(f"/api/v1/employer/recommendations/{shot['id']}")).json()
    assert old["need_version"] == 1
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(NeedVersion)) == 2
    other = await register(client, "other@example.com", "employer")
    await verified(sessions, other)
    await login(client, "other@example.com")
    assert (await client.get(f"/api/v1/employer/needs/{nid}")).status_code == 404
    assert (
        await client.get(f"/api/v1/employer/recommendations/{shot['id']}")
    ).status_code == 404
    candidate = await register(client)
    await verified(sessions, candidate)
    await login(client)
    assert (await client.get("/api/v1/employer/needs")).status_code == 403


@pytest.mark.parametrize(("mode", "admitted"), [("demo", True), ("credit", False)])
async def test_unadmitted_and_demo_never_match(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    mode: str,
    admitted: bool,
) -> None:
    candidate = await register(client)
    await synthetic_credit(sessions, candidate, mode=mode, admitted=admitted)
    employer = await register(client, "employer@example.com", "employer")
    await verified(sessions, employer)
    await login(client, "employer@example.com")
    need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    result = await client.post(
        f"/api/v1/employer/needs/{need['need_id']}/recommendations", json={}
    )
    assert result.status_code == 200, result.text
    assert result.json()["entries"] == []


async def test_snapshot_marks_privacy_and_category_recheck(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    candidate = await register(client)
    cid = await synthetic_credit(sessions, candidate)
    employer = await register(client, "employer@example.com", "employer")
    await verified(sessions, employer)
    await login(client, "employer@example.com")
    need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    nid = need["need_id"]
    result = await client.post(f"/api/v1/employer/needs/{nid}/recommendations", json={})
    assert result.status_code == 200, result.text
    snapshot = result.json()
    sid = snapshot["id"]
    row = snapshot["entries"][0]
    assert (
        row["available"]
        and row["card"]["display_name"] == "Тестовая Анна"
        and row["recommendation"]["components"]["F"] == 0
    )
    assert not any(
        x in result.text for x in ["candidate@example.com", "phone", "messengers"]
    )
    path = f"/api/v1/employer/needs/{nid}/candidates/{cid}"
    assert (await client.put(path, json={"saved": True})).status_code == 200
    assert (await client.get(f"/api/v1/employer/recommendations/{sid}")).json()[
        "entries"
    ][0]["saved"]
    assert (
        await client.put(
            path, json={"saved": True, "hidden": True, "reason": "Для другой команды"}
        )
    ).status_code == 200
    unavailable = (await client.get(f"/api/v1/employer/recommendations/{sid}")).json()[
        "entries"
    ][0]
    assert (
        not unavailable["available"]
        and unavailable["card"] is None
        and unavailable["recommendation"] is None
    )
    other_need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    other_snapshot = (
        await client.post(
            f"/api/v1/employer/needs/{other_need['need_id']}/recommendations", json={}
        )
    ).json()
    assert (
        other_snapshot["entries"][0]["available"]
        and not other_snapshot["entries"][0]["saved"]
        and not other_snapshot["entries"][0]["hidden"]
    )
    assert (
        await client.put(path, json={"saved": True, "hidden": False})
    ).status_code == 200
    async with sessions.begin() as db:
        profile = await db.get(CandidateProfile, cid)
        assert profile
        profile.privacy = {"visible_to_employers": True, "show_name": False}
    result = await client.get(f"/api/v1/employer/recommendations/{sid}")
    assert (
        result.json()["entries"][0]["card"]["display_name"] == "Кандидат"
        and "Тестовая Анна" not in result.text
    )
    async with sessions.begin() as db:
        company = await db.scalar(
            select(EmployerProfile).where(EmployerProfile.user_id == employer)
        )
        assert company
        db.add(
            CandidateEmployerBlock(
                candidate_id=cid, employer_id=company.id, created_at=datetime.now(UTC)
            )
        )
    result = await client.get(f"/api/v1/employer/recommendations/{sid}")
    assert (
        not result.json()["entries"][0]["available"] and "Тестовая" not in result.text
    )
    async with sessions.begin() as db:
        await db.execute(text("DELETE FROM candidate_employer_blocks"))
        profile = await db.get(CandidateProfile, cid)
        assert profile
        profile.consented_at = None
    assert not (await client.get(f"/api/v1/employer/recommendations/{sid}")).json()[
        "entries"
    ][0]["available"]
    async with sessions.begin() as db:
        profile = await db.get(CandidateProfile, cid)
        assert profile
        profile.consented_at = datetime.now(UTC)
        cycle = await db.scalar(
            select(AssessmentCycle).where(AssessmentCycle.user_id == candidate)
        )
        assert cycle
        cycle.review_state = "pending"
    assert not (await client.get(f"/api/v1/employer/recommendations/{sid}")).json()[
        "entries"
    ][0]["available"]
    async with sessions() as db:
        shot = await db.get(MatchingSnapshot, UUID(sid))
        assert shot
        assert "Тестовая Анна" not in str(
            shot.ranking
        ) and "candidate@example.com" not in str(shot.ranking)


async def test_api_cli_shared_computation(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    user = await register(client)
    cid = await synthetic_credit(sessions, user)
    employer = await register(client, "employer@example.com", "employer")
    await verified(sessions, employer)
    await login(client, "employer@example.com")
    need = (await client.post("/api/v1/employer/needs", json=need_body())).json()
    snapshot = (
        await client.post(
            f"/api/v1/employer/needs/{need['need_id']}/recommendations", json={}
        )
    ).json()
    product = snapshot["entries"][0]["recommendation"]
    async with sessions() as db:
        profile = await db.get(CandidateProfile, cid)
        assert profile
        before = [
            await db.scalar(select(func.count()).select_from(table))
            for table in [User, AssessmentCycle, MatchingSnapshot]
        ]
        assert profile.salary_min is not None and profile.salary_max is not None
        assert profile.available_from is not None
        assert profile.preferences_confirmed_at is not None
        conditions = {
            "salary_from": float(profile.salary_min),
            "salary_to": float(profile.salary_max),
            "work_formats": profile.work_preferences["formats"],
            "location": profile.work_preferences.get("location"),
            "available_from": profile.available_from.isoformat(),
            "confirmed_at": profile.preferences_confirmed_at.isoformat(),
        }
    # Внешний контракт помечает те же значения как jury fixture.
    fixture = {
        "schema_version": "matching-fixture-v1",
        "dataset_id": "isolated-api-cli-test",
        "as_of": snapshot["as_of"],
        "needs": [need],
        "candidates": [
            {
                "candidate_id": str(cid),
                "specialization": "backend",
                "grade": product["grade"],
                "category_status": "fixture_confirmed",
                "assessment_scope": {
                    **product["assessment_scope"],
                    "format": "jury-skill-100-v1",
                },
                "skills": {
                    code: {k: v for k, v in evidence.items() if k != "families"}
                    for code, evidence in product["skills"].items()
                },
                "technologies": product["technologies"],
                "fsp_verified": False,
                "conditions": conditions,
                "visibility": {"consent_to_match": True, "blocked_employer_ids": []},
            }
        ],
    }
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(fixture))
    assert main(["--input", str(path), "--output", str(tmp_path / "out")]) == 0
    rows = json.loads((tmp_path / "out/rankings.json").read_text())["rankings"]
    cli_ranking = next(r for r in rows if r["algorithm"] == "B2")
    fixture_data = model_input(Dataset, fixture)
    same_dto_api = compute(
        fixture_data.needs[0],
        candidates_from_fixture(fixture_data),
        fixture_data.as_of,
        frozenset(["backend-assessment-v1"]),
    )
    assert same_dto_api.model_dump(mode="json") == cli_ranking
    external = cli_ranking["recommendations"][0]
    for key in [
        "candidate_id",
        "grade",
        "group",
        "score",
        "components",
        "technologies",
        "missing_conditions",
        "reasons",
    ]:
        assert product[key] == external[key]
    assert (
        external["origin"] == "jury_fixture"
        and product["origin"] == "credit_assessment"
    )
    async with sessions() as db:
        after = [
            await db.scalar(select(func.count()).select_from(table))
            for table in [User, AssessmentCycle, MatchingSnapshot]
        ]
    assert before == after


async def test_fsp_ownership_dedup_unlink(
    client: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user = await register(client, "wrong@example.com")
    await verified(sessions, user)
    await login(client, "wrong@example.com")
    body = {"external_id": "demo-anna", "claim_code": "demo-anna-proof"}
    assert (
        await client.post("/api/v1/candidate/fsp/link", json=body)
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/candidate/fsp/link",
            json={"external_id": "missing", "claim_code": "any"},
        )
    ).status_code == 404
    anna = await register(client, "fsp-demo-anna@example.com")
    await login(client, "fsp-demo-anna@example.com")
    assert (
        await client.post("/api/v1/candidate/fsp/link", json=body)
    ).status_code == 403
    await verified(sessions, anna)
    assert (
        await client.post(
            "/api/v1/candidate/fsp/link", json={**body, "claim_code": "wrong"}
        )
    ).status_code == 403
    assert (
        await client.post("/api/v1/candidate/fsp/link", json=body)
    ).status_code == 200
    first = (await client.post("/api/v1/candidate/fsp/sync")).json()
    second = (await client.post("/api/v1/candidate/fsp/sync")).json()
    assert (
        first == second
        and len(first["achievements"]) == 1
        and first["source"] == "fsp_mock"
        and not first["verified_real_achievement"]
    )
    assert (await client.delete("/api/v1/candidate/fsp/link")).status_code == 200
    assert (await client.get("/api/v1/candidate/fsp/achievements")).json()[
        "status"
    ] == "not_linked"
    async with sessions() as db:
        assert await db.scalar(select(func.count()).select_from(FspLink)) == 0


@pytest.mark.parametrize(
    ("email", "external_id", "status"),
    [
        ("fsp-demo-empty@example.com", "demo-empty", "no_achievements"),
        (
            "fsp-demo-unavailable@example.com",
            "demo-unavailable",
            "temporarily_unavailable",
        ),
    ],
)
async def test_fsp_empty_and_unavailable(
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    email: str,
    external_id: str,
    status: str,
) -> None:
    user = await register(client, email)
    await verified(sessions, user)
    await login(client, email)
    assert (
        await client.post(
            "/api/v1/candidate/fsp/link",
            json={"external_id": external_id, "claim_code": external_id + "-proof"},
        )
    ).status_code == 200
    result = (await client.post("/api/v1/candidate/fsp/sync")).json()
    assert result["status"] == status and result["achievements"] == []
