"""Регрессии понятного результата и сохранности стартовых пользовательских данных."""

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment.models import AssessmentCycle
from app.assessment.service import result_view
from app.assessment.v3_models import V3_METHODOLOGY
from app.auth.models import User
from app.candidate_profile.models import CandidateProfile
from app.core.config import Settings
from app.notifications.queue import utc_now
from app.tools.populate_product import account, products
from tests.test_auth_profiles import auth_app as auth_app


def test_failed_credit_has_human_task_titles_without_demo_label() -> None:
    """Высокий балл не меняет отказ; старое сохранение получает названия при чтении."""
    cycle = AssessmentCycle(
        id=uuid4(),
        user_id=uuid4(),
        mode="credit",
        grade="junior",
        form="Y",
        outcome="not_confirmed",
        state="completed",
        review_state="clear",
        methodology=V3_METHODOLOGY,
        completed_at=utc_now(),
        admission={},
        materials={"Y2-J": {"title": "Доступ к своему счёту"}},
        result={
            "total": 91.67,
            "skills": [],
            "requirements": [
                {
                    "task_id": "Y2-J",
                    "family_id": "Y2",
                    "skill": "security_validation",
                    "action": "Проверка доступа в точке записи",
                    "status": "completed",
                    "passed": False,
                }
            ],
        },
    )
    view = result_view(cycle)
    assert view.outcome == "not_confirmed" and not view.verified
    assert view.requirements[0].task_title == "Доступ к своему счёту"
    assert view.requirements[0].task_number == 1
    assert "демонстра" not in view.label.lower()
    assert cycle.result["total"] == 91.67


@pytest.mark.integration
async def test_starter_account_is_idempotent_and_preserves_edits(
    auth_app: FastAPI, sessions: async_sessionmaker[AsyncSession]
) -> None:
    settings: Settings = auth_app.state.settings
    async with sessions.begin() as db:
        user_id = await account(db, settings, 1, "candidate")
    async with sessions.begin() as db:
        user = await db.get(User, user_id)
        profile = await db.scalar(
            select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        )
        assert user and profile and user.email_verified_at
        user.password_hash = "changed-by-user"
        profile.summary = "Пользователь изменил описание"
        profile.privacy = {"show_name": True, "visible_to_employers": False}
    async with sessions.begin() as db:
        assert await account(db, settings, 1, "candidate") == user_id
    async with sessions() as db:
        user = await db.get(User, user_id)
        profile = await db.scalar(
            select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        )
        assert user and profile
        assert user.password_hash == "changed-by-user"
        assert profile.summary == "Пользователь изменил описание"
        assert profile.privacy == {"show_name": True, "visible_to_employers": False}
        assert len(list(await db.scalars(select(User.id)))) == 1


def test_public_examples_cover_every_v3_card_without_reference_sources() -> None:
    import json

    bank = json.loads(Path("bank/private/v3.json").read_text())
    examples = Path("frontend/src/task-examples.ts").read_text()
    assert all(f'"{card["task_id"]}"' in examples for card in bank["cards"])
    for card in bank["cards"]:
        assert all(
            solution["base"] not in examples
            for solution in card["solutions"]
            if len(solution["base"]) > 80
        )


async def test_starter_need_uses_valid_numeric_salary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Наполнение проходит строгий контракт денег до обращения к сохранению."""
    from app.matching import service as matching

    employer = uuid4()
    db = AsyncMock(spec=AsyncSession)
    db.scalar.return_value = None
    db.get.return_value = None
    save = AsyncMock()
    save.return_value.need_id = str(uuid4())
    monkeypatch.setattr(matching, "save_need", save)
    with pytest.raises(RuntimeError, match="starter_need_missing"):
        await products(db, [employer], [uuid4()])
    need = save.call_args.args[2]
    assert need.salary_from == Decimal(100000)
    assert need.salary_to == Decimal(250000)


def test_pdf_does_not_turn_missing_evidence_into_failed_skill() -> None:
    from io import BytesIO

    from pypdf import PdfReader

    from app.assessment.schemas import ResultView
    from app.candidate_profile.pdf import generate_pdf
    from app.candidate_profile.schemas import SafeCard

    result = ResultView.model_validate(
        {
            "outcome": "insufficient",
            "label": "Недостаточно данных",
            "grade": "junior",
            "mode": "credit",
            "verified": False,
            "methodology": V3_METHODOLOGY,
            "scope": "Backend",
            "limitations": "",
            "total": None,
            "skills": [
                {
                    "skill": "http_api",
                    "status": "insufficient",
                    "score": None,
                    "families": 0,
                }
            ],
        }
    )
    card = SafeCard.model_validate(
        {
            "id": str(uuid4()),
            "display_name": "Анна",
            "summary": "Профиль",
            "experience": "Разработка",
            "salary_min": None,
            "salary_max": None,
            "salary_basis": "gross",
            "available_from": None,
            "work_preferences": {"formats": ["remote"]},
            "technology_ids": [],
            "technology_names": [],
            "assessment": result,
        }
    )
    text = "\n".join(
        p.extract_text() for p in PdfReader(BytesIO(generate_pdf(card))).pages
    )
    assert "HTTP и API: недостаточно данных" in text
    assert "удалённо" in text and "нужна доработка" not in text
    assert "None" not in text and V3_METHODOLOGY not in text
