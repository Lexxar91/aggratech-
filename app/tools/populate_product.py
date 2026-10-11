"""Стартовое наполнение: штатные переходы и настоящий runner, без ручных оценок."""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment import service as assessment
from app.assessment.models import AssessmentCycle
from app.assessment.runtime_bank import admitted_bank
from app.assessment.schemas import CycleInput, SaveAnswer, SurveyInput, TaskAnswer
from app.assessment.v3_models import V3Card
from app.auth.models import User
from app.auth.schemas import Registration
from app.auth.service import AuthService
from app.candidate_profile import service as profiles
from app.candidate_profile.schemas import (
    ContactsInput,
    Privacy,
    ProfileInput,
    WorkPreferences,
)
from app.catalog.models import Technology
from app.core import models  # noqa: F401 — FK для отдельного процесса
from app.core.config import Settings
from app.core.database import create_database, create_sessions
from app.employer.models import EmployerProfile
from app.invitations import service as invitations
from app.invitations.schemas import Acceptance, Offer, SendInput
from app.matching import service as matching
from app.matching.models import EmployerNeed
from app.matching.schemas import Need
from app.notifications.models import AuditEvent, BackgroundJob
from app.notifications.queue import utc_now
from app.vacancies import service as vacancies
from app.vacancies.schemas import ApplicationInput, VacancyInput
from app.worker import process_one

logger = logging.getLogger(__name__)
PASSWORD = "StartProduct2026!"
NAMES = [
    "Анна Смирнова",
    "Илья Волков",
    "Мария Соколова",
    "Денис Орлов",
    "Елена Кузнецова",
    "Олег Морозов",
    "Алина Лебедева",
    "Михаил Павлов",
    "София Новикова",
    "Артём Попов",
    "Дарья Алексеева",
    "Никита Васильев",
]
TEAMS = ["Линия данных", "Городские сервисы", "Финтех решения"]


def marker(key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"aggratech:starter-v1:{key}")


def record(db: AsyncSession, key: str, **metadata: object) -> None:
    db.add(
        AuditEvent(
            action="starter_initialized",
            entity_type="starter_data",
            entity_id=marker(key),
            safe_metadata={"key": key, "origin": "starter_product_v1", **metadata},
            created_at=utc_now(),
        )
    )


async def account(db: AsyncSession, settings: Settings, index: int, role: str) -> UUID:
    """Создаёт аккаунт однажды; существующий пароль и профиль не меняет."""
    key = f"{role}-{index:02d}"
    saved = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "starter_initialized",
            AuditEvent.entity_id == marker(key),
        )
    )
    if saved:
        return UUID(str(saved.safe_metadata["user_id"]))
    email = f"{role}{index:02d}@aggratech.example.com"
    if await db.scalar(select(User.id).where(User.email_normalized == email)):
        raise RuntimeError("starter_reserved_account_conflict")
    auth = AuthService(settings)
    user = await auth.register(
        db,
        Registration.model_validate(
            {"email": email, "password": PASSWORD, "role": role}
        ),
    )
    job = await db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.kind == "auth_email",
            BackgroundJob.payload["email"].astext == email,
        )
    )
    if not job:
        raise RuntimeError("starter_verification_mail_missing")
    await auth.action(db, str(job.payload["token"]), "verify_email")
    if role == "candidate":
        i = index - 1
        technologies = list(
            await db.scalars(
                select(Technology.id).where(
                    Technology.code.in_(
                        ["python", "sql", "postgresql"] if i % 2 else ["python", "sql"]
                    )
                )
            )
        )
        await profiles.save_profile(
            db,
            user.id,
            ProfileInput(
                display_name=NAMES[i],
                summary=[
                    "Разрабатываю API и интеграции для сервисов.",
                    "Работаю с обработкой данных и SQL-запросами.",
                    "Создаю надёжные сервисы и автоматизацию.",
                ][i % 3],
                experience=(
                    f"Опыт разработки: {1 + i % 6} лет. "
                    "Python, PostgreSQL, тестирование и командная работа."
                ),
                salary_min=Decimal(90000 + i * 10000),
                salary_max=Decimal(120000 + i * 10000),
                available_from=utc_now().date() + timedelta(days=i * 2),
                work_preferences=WorkPreferences(
                    formats=["remote", "hybrid"] if i % 2 else ["remote"],
                    location="Москва" if i % 2 else None,
                ),
                technology_ids=technologies,
                confirm_preferences=True,
                consent_version="profile-v1",
            ),
        )
        await profiles.contacts(
            db,
            await profiles.own_profile(db, user.id),
            ContactsInput(email=email, phone=f"+7999000{index:04d}"),
        )
        await profiles.save_privacy(
            db, user.id, Privacy(visible_to_employers=i != 11, show_name=i % 3 != 0)
        )
        await assessment.save_survey(
            db,
            user.id,
            SurveyInput(
                industry="IT",
                stack=["Python", "SQL", "HTTP"],
                experience_years=1 + i % 6,
                instructions_accepted=True,
            ),
            utc_now(),
        )
    else:
        company = await db.scalar(
            select(EmployerProfile).where(EmployerProfile.user_id == user.id)
        )
        if not company:
            raise RuntimeError("starter_company_missing")
        company.company_name = TEAMS[index - 1]
        company.description = [
            "Продукты аналитики и обработки данных.",
            "Цифровые сервисы для городской жизни.",
            "Платёжные API и финансовая инфраструктура.",
        ][index - 1]
        company.industry = "IT"
        company.representative_contact = email
        company.version += 1
    record(db, key, user_id=str(user.id))
    return user.id


