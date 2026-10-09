"""Служебная сводка из безопасной SQL-проекции существующих сохранённых попыток."""

import argparse
import json
from pathlib import Path

from pydantic import TypeAdapter

from app.tools.matching_check import prepare_output, write_json
from app.validation.summary import Attempt, HumanRegistry, summarize


def main(argv: list[str] | None = None) -> int:
    """Не обращается к инфраструктуре и не публикует идентификаторы участников."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--human-registry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    attempts = TypeAdapter(list[Attempt]).validate_json(args.input.read_bytes())
    registry = HumanRegistry.model_validate_json(args.human_registry.read_bytes())
    result = summarize(attempts, registry)
    prepare_output(args.output)
    write_json(args.output / "summary.json", result)
    (args.output / "summary.md").write_text(
        "# Сводка сохранённых прохождений\n\n"
        + str(result["status"])
        + ". Человеческое происхождение подтверждается отдельным реестром; "
        "demo, seed, fixtures и технические прогоны исключаются.\n\n```json\n"
        + json.dumps(result, ensure_ascii=False, indent=2)
        + "\n```\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
