import argparse
import asyncio
import json
from pathlib import Path

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
        f"# Техническая проверка первых двух семейств\n\n"
        f"Статус: {report['technical_status']}. Проверок: {report['checks']}.\n\n"
        "Полный банк не допущен. Сложность для людей не измерена.\n",
        encoding="utf-8",
    )


async def run(bank: Path, output: Path) -> int:
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
    finally:
        if runner is not None:
            await runner.close()
    await asyncio.to_thread(save_report, output, report)
    return 0 if report["technical_status"] == "passed" else 1


def main() -> None:
    """Создаёт служебный отчёт; незавершённая проверка не считается допуском."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, default=Path("bank/private/stage1.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        code = asyncio.run(run(args.bank, args.output))
    except ValueError, RunnerUnavailable, OSError:
        print("bank_quality: вход или инфраструктура недоступны; допуск не выполнен")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
