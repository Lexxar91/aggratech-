"""Фильтры и формула 03; модуль не получает labels и не обращается к сервисам."""

from datetime import datetime
from typing import Literal

from app.matching.catalog import (
    DEFAULT_PRIORITIES,
    SKILLS,
    VERIFIED_TECHNOLOGIES,
    SkillCode,
)
from app.matching.schemas import (
    Candidate,
    Components,
    Evidence,
    Need,
    Ranking,
    Recommendation,
)

Algorithm = Literal["B0", "B1", "B2"]


def freshness(verified_at: datetime | None, as_of: datetime) -> float:
    """Считает полные дни актуальности относительно фиксированного времени."""
    if verified_at is None:
        return 0
    days = (as_of - verified_at).days
    return 1 if days <= 90 else 0.5 if days <= 180 else 0


def filter_candidate(
    need: Need, candidate: Candidate, skills: dict[SkillCode, Evidence]
) -> tuple[list[str], list[str]]:
    """Различает известное противоречие и неизвестное условие до ранжирования."""
    reasons: list[str] = []
    missing: list[str] = []
    if (
        not candidate.visibility.consent_to_match
        or need.employer_id in candidate.visibility.blocked_employer_ids
    ):
        return ["privacy"], []
    if candidate.category_status != "confirmed":
        reasons.append("unconfirmed_category")
    if candidate.specialization != need.specialization:
        reasons.append("specialization")
    if candidate.grade not in need.accepted_grades:
        reasons.append("grade")
    for item in need.required_stack:
        status = candidate.technologies.get(item.technology)
        if status is None or (item.verification_required and status != "verified"):
            reasons.append("required_technology:" + item.technology)
    for skill in need.required_verified_skills:
        if skill not in skills:
            reasons.append("required_skill:" + skill)
    conditions = candidate.conditions
    if conditions.salary_from is None:
        missing.append("salary")
    elif need.salary_to < conditions.salary_from or (
        conditions.salary_to is not None and need.salary_from > conditions.salary_to
    ):
        reasons.append("salary")
    if not conditions.work_formats:
        missing.append("work_formats")
    else:
        common = set(need.work_formats) & set(conditions.work_formats)
        if not common:
            reasons.append("work_formats")
        elif "remote" not in common:
            if not conditions.location:
                missing.append("location")
            elif conditions.location != need.location:
                reasons.append("location")
    if need.desired_start_date:
        if conditions.available_from is None:
            missing.append("available_from")
        elif (
            need.start_date_required
            and conditions.available_from > need.desired_start_date
        ):
            reasons.append("start_date")
    years = need.additional_requirements.get("required_experience_years")
    if years is not None:
        if candidate.experience_years is None:
            missing.append("experience_years")
        elif candidate.experience_years < years:
            reasons.append("experience_years")
    return reasons, missing


def components(
    need: Need, candidate: Candidate, skills: dict[SkillCode, Evidence], as_of: datetime
) -> Components:
    """Вычисляет T/K/A/F/U/P без перераспределения весов при отсутствии ФСП."""
    priorities = need.skill_priorities or DEFAULT_PRIORITIES[candidate.grade]
    divisor = sum(priorities.values())
    T = (
        sum(
            weight * (skills[skill].score / 100 if skill in skills else 0)
            for skill, weight in priorities.items()
        )
        / divisor
    )
    U = (
        sum(
            weight
            * freshness(skills[skill].verified_at if skill in skills else None, as_of)
            for skill, weight in priorities.items()
        )
        / divisor
    )
    requested = {x.technology: 2 for x in need.required_stack} | {
        x: 1 for x in need.preferred_stack
    }
    coefficients = {"verified": 1.0, "self_reported": 0.6}
    K = (
        sum(
            weight * coefficients.get(candidate.technologies.get(code, ""), 0)
            for code, weight in requested.items()
        )
        / sum(requested.values())
        if requested
        else 1.0
    )
    A = 1.0
    if need.desired_start_date:
        A = (
            max(
                0.0,
                1.0
                - max(
                    0,
                    (
                        candidate.conditions.available_from - need.desired_start_date
                    ).days,
                )
                / 30,
            )
            if candidate.conditions.available_from
            else 0.0
        )
    conditions_age = freshness(candidate.conditions.confirmed_at, as_of)
    P = 0.0 if conditions_age == 1 else 3.0 if conditions_age == 0.5 else 5.0
    return Components(
        T=round(T, 8),
        K=round(K, 8),
        A=round(A, 8),
        F=1.0 if candidate.fsp_verified else 0.0,
        U=round(U, 8),
        P=P,
    )


