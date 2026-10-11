"""Фиксированные пороги, независимые семейства и календарные ограничения 02."""

from datetime import datetime, timedelta

from app.core.errors import ApiError

WEIGHTS = {
    "junior": {
        "language_algorithms": 20,
        "sql_data": 30,
        "http_api": 20,
        "debug_reliability": 20,
        "security_validation": 10,
    },
    "middle": {
        "language_algorithms": 10,
        "sql_data": 20,
        "http_api": 20,
        "debug_reliability": 30,
        "security_validation": 20,
    },
}
CRITICAL = {"sql_data", "http_api"}
METHODOLOGY = "backend-assessment-v1"


def decide(
    grade: str,
    evidence: dict[str, dict[str, int]],
    *,
    b_completed: bool,
    review_required: bool = False,
) -> tuple[str, float | None, list[dict[str, object]]]:
    """Считает семейство один раз и не компенсирует критический провал общей суммой."""
    details: list[dict[str, object]] = []
    sufficient, passed, total = b_completed, True, 0.0
    for skill, weight in WEIGHTS[grade].items():
        values = [scores[skill] for scores in evidence.values() if skill in scores]
        if any(type(v) is not int or not 0 <= v <= 4 for v in values):
            raise ValueError("invalid_skill_evidence")
        enough = len(values) >= (3 if skill in CRITICAL else 2)
        if skill in CRITICAL:
            enough = enough and any(
                family in {"X5", "X6", "Y5", "Y6"} and skill in scores
                for family, scores in evidence.items()
            )
        ok = enough and (
            min(values) >= 3
            if skill in CRITICAL
            else min(values) >= 2 and max(values) >= 3
        )
        score = round(sum(values) / len(values) * 25, 2) if values else None
        sufficient = sufficient and enough
        passed = passed and ok
        total += (score or 0) * weight / 100
        details.append(
            {
                "skill": skill,
                "families": len(values),
                "score": score,
                "status": "met" if ok else ("not_met" if enough else "not_checked"),
            }
        )
    outcome = "confirmed" if passed else "not_confirmed"
    if not sufficient:
        outcome = "insufficient"
    if review_required:
        outcome = "review_required"
    return outcome, round(total, 2) if evidence else None, details


def check_calendar(
    now: datetime,
    *,
    grade: str,
    completed: list[tuple[str, datetime, bool]],
    published_grade: str | None,
    published_at: datetime | None,
) -> None:
    """Проверяет 7/30 суток; соседний грейд до первой публикации не ждёт неделю."""
    eligible = [(g, t) for g, t, exempt in completed if not exempt]
    if sum(t > now - timedelta(days=30) for _, t in eligible) >= 2:
        raise ApiError(
            409, "cycle_window_limit", "Не более двух завершённых циклов за 30 дней."
        )
    if (
        published_at is not None
        and grade != published_grade
        and now < published_at + timedelta(days=30)
    ):
        raise ApiError(
            409,
            "grade_cooldown",
            "Смена опубликованного уровня доступна через 30 дней.",
        )
    same_grade = [t for g, t in eligible if g == grade]
    if same_grade and now < max(same_grade) + timedelta(days=7):
        raise ApiError(
            409, "retry_cooldown", "Повтор этого уровня доступен через 7 дней."
        )
