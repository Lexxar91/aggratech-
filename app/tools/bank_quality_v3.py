"""Автономная команда полного технического допуска v3 через защищённый runner."""

import argparse
import asyncio
import json
from pathlib import Path

from app.assessment.runner import RunnerClient
from app.assessment.v3_admission import (
    OperatorAcceptance,
    check_bank_v3,
    digest,
    require_admission_v3,
)
from app.core.config import Settings


async def run(bank: Path, output: Path, acceptance: Path) -> int:
    """Сохраняет новый отчёт; не переносит допуск с чужих хешей."""
    await asyncio.to_thread(prepare_output, output)
    runner = RunnerClient(Settings())
    try:
        report = await check_bank_v3(bank, runner.execute_v3)
    finally:
        await runner.close()
    if report.technical_status == "passed":
        record = OperatorAcceptance.model_validate_json(
            await asyncio.to_thread(acceptance.read_bytes)
        )
        report.acceptance_hash = digest(record.model_dump(mode="json"))
        await asyncio.to_thread(require_admission_v3, bank, report, acceptance)
        report.admission_status = "admitted"
    (output / "report.json").write_text(report.model_dump_json(indent=2) + "\n")
    summary = {
        "technical_status": report.technical_status,
        "admission_status": report.admission_status,
        "bank_hash": report.bank_hash,
        "source_hash": report.source_hash,
        "grader_hash": report.grader_hash,
        "cards": 28,
        "checks": report.checks,
        "acceptance": "operator_content_acceptance",
        "independent_review": "not_recorded",
        "human_calibration": "not_measured_by_this_run",
        "technical_errors": report.technical_errors,
    }
    (output / "public-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    (output / "report.md").write_text(
        "# Технический допуск v3\n\n"
        f"Статус: {report.technical_status}. Допуск: {report.admission_status}.\n\n"
        f"Карточек: 28. Проверок: {report.checks}.\n\n"
        "Основание принятия: разрешение оператора на содержимое исходного "
        f"документа с SHA-256 `{report.source_hash}`.\n\n"
        "Этот прогон не измеряет точность оценки, сложность или сопоставимость "
        "на людях. Независимые рецензенты и результаты пилота не выдумываются.\n"
    )
    print(
        f"{report.technical_status}; {report.checks} checks; {report.admission_status}"
    )
    return 0 if report.admission_status == "admitted" else 1


def prepare_output(output: Path) -> None:
    """Защищает предыдущие отчёты от перезаписи."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("output_directory_not_empty")
    output.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """Техническое выполнение всех 28 карточек — обязательное основание допуска."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, default=Path("bank/private/v3.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--acceptance",
        type=Path,
        default=Path("bank/private/v3_operator_acceptance.json"),
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.bank, args.output, args.acceptance)))


if __name__ == "__main__":
    main()
