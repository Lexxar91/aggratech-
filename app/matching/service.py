"""Продуктовая проекция допускает только опубликованные зачётные доказательства."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assessment.models import (
    AssessmentCycle,
    AssessmentPublication,
    AssessmentSurvey,
)
from app.assessment.policy import METHODOLOGY
from app.assessment.runtime_bank import credit_admission_valid
from app.assessment.v3_models import V3_METHODOLOGY
from app.candidate_profile.models import (
    CandidateEmployerBlock,
    CandidateProfile,
    CandidateTechnology,
)
from app.candidate_profile.service import card, visible_profile
from app.catalog.models import Technology
from app.core.errors import ApiError
from app.employer.models import EmployerProfile
from app.fsp.models import FspLink
from app.matching.catalog import (
    ALGORITHM_VERSION,
    CATALOG_VERSION,
    VERIFIED_TECHNOLOGIES,
)
from app.matching.engine import rank
from app.matching.models import (
    CandidateNeedMark,
    EmployerNeed,
    MatchingSnapshot,
    NeedVersion,
)
from app.matching.schemas import Candidate, Need, Ranking, Recommendation

PRODUCT_METHODS = frozenset([METHODOLOGY, V3_METHODOLOGY])


class SnapshotEntry(BaseModel):
    candidate_id: UUID
    available: bool
    saved: bool = False
    hidden: bool = False
    card: dict[str, object] | None = None
    recommendation: Recommendation | None = None
    notice: str | None = None


class SnapshotView(BaseModel):
    id: UUID
    need_id: UUID
    need_version: int
    as_of: datetime
    algorithm_version: str
    catalog_version: str
    entries: list[SnapshotEntry] = Field(default_factory=list)
    notice: str = "Подбор по проверенным навыкам, уровню и условиям работы."


_TEMPLATE_DATA = json.loads(
    Path("fixtures/demo/vacancy_examples.json").read_text(encoding="utf-8")
)


def templates() -> list[dict[str, object]]:
    """Публичная часть трёх шаблонов не раскрывает трассировку закрытых рубрик."""
    data = _TEMPLATE_DATA
    return [
        {
            "code": row["id"],
            "version": data["version"],
            "title": row["title"],
            "task_description": row["description"],
            "skill_priorities": row["priorities"],
            "accepted_grades": [row["grade"]],
        }
        for row in data["examples"]
    ]


async def company(db: AsyncSession, user_id: UUID) -> EmployerProfile:
    """Компания доступна только активному владельцу."""
    row = await db.scalar(
        select(EmployerProfile).where(
            EmployerProfile.user_id == user_id, EmployerProfile.status == "active"
        )
    )
    if row is None:
        raise ApiError(404, "company_unavailable", "Компания недоступна.")
    return row


async def owned_need(
    db: AsyncSession, user_id: UUID, need_id: UUID, *, lock: bool = False
) -> EmployerNeed:
    """Не позволяет читать или редактировать чужую потребность."""
    employer = await company(db, user_id)
    query = select(EmployerNeed).where(
        EmployerNeed.id == need_id, EmployerNeed.employer_id == employer.id
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query)
    if row is None:
        raise ApiError(404, "need_unavailable", "Потребность недоступна.")
    return row


def valid_template(data: Need) -> None:
    """Сохраняет явное происхождение, но разрешает редактировать все поля шаблона."""
    if data.template_code is not None and not any(
        t["code"] == data.template_code and t["version"] == data.template_version
        for t in templates()
    ):
        raise ApiError(422, "unknown_template", "Версия шаблона неизвестна.")


async def save_need(
    db: AsyncSession, user_id: UUID, data: Need, existing: EmployerNeed | None = None
) -> Need:
    """Создаёт неизменяемую версию, проверяя конкурентное редактирование."""
    employer = await company(db, user_id)
    valid_template(data)
    if existing is not None and data.version != existing.version:
        raise ApiError(
            409, "need_version_conflict", "Потребность изменена. Обновите страницу."
        )
    identifier = existing.id if existing else uuid4()
    definition = data.model_copy(
        update={
            "need_id": str(identifier),
            "employer_id": str(employer.id),
            "version": existing.version + 1 if existing else 1,
        }
    )
    if existing is None:
        existing = EmployerNeed(
            id=identifier,
            employer_id=employer.id,
            version=definition.version,
            definition=definition.model_dump(mode="json"),
        )
        db.add(existing)
    else:
        existing.version = definition.version
        existing.definition = definition.model_dump(mode="json")
    await db.flush()
    db.add(
        NeedVersion(
            need_id=identifier,
            version=definition.version,
            definition=definition.model_dump(mode="json"),
            created_at=datetime.now(UTC),
        )
    )
    return definition


async def published_cycle(db: AsyncSession, user_id: UUID) -> AssessmentCycle | None:
    """Не принимает демо, незакрытый review и отсутствие зачётного допуска."""
    row = await db.scalar(
        select(AssessmentCycle)
        .join(
            AssessmentPublication, AssessmentPublication.cycle_id == AssessmentCycle.id
        )
        .where(
            AssessmentPublication.user_id == user_id,
            AssessmentPublication.mode == "credit",
            AssessmentCycle.user_id == user_id,
            AssessmentCycle.mode == "credit",
            AssessmentCycle.outcome == "confirmed",
            AssessmentCycle.review_state == "clear",
            AssessmentCycle.state == "completed",
            AssessmentPublication.grade == AssessmentCycle.grade,
        )
    )
    if row is None or not credit_admission_valid(row):
        return None
    return row


async def product_candidates(
    db: AsyncSession, employer_id: UUID, now: datetime
) -> list[Candidate]:
    """Проецирует реальные credit-результаты; в приложении нет fixture-импорта."""
    rows = await db.scalars(select(CandidateProfile).order_by(CandidateProfile.id))
    result: list[Candidate] = []
    for profile in rows:
        if (
            not profile.consented_at
            or profile.privacy.get("visible_to_employers") is not True
        ):
            continue
        if await db.get(CandidateEmployerBlock, (profile.id, employer_id)):
            continue
        cycle = await published_cycle(db, profile.user_id)
        if cycle is None or cycle.completed_at is None or cycle.completed_at > now:
            continue
        skills = {}
        evidence_rows = cycle.result.get("skills", [])
        if not isinstance(evidence_rows, list):
            continue
        for evidence in evidence_rows:
            if (
                isinstance(evidence, dict)
                and evidence.get("status") == "met"
                and isinstance(evidence.get("score"), (float, int))
            ):
                skills[str(evidence["skill"])] = {
                    "score": evidence["score"],
                    "verified_at": cycle.completed_at,
                    "mode": "independent",
                    "families": evidence["families"],
                }
        declarations = await db.scalars(
            select(Technology.code)
            .join(
                CandidateTechnology, CandidateTechnology.technology_id == Technology.id
            )
            .where(CandidateTechnology.candidate_id == profile.id)
        )
        technologies = {code: "self_reported" for code in declarations}
        for code, skill in VERIFIED_TECHNOLOGIES.items():
            if skill in skills:
                technologies[code] = "verified"
        survey = await db.get(AssessmentSurvey, profile.user_id)
        experience = survey.answers.get("experience_years") if survey else None
        fsp = await db.get(FspLink, profile.id)
        value = {
            "evidence_snapshot": {
                "cycle_id": str(cycle.id),
                "bank_sha256": cycle.bank_hash,
                "evaluator_sha256": cycle.evaluator_hash,
                "method_version": cycle.methodology,
            },
            "candidate_id": str(profile.id),
            "specialization": "backend",
            "grade": cycle.grade,
            "category_status": "confirmed",
            "origin": "credit_assessment",
            "assessment_scope": {
                "language": "python",
                "method_version": cycle.methodology,
                "format": "assessment-skill-100-v1",
            },
            "skills": skills,
            "technologies": technologies,
            "fsp_verified": False,
            "fsp_origin": "fsp_mock" if fsp else "none",
            "conditions": {
                "salary_from": profile.salary_min,
                "salary_to": profile.salary_max,
                "work_formats": profile.work_preferences.get("formats", []),
                "location": profile.work_preferences.get("location"),
                "available_from": profile.available_from,
                "confirmed_at": profile.preferences_confirmed_at,
            },
            "visibility": {"consent_to_match": True, "blocked_employer_ids": []},
            "experience_years": experience,
        }
        result.append(Candidate.model_validate(value))
    return result


def compute(
    need: Need, candidates: list[Candidate], as_of: datetime, methods: frozenset[str]
) -> Ranking:
    """Общий вычислительный путь API и CLI не принимает labels."""
    return rank(need, candidates, as_of=as_of, comparable_methods=methods)


async def build_snapshot(db: AsyncSession, row: EmployerNeed) -> MatchingSnapshot:
    """Снимает текущую версию потребности и доказательств без контактных данных."""
    now = datetime.now(UTC)
    need = Need.model_validate(row.definition)
    candidates = await product_candidates(db, row.employer_id, now)
    ranking = compute(need, candidates, now, PRODUCT_METHODS)
    snapshot = MatchingSnapshot(
        id=uuid4(),
        need_id=row.id,
        need_version=row.version,
        created_at=now,
        algorithm_version=ALGORITHM_VERSION,
        catalog_version=CATALOG_VERSION,
        definition=row.definition,
        ranking=ranking.model_dump(mode="json"),
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def snapshot_view(
    db: AsyncSession, snapshot: MatchingSnapshot, employer_user: UUID
) -> SnapshotView:
    """Повторно проверяет приватность и категорию каждой прежней доступной карточки."""
    await owned_need(db, employer_user, snapshot.need_id)
    entries: list[SnapshotEntry] = []
    for recommendation in Ranking.model_validate(snapshot.ranking).recommendations:
        if recommendation.group == "excluded":
            continue
        identifier = UUID(recommendation.candidate_id)
        mark = await db.get(CandidateNeedMark, (snapshot.need_id, identifier))
        saved = mark.saved if mark else False
        hidden = mark.hidden if mark else False
        try:
            profile = await visible_profile(db, identifier, employer_user)
            cycle = await published_cycle(db, profile.user_id)
            original_id = recommendation.evidence_snapshot.get("cycle_id")
            original = (
                await db.get(AssessmentCycle, UUID(original_id))
                if original_id
                else None
            )
            original_valid = (
                original is not None
                and original.user_id == profile.user_id
                and original.mode == "credit"
                and original.outcome == "confirmed"
                and original.review_state == "clear"
                and original.state == "completed"
                and credit_admission_valid(original)
                and original.bank_hash
                == recommendation.evidence_snapshot.get("bank_sha256")
                and original.evaluator_hash
                == recommendation.evidence_snapshot.get("evaluator_sha256")
            )
            if (
                cycle is None
                or cycle.grade != recommendation.grade
                or hidden
                or not original_valid
            ):
                raise ApiError(404, "profile_unavailable", "Карточка недоступна.")
        except ApiError as error:
            if error.status_code != 404:
                raise
            entries.append(
                SnapshotEntry(
                    candidate_id=identifier,
                    available=False,
                    saved=saved,
                    hidden=hidden,
                    notice="Карточка недоступна.",
                )
            )
            continue
        entries.append(
            SnapshotEntry(
                candidate_id=identifier,
                available=True,
                saved=saved,
                hidden=hidden,
                card=(await card(db, profile)).model_dump(mode="json"),
                recommendation=recommendation,
            )
        )
    return SnapshotView(
        id=snapshot.id,
        need_id=snapshot.need_id,
        need_version=snapshot.need_version,
        as_of=snapshot.created_at,
        algorithm_version=snapshot.algorithm_version,
        catalog_version=snapshot.catalog_version,
        entries=entries,
    )