async def qualify(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    user: UUID,
    index: int,
) -> None:
    """Проходит A/B через сервис; оценки записывает только обычный worker."""
    key = f"qualification-{index}"
    async with sessions.begin() as db:
        if await db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "starter_initialized",
                AuditEvent.entity_id == marker(key),
            )
        ):
            return
        cycle = await db.scalar(
            select(AssessmentCycle)
            .where(AssessmentCycle.user_id == user)
            .order_by(AssessmentCycle.created_at)
        )
        if cycle is None:
            cycle = await assessment.create_cycle(
                db,
                user,
                CycleInput(grade="junior" if index <= 6 else "middle", mode="credit"),
                settings,
                utc_now(),
            )
            # Метаданные не меняют live_credit или криптографический допуск.
            cycle.admission = {
                **cycle.admission,
                "starter_data": True,
                "human_attempt": False,
            }
        identifier = cycle.id
        for phase in ("A", "B"):
            if cycle.state == "B_ready" and phase == "B":
                await assessment.start_b(db, cycle, utc_now())
            if cycle.state != phase:
                continue
            await assessment.cycle_view(db, cycle, utc_now())
            for row in await assessment.answers(db, cycle.id):
                if row.phase != phase or row.finalized_at:
                    continue
                card = assessment.material(cycle, row.family)
                if not isinstance(card, V3Card):
                    raise RuntimeError("starter_requires_v3")
                solutions = [
                    s for s in card.solutions if s.kind in {"reference", "alternative"}
                ]
                solution = solutions[(index - 1) % len(solutions)]
                if row.step == "base":
                    await assessment.save_answer(
                        db,
                        cycle,
                        row.family,
                        SaveAnswer(
                            revision=row.revision,
                            step="base",
                            answer=TaskAnswer(source=solution.base),
                        ),
                        utc_now(),
                        finalize=True,
                    )
                await assessment.save_answer(
                    db,
                    cycle,
                    row.family,
                    SaveAnswer(
                        revision=row.revision,
                        step="transfer",
                        answer=TaskAnswer(source=solution.transfer),
                    ),
                    utc_now(),
                    finalize=True,
                )
            await assessment.submit_phase(db, cycle, phase, utc_now())
    # Lease, hash guard, runner and persisted observations use the normal path.
    deadline = asyncio.get_running_loop().time() + 1200
    while True:
        async with sessions() as db:
            cycle = await db.get(AssessmentCycle, identifier)
            if not cycle:
                raise RuntimeError("starter_cycle_missing")
            if cycle.state == "completed":
                if not assessment.result_view(cycle).verified:
                    raise RuntimeError("starter_level_not_confirmed")
                break
            if cycle.state in {"technical_error", "expired", "invalidated"}:
                raise RuntimeError("starter_assessment_failed")
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError("starter_assessment_timeout")
        if not await process_one(sessions, settings):
            await asyncio.sleep(1)
    async with sessions.begin() as db:
        await assessment.publish(db, user, identifier, utc_now())
        record(db, key, cycle_id=str(identifier), human_attempt=False)


