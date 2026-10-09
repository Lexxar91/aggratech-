"""Автономная проверка matching: только JSON, без конфигурации приложения и БД."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from time import perf_counter

from app.matching.catalog import ADAPTER_VERSION, ALGORITHM_VERSION, CATALOG_VERSION
from app.matching.engine import rank
from app.matching.fixtures import (
    InputError,
    candidates_from_fixture,
    example_files,
    load_dataset,
    load_labels,
)
from app.matching.metrics import measure

EXAMPLE_README = """# Автономная проверка matching

Это синтетические fixture-данные и примерная синтетическая разметка, а не
подтверждение квалификации людей. Импорт в продуктовую БД отсутствует.

python -m app.tools.matching_check --input dataset.json --validate-only python -m
app.tools.matching_check --input dataset.json --labels labels.json --output results

Новый набор: сохраняйте все обязательные поля, включая nullable; ID уникальны; баллы
0–100 только самостоятельного режима и одной явно сопоставимой версии jury-
skill-100-v1. Категория fixture_confirmed не вычисляется из грейда. Неизвестные
навыки, технологии, поля, bool вместо чисел и будущие даты подтверждения запрещены.
Для verified технологии требуется соответствующее доказательство; framework не
подтверждает Python. Ограничения: 10 MiB на файл, 1000 кандидатов, 100 потребностей,
100000 пар. Разметка применяется после построения выдачи. При неполной разметке
основные метрики всей потребности not_measured; отсутствующие пары не отрицательные.

Возврат 0: успешный запуск, включая отсутствие/неполноту labels; 2: ошибочный
ввод/аргументы; 1: техническая ошибка. errors.json содержит только поле и код.
Непустая выходная папка никогда не перезаписывается. Четыре успешных артефакта
публикуются целиком: rankings.json, metrics.json, report.md, run_manifest.json.

Порядок B2: отдельно по грейдам и группам, Score → T → K → candidate_id. B0: ID
после фильтров; B1: покрытие стека после тех же фильтров. При отсутствии ФСП F=0,
веса не меняются. Фиксируйте as_of для воспроизводимости."""


def write_json(path: Path, value: object) -> None:
    """Записывает читаемый UTF-8 JSON с запретом нечисел."""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def prepare_output(path: Path) -> None:
    """Разрешает только новую или пустую директорию без перезаписи результатов."""
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise InputError("output", "nonempty_output")
    path.mkdir(parents=True, exist_ok=True)


def code_hashes() -> dict[str, str]:
    """Фиксирует фактические версии вычислительных файлов для воспроизводимости."""
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "matching").glob("*.py")), Path(__file__).resolve()]
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }


def report(metrics: dict[str, object]) -> str:
    """Отчёт явно отделяет fixture-метрики от оценки квалификации людей."""
    return (
        (
            "# Matching check\n\nДанные: внешние fixture, не "
            "реальные подтверждённые профили. Независимая "
            "проверка labels и объективности человеком не "
            "подтверждена.\n\nОсновные метрики: Precision@10 "
            "(делитель 10), Recall@20 (полный oracle-пул), "
            "nDCG@10 (полный идеальный пул); группы и грейды "
            "раздельно. Нет labels или пропущена пара — "
            "not_measured для всей "
            "потребности.\n\n```json\n"
        )
        + json.dumps(metrics, ensure_ascii=False, indent=2)
        + "\n```\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Выполняет контракт CLI; labels загружаются лишь после ранжирования."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-example", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    if args.write_example:
        if args.input or args.output or args.labels or args.validate_only:
            parser.error("--write-example cannot be combined")
    elif not args.input or (not args.validate_only and not args.output):
        parser.error("--input and --output are required (except --validate-only)")
    elif args.validate_only and args.output:
        parser.error("--validate-only does not produce output")
    destination = args.write_example or args.output
    prepared = False
    staging: Path | None = None
    started = perf_counter()
    try:
        if destination:
            prepare_output(destination)
            prepared = True
        if args.write_example:
            for name, value in example_files().items():
                write_json(destination / name, value)
            (destination / "README.md").write_text(EXAMPLE_README, encoding="utf-8")
            return 0
        dataset, dataset_hash = load_dataset(args.input)
        if args.validate_only:
            if args.labels:
                load_labels(args.labels, dataset)
            print("valid: matching-fixture-v1; fixture only")
            return 0
        candidates = candidates_from_fixture(dataset)
        methods = frozenset(c.assessment_scope.method_version for c in candidates)
        rankings = [
            rank(
                need,
                candidates,
                as_of=dataset.as_of,
                comparable_methods=methods,
                algorithm=algorithm,
            )
            for algorithm in ("B0", "B1", "B2")
            for need in dataset.needs
        ]
        # Этот барьер принципиален: разметки ещё нет в памяти во время matching.
        labels, labels_hash = (
            load_labels(args.labels, dataset) if args.labels else (None, None)
        )
        metrics = measure(dataset, rankings, labels)
        manifest = {
            "dataset_id": dataset.dataset_id,
            "dataset_sha256": dataset_hash,
            "labels_sha256": labels_hash,
            "schema_version": dataset.schema_version,
            "labels_schema_version": labels.schema_version if labels else None,
            "schema_hash_mode": "canonical_json_sort_keys_true",
            "algorithm_version": ALGORITHM_VERSION,
            "catalog_version": CATALOG_VERSION,
            "adapter_version": ADAPTER_VERSION,
            "as_of": dataset.as_of.isoformat(),
            "candidates": len(candidates),
            "needs": len(dataset.needs),
            "labels": len(labels.pairs) if labels else 0,
            "duration_seconds": round(perf_counter() - started, 6),
            "code_sha256": code_hashes(),
            "schema_sha256": {
                name: hashlib.sha256(
                    json.dumps(value, sort_keys=True).encode()
                ).hexdigest()
                for name, value in example_files().items()
                if name.endswith("schema.json")
            },
            "fixture_only": True,
            ("admission"): (
                "not applicable; fixture scores are not verified qualifications"
            ),
        }
        staging = Path(tempfile.mkdtemp(prefix=".matching-", dir=destination.parent))
        write_json(
            staging / "rankings.json",
            {
                "fixture_only": True,
                "rankings": [r.model_dump(mode="json") for r in rankings],
            },
        )
        write_json(staging / "metrics.json", metrics)
        write_json(staging / "run_manifest.json", manifest)
        (staging / "report.md").write_text(report(metrics), encoding="utf-8")
        os.replace(staging, destination)
        staging = None
        return 0
    except InputError as error:
        if prepared:
            write_json(destination / "errors.json", {"errors": [error.record()]})
        print(str(error), file=sys.stderr)
        return 2
    except OSError:
        if prepared:
            try:
                write_json(
                    destination / "errors.json",
                    {"errors": [{"field": "$", "code": "io_error"}]},
                )
            except OSError:
                pass
        print("technical error: io_error", file=sys.stderr)
        return 1
    finally:
        if staging is not None:
            shutil.rmtree(staging)


if __name__ == "__main__":
    raise SystemExit(main())
