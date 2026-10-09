"""Сводка существующих попыток с явным реестром человеческого происхождения."""

from collections import Counter
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Attempt(BaseModel):
    """Безопасная проекция сохранённой записи; ответов и закрытых рубрик нет."""

    model_config = ConfigDict(extra="forbid")
    cycle_token: str
    subject_token: str
    mode: str
    origin: str
    review_status: str
    fixture_notice: bool = False
    family: str
    item_version: str
    evaluator_version: str
    grade: Literal["junior", "middle"]
    form: Literal["X", "Y"]
    created_at: datetime
    shown: bool
    finalized: bool
    grading_status: str
    technical_intervention: bool = False
    technical_reason: Literal[
        "assessment_infrastructure_unavailable", "worker_recovery_exhausted", "unknown"
    ] = "unknown"
    scores: dict[str, Annotated[int, Field(strict=True, ge=0, le=4)]] = Field(
        default_factory=dict
    )
    base_correct: bool | None = None
    transfer_correct: bool | None = None
    tests_valid: bool | None = None
    mandatory_tests_met: bool | None = None


class HumanRegistry(BaseModel):
    """Подтверждается оператором после пилота; пустой реестр не создаёт людей."""

    model_config = ConfigDict(extra="forbid")
    source: Literal["real_human_pilot"] = "real_human_pilot"
    independently_verified: bool = False
    cycle_tokens: list[str] = Field(default_factory=list)


def summarize(attempts: list[Attempt], registry: HumanRegistry) -> dict[str, object]:
    """Не трактует demo/seed/fixture/технический запуск как наблюдение человека."""
    if registry.cycle_tokens and not registry.independently_verified:
        raise ValueError("human_provenance_not_verified")
    if len({(a.cycle_token, a.family) for a in attempts}) != len(attempts):
        raise ValueError("duplicate_attempt")
    allowlist = set(registry.cycle_tokens)
    real = [
        a
        for a in attempts
        if a.cycle_token in allowlist
        and a.mode == "credit"
        and a.origin == "live_credit"
        and a.review_status == "passed"
        and not a.fixture_notice
    ]
    grouped: dict[tuple[str, str, str, str, str], list[Attempt]] = {}
    for a in real:
        if a.shown:
            grouped.setdefault(
                (a.family, a.item_version, a.evaluator_version, a.grade, a.form), []
            ).append(a)
    rows: list[dict[str, object]] = []
    for key, values in sorted(grouped.items()):
        checked = [a for a in values if a.finalized and a.grading_status == "completed"]
        stages: dict[str, object] = {}
        for name in (
            "base_correct",
            "transfer_correct",
            "tests_valid",
            "mandatory_tests_met",
        ):
            eligible = (
                checked
                if name in ("base_correct", "transfer_correct")
                else [a for a in checked if a.family in ("X4", "Y4")]
            )
            booleans = [
                getattr(a, name) for a in eligible if getattr(a, name) is not None
            ]
            stages[name] = (
                {
                    "checked": len(booleans),
                    "failed": booleans.count(False),
                    "missing": len(eligible) - len(booleans),
                }
                if eligible
                else "нет данных"
            )
        rows.append(
            {
                "family": key[0],
                "item_version": key[1],
                "evaluator_version": key[2],
                "grade": key[3],
                "form": key[4],
                "period": {
                    "from": min(a.created_at for a in values).isoformat(),
                    "to": max(a.created_at for a in values).isoformat(),
                },
                "candidates": len({a.subject_token for a in values}),
                "shown_attempts": len(values),
                "finalized_attempts": sum(a.finalized for a in values),
                "technically_completed": len(checked),
                "requirements_met": sum(
                    bool(a.scores) and all(v >= 3 for v in a.scores.values())
                    for a in checked
                ),
                "technical_errors": sum(
                    a.grading_status == "technical_error" for a in values
                ),
                "technical_reasons": {
                    code: count
                    for code, count in Counter(
                        a.technical_reason
                        for a in values
                        if a.grading_status == "technical_error"
                    ).items()
                },
                "cycles_with_technical_intervention": len(
                    {a.cycle_token for a in values if a.technical_intervention}
                ),
                "recovered_error_history": (
                    "нет данных: отдельная история ошибок не входит в проекцию; "
                    "вмешательства считаются отдельно, без вывода о неуспехе"
                ),
                "diagnosis": (
                    "нет данных: отдельный результат диагностики не сохраняется"
                ),
                "stages": stages,
                "unclear_conditions": "нет данных",
                "analysis_decisions": "нет данных",
            }
        )
    return {
        "status": "observed" if rows else "нет данных",
        "source": "saved_attempts_with_verified_human_registry",
        "observed_candidates": len({a.subject_token for a in real if a.shown}),
        "source_attempts": len(attempts),
        "excluded_attempts": len(attempts) - len(real),
        "excluded_modes": dict(Counter(a.mode for a in attempts if a not in real)),
        "rows": rows,
        "repeatability": "не измерено",
        "false_confirmation": "не измерено",
        "false_failure": "не измерено",
        "interpretation": (
            "Не подтверждает объективность и сопоставимую сложность; "
            "технические ошибки не являются ошибками кандидата."
        ),
    }
