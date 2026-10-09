import argparse
import asyncio
import json
from pathlib import Path

from pydantic import TypeAdapter

from app.assessment.bank_checker import (
    QualityReport,
    ReviewRecord,
    public_summary,
    require_admission,
)
from app.assessment.bank_quality import check_bank
from app.assessment.runner import (
    ExecutionRequest,
    ExecutionResult,
    RunnerClient,
    RunnerUnavailable,
)
from app.core.config import Settings


def prepare_output(output: Path) -> None:
    """Создаёт новую папку отчёта и запрещает перезапись прежних результатов."""
    if output.exists() and any(output.iterdir()):
        raise ValueError("output_directory_not_empty")
    output.mkdir(parents=True, exist_ok=True)


def save_report(output: Path, report: dict[str, object]) -> None:
    """Сохраняет служебные JSON/Markdown-результаты и честный статус проверки."""
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "report.md").write_text(
        f"# Техническая проверка банка\n\n"
        f"Статус: {report['technical_status']}. Проверок: {report['checks']}.\n\n"
        f"Зачётный допуск: {report['admission_status']}.\n\n"
        f"{report.get('admission_reason', '')}\n\n"
        "Сложность и объективность для людей не измерены; "
        "проверка в финальном этапе.\n",
        encoding="utf-8",
    )
    if "versions" in report:
        safe = public_summary(QualityReport.model_validate(report))
        (output / "public-summary.json").write_text(
            json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8"
        )


async def run(
    bank: Path,
    output: Path,
    reviews_path: Path | None = None,
    require_review: bool = False,
) -> int:
    """Запускает техническую проверку банка через реальный отдельный runner."""
    await asyncio.to_thread(prepare_output, output)
    runner: RunnerClient | None = None

    async def unavailable(request: ExecutionRequest) -> ExecutionResult:
        """Отделяет недоступный runner от неверных ответов кандидата."""
        raise RunnerUnavailable("runner_not_configured")

    try:
        runner = RunnerClient(Settings())
    except RunnerUnavailable, OSError:
        execute = unavailable
    else:
        execute = runner.execute
    try:
        report = await check_bank(bank, execute)
        if "versions" in report and report["technical_status"] == "passed":
            full_report = QualityReport.model_validate(report)
            reviews = (
                TypeAdapter(list[ReviewRecord]).validate_json(
                    await asyncio.to_thread(reviews_path.read_bytes)
                )
                if reviews_path is not None
                else []
            )
            try:
                await asyncio.to_thread(
                    require_admission, bank, full_report, reviews=reviews
                )
            except ValueError as error:
                full_report.admission_reason = str(error)
            else:
                full_report.admission_status = "admitted"
                full_report.admission_reason = (
                    "Technical checks and recorded independent review passed"
                )
            report = full_report.model_dump(mode="json")
    except ValueError:
        report = {
            "technical_status": "failed",
            "checks": 0,
            "admission_status": "not_admitted",
            "admission_reason": "invalid_materials_or_review",
            "technical_errors": [],
            "results": [],
        }
    finally:
        if runner is not None:
            await runner.close()
    await asyncio.to_thread(save_report, output, report)
    return (
        0
        if report["technical_status"] == "passed"
        and (not require_review or report["admission_status"] == "admitted")
        else 1
    )


def main() -> None:
    """Создаёт служебный отчёт; незавершённая проверка не считается допуском."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, default=Path("bank/private/full.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--require-admission", action="store_true")
    args = parser.parse_args()
    try:
        code = asyncio.run(
            run(args.bank, args.output, args.reviews, args.require_admission)
        )
    except ValueError, RunnerUnavailable, OSError:
        print("bank_quality: вход или инфраструктура недоступны; допуск не выполнен")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
