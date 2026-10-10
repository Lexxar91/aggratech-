"""Собирает полную исполняемую поставку v3; технический допуск выполняется отдельно."""

import argparse
import hashlib
import json
from pathlib import Path

from app.assessment.runner import POSTGRES_IMAGE, PYTHON_IMAGE
from app.assessment.v3_cases import cases_for
from app.assessment.v3_models import V3Bank
from app.assessment.v3_solutions import partial_solution, prepared_solutions


def prepare(bank_path: Path) -> V3Bank:
    """Фикстуры всех seeds сохраняются, runtime не меняет требования генерацией."""
    bank = V3Bank.model_validate_json(bank_path.read_bytes())
    for card in bank.cards:
        # При повторной сборке берётся человеческий reference, не старые мутанты.
        card.solutions = [
            next(
                solution for solution in card.solutions if solution.kind == "reference"
            )
        ]
        card.cases = []
        card.parameter_manifests = []
        fixtures = []
        partials = []
        for seed in card.seeds:
            cases = cases_for(card, seed)
            fixtures.extend(cases)
            partials.append(partial_solution(card, cases, seed))
            payload = json.dumps(
                [case.model_dump(mode="json") for case in cases],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            card.parameter_manifests.append(
                {
                    "bank_version": bank.bank_version,
                    "task_id": card.task_id,
                    "family_id": card.family_id,
                    "target_level": card.grade,
                    "rule_version": card.rule_version,
                    "seed": seed,
                    "fixture_hash": hashlib.sha256(payload).hexdigest(),
                    "oracle_version": card.oracle_version,
                    "test_pack_version": card.test_pack_version,
                    "runtime_image": PYTHON_IMAGE
                    if card.language == "python"
                    else POSTGRES_IMAGE,
                }
            )
        card.cases = fixtures
        card.solutions = prepared_solutions(card) + partials
    bank_path.write_text(
        json.dumps(bank.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    )
    return bank


def main() -> None:
    """Сборка банка не выставляет admission_status и не выполняет фиктивное review."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, default=Path("bank/private/v3.json"))
    args = parser.parse_args()
    bank = prepare(args.bank)
    print(f"Prepared {len(bank.cards)} cards; technical admission not yet run")


if __name__ == "__main__":
    main()