async def products(
    db: AsyncSession, employers: list[UUID], candidates: list[UUID]
) -> None:
    """Создаёт поиск, вакансии и легальные переходы только в первую транзакцию."""
    if await db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.action == "starter_initialized",
            AuditEvent.entity_id == marker("products"),
        )
    ):
        return
    for i, employer in enumerate(employers):
        need = await matching.save_need(
            db,
            employer,
            Need.model_validate(
                {
                    "need_id": "starter",
                    "employer_id": "starter",
                    "title": [
                        "Python-разработчик API",
                        "Разработчик сервисов данных",
                        "Backend-разработчик платежей",
                    ][i],
                    "specialization": "backend",
                    "accepted_grades": ["junior", "middle"],
                    "required_stack": [],
                    "preferred_stack": ["python", "sql"],
                    "skill_priorities": {"sql_data": 2} if i == 1 else {"http_api": 2},
                    "required_verified_skills": ["http_api"],
                    "work_formats": ["remote"],
                    "location": None,
                    "salary_from": 100000,
                    "salary_to": 250000,
                    "desired_start_date": None,
                    "start_date_required": False,
                    "task_description": (
                        "Развитие API, работа с данными, "
                        "тестирование и поддержка сервисов."
                    ),
                    "team_description": (
                        "Небольшая продуктовая команда, "
                        "поддержка наставника и ревью кода."
                    ),
                }
            ),
        )
        row = await db.get(EmployerNeed, UUID(need.need_id))
        if not row:
            raise RuntimeError("starter_need_missing")
        await matching.build_snapshot(db, row)
        offer = Offer(
            description=need.task_description,
            salary_from=need.salary_from,
            salary_to=need.salary_to,
            work_formats=["remote"],
            conditions="Полный рабочий день, обучение, оплачиваемый отпуск.",
            representative_contact=f"employer{i + 1:02d}@aggratech.example.com",
        )
        for j in range(3):
            vacancy = await vacancies.create(
                db,
                employer,
                VacancyInput(
                    **offer.model_dump(),
                    title=[
                        "Python-разработчик",
                        "SQL-разработчик",
                        "Backend-разработчик",
                    ][j],
                    need_id=UUID(need.need_id),
                ),
            )
            for k in range(2):
                candidate = candidates[(i * 3 + j + k) % len(candidates)]
                application = await vacancies.apply(
                    db,
                    candidate,
                    vacancy.id,
                    ApplicationInput(
                        allowed_fields=["email"],
                        consent_version="contacts-v1",
                        message="Интересны ваши задачи. Готов обсудить опыт и условия.",
                    ),
                )
                target = ("viewed", "accepted", "rejected", "withdrawn")[
                    (i + j + k) % 4
                ]
                await vacancies.action(
                    db,
                    candidate if target == "withdrawn" else employer,
                    "candidate" if target == "withdrawn" else "employer",
                    application.id,
                    target,
                )
            if j == 2:
                await vacancies.close(db, employer, vacancy.id)
        for j, state in enumerate(
            ("sent", "viewed", "accepted", "rejected", "withdrawn")
        ):
            candidate = candidates[(j + i * 3) % 11]
            profile = await profiles.own_profile(db, candidate)
            now = utc_now()
            invitation = await invitations.send(
                db,
                employer,
                SendInput(
                    need_id=UUID(need.need_id),
                    candidate_id=profile.id,
                    idempotency_key=f"starter-{i}-{j}",
                    offer=offer,
                ),
                now=now,
            )
            if state != "sent":
                await invitations.action(
                    db,
                    employer if state == "withdrawn" else candidate,
                    "employer" if state == "withdrawn" else "candidate",
                    invitation.id,
                    state,
                    Acceptance(allowed_fields=["email"], consent_version="contacts-v1")
                    if state == "accepted"
                    else None,
                )
    record(db, "products")


async def populate(settings: Settings) -> None:
    """Сериализует повторный запуск, не сбрасывая пользовательские изменения."""
    await asyncio.to_thread(admitted_bank, settings, "credit")
    engine = create_database(settings)
    sessions = create_sessions(engine)
    try:
        # Отдельное соединение держит session advisory lock между транзакциями.
        async with engine.connect() as lock:
            await lock.execute(text("SELECT pg_advisory_lock(71620261011)"))
            try:
                candidates: list[UUID] = []
                employers: list[UUID] = []
                for role, count, target in (
                    ("candidate", 12, candidates),
                    ("employer", 3, employers),
                ):
                    for index in range(1, count + 1):
                        async with sessions.begin() as db:
                            target.append(await account(db, settings, index, role))
                for index, user in enumerate(candidates, 1):
                    await qualify(sessions, settings, user, index)
                    logger.warning("starter_assessment_completed %s/12", index)
                async with sessions.begin() as db:
                    await products(db, employers, candidates)
            finally:
                await lock.execute(text("SELECT pg_advisory_unlock(71620261011)"))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(populate(Settings()))
