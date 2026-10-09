"""Допуск материалов без обхода review для зачётного режима."""

import hashlib
from pathlib import Path

from pydantic import TypeAdapter

from app.assessment.bank_checker import QualityReport, ReviewRecord, require_admission
from app.assessment.bank_models import FullBank
from app.core.config import Settings
from app.core.errors import ApiError


def evaluator_hash() -> str:
    """Фиксирует правила результата и реализации оценивания для уже начатого цикла."""
    value = b"".join(
        Path(p).read_bytes()
        for p in (
            "app/assessment/grading.py",
            "app/assessment/policy.py",
            "app/assessment/candidate_tests.py",
            "app/assessment/structured_evaluator.py",
        )
    )
    return hashlib.sha256(value).hexdigest()


def admitted_bank(settings: Settings, mode: str) -> tuple[FullBank, QualityReport]:
    """Демо требует технического отчёта; credit дополнительно требует review банка."""
    try:
        if mode not in ("demo", "credit"):
            raise ValueError("unsupported_mode")
        report = QualityReport.model_validate_json(
            settings.assessment_report.read_bytes()
        )
        if mode == "credit" and report.admission_status != "admitted":
            raise ValueError("credit_admission_not_recorded")
        reviews = (
            TypeAdapter(list[ReviewRecord]).validate_json(
                settings.assessment_reviews.read_bytes()
            )
            if settings.assessment_reviews
            else []
        )
        bank = require_admission(
            settings.assessment_bank,
            report,
            reviews=reviews,
            technical_only=mode == "demo",
        )
    except ValueError, OSError:
        raise ApiError(
            409,
            "bank_not_admitted",
            "Банк не допущен для этого режима; "
            "зачётный допуск ожидает независимого review.",
        ) from None
    return bank, report
