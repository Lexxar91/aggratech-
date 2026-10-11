"""Отдельные основания допуска старого банка и принятого оператором v3."""

from pydantic import TypeAdapter

from app.assessment.bank_checker import (
    QualityReport,
    ReviewRecord,
    grader_hash,
    require_admission,
)
from app.assessment.bank_models import FullBank
from app.assessment.models import AssessmentCycle
from app.assessment.v3_admission import (
    SOURCE_HASH,
    OperatorAcceptance,
    V3QualityReport,
    digest,
    require_admission_v3,
)
from app.assessment.v3_models import V3_METHODOLOGY, V3Bank
from app.core.config import Settings
from app.core.errors import ApiError


def evaluator_hash() -> str:
    """Связывает цикл с полным проверенным оценщиком, runtime и зависимостями."""
    return grader_hash()


def admitted_bank(
    settings: Settings, mode: str
) -> tuple[FullBank, QualityReport] | tuple[V3Bank, V3QualityReport]:
    """Демо требует технического отчёта; credit дополнительно требует review банка."""
    try:
        if mode not in ("demo", "credit"):
            raise ValueError("unsupported_mode")
        if settings.assessment_bank.name == "v3.json":
            v3_report = V3QualityReport.model_validate_json(
                settings.assessment_report.read_bytes()
            )
            if mode == "credit" and v3_report.admission_status != "admitted":
                raise ValueError("credit_admission_not_recorded")
            v3_bank = require_admission_v3(
                settings.assessment_bank,
                v3_report,
                settings.assessment_acceptance,
                technical_only=mode == "demo",
            )
            return v3_bank, v3_report
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
            "Проверка навыков временно недоступна. Попробуйте позже.",
        ) from None
    return bank, report


def credit_admission_valid(cycle: AssessmentCycle) -> bool:
    """Проверяет происхождение сохранённого допуска без переоценивания истории."""
    admission = cycle.admission
    if cycle.mode != "credit" or admission.get("origin") != "live_credit":
        return False
    if cycle.methodology != V3_METHODOLOGY:
        return admission.get("review_passed") is True
    acceptance = admission.get("operator_acceptance")
    if not isinstance(acceptance, dict):
        return False
    try:
        record = OperatorAcceptance.model_validate(acceptance)
    except ValueError:
        return False
    return (
        admission.get("acceptance_type") == "operator_content_acceptance"
        and admission.get("admission_status") == "admitted"
        and admission.get("technical_status") == "passed"
        and admission.get("bank_version") == "3.0"
        and admission.get("bank_hash") == cycle.bank_hash
        and admission.get("grader_hash") == cycle.evaluator_hash
        and record.source_hash == admission.get("source_hash") == SOURCE_HASH
        and admission.get("acceptance_hash") == digest(record.model_dump(mode="json"))
        and isinstance(admission.get("technical_report_hash"), str)
        and len(str(admission["technical_report_hash"])) == 64
    )