def explain(
    need: Need,
    candidate: Candidate,
    skills: dict[SkillCode, Evidence],
    value: Components,
    missing: list[str],
    algorithm: Algorithm,
) -> list[str]:
    """Показывает фактические основания и пробелы, не раскрывая зарплатные ожидания."""
    priorities = need.skill_priorities or DEFAULT_PRIORITIES[candidate.grade]
    result = [
        "Источник категории: "
        + (
            "внешний тестовый fixture; квалификация сервисом не подтверждена"
            if candidate.origin == "jury_fixture"
            else "опубликованный самостоятельный assessment; методика экспериментальная"
        )
    ]
    if algorithm == "B2":
        strongest = sorted(
            priorities,
            key=lambda skill: (
                -priorities[skill],
                -(skills[skill].score if skill in skills else 0),
                skill,
            ),
        )[:3]
        for skill in strongest:
            result.append(
                f"{SKILLS[skill]}: "
                + (
                    f"{skills[skill].score:g}/100, приоритет {priorities[skill]}"
                    if skill in skills
                    else (
                        "нет сопоставимого доказательства; это не оценка "
                        "некомпетентности"
                    )
                )
            )
    elif algorithm == "B0":
        result.append("B0: только фильтры и стабильный идентификатор.")
    else:
        result.append("B1: порядок по совпадению запрошенного стека.")
    requested = [x.technology for x in need.required_stack] + need.preferred_stack
    if requested:
        declared = sum(code in candidate.technologies for code in requested)
        verified = sum(
            candidate.technologies.get(code) == "verified" for code in requested
        )
        result.append(f"Стек: {declared} из {len(requested)}, подтверждено {verified}.")
    result.append(
        "Зарплату нужно уточнить."
        if "salary" in missing
        else "Зарплатные диапазоны пересекаются; весь диапазон не гарантирован."
    )
    if missing:
        result.append("Нужно уточнить: " + ", ".join(missing) + ".")
    if algorithm == "B2":
        result.append(
            "ФСП: "
            + (
                "подтверждение внешнего тестового набора."
                if value.F and candidate.origin == "jury_fixture"
                else "подтверждённое происхождение и принадлежность."
                if value.F
                else "нет подтверждённой истории; F=0, остальные веса сохранены."
            )
        )
        if candidate.fsp_origin == "fsp_mock":
            result.append(
                "ФСП mock: демонстрационные записи, не подтверждение "
                "реальных достижений."
            )
        result.append(
            f"Актуальность доказательств U={value.U:g}; штраф условий P={value.P:g}."
        )
    return result


def rank(
    need: Need,
    candidates: list[Candidate],
    *,
    as_of: datetime,
    comparable_methods: frozenset[str],
    algorithm: Algorithm = "B2",
) -> Ranking:
    """Ранжирует отдельно категории/группы: Score → T → K → candidate_id."""
    rows: list[Recommendation] = []
    requested = [x.technology for x in need.required_stack] + need.preferred_stack
    for candidate in candidates:
        skills = (
            candidate.skills
            if candidate.assessment_scope.method_version in comparable_methods
            else {}
        )
        # Неподдерживаемая версия не сохраняет verified-коэффициент технологии.
        candidate = candidate.model_copy(
            update={
                "technologies": {
                    code: (
                        "verified"
                        if status == "verified"
                        and VERIFIED_TECHNOLOGIES.get(code) in skills
                        else "self_reported"
                    )
                    for code, status in candidate.technologies.items()
                }
            }
        )
        reasons, missing = filter_candidate(need, candidate, skills)
        values = components(need, candidate, skills, as_of)
        total = (
            55 * values.T
            + 25 * values.K
            + 8 * values.A
            + 7 * values.F
            + 5 * values.U
            - values.P
        )
        score = (
            round(max(0.0, min(100.0, total)), 6)
            if algorithm == "B2"
            else round(100 * values.K, 6)
            if algorithm == "B1"
            else 0.0
        )
        group: Literal["eligible", "needs_clarification", "excluded"] = (
            "excluded" if reasons else "needs_clarification" if missing else "eligible"
        )
        rows.append(
            Recommendation(
                evidence_snapshot=candidate.evidence_snapshot,
                candidate_id=candidate.candidate_id,
                grade=candidate.grade,
                group=group,
                score=score,
                components=values,
                reasons=reasons,
                explanations=[]
                if reasons
                else explain(need, candidate, skills, values, missing, algorithm),
                missing_conditions=missing,
                skills=skills if not reasons else {},
                technologies={
                    code: candidate.technologies.get(code, "absent")
                    for code in requested
                }
                if not reasons
                else {},
                assessment_scope=candidate.assessment_scope,
                origin=candidate.origin,
                fsp_origin=candidate.fsp_origin,
            )
        )
    groups = {"eligible": 0, "needs_clarification": 1, "excluded": 2}

    def key(row: Recommendation) -> tuple[object, ...]:
        if row.group == "excluded" or algorithm == "B0":
            return (row.grade, groups[row.group], 0, 0, 0, row.candidate_id)
        return (
            row.grade,
            groups[row.group],
            -row.score,
            -row.components.T if algorithm == "B2" else 0,
            -row.components.K,
            row.candidate_id,
        )

    rows.sort(key=key)
    return Ranking(
        need_id=need.need_id,
        need_version=need.version,
        algorithm=algorithm,
        as_of=as_of,
        recommendations=rows,
    )
