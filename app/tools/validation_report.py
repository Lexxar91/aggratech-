"""Воспроизводимое техническое сравнение этапа 7; человеческие проверки отложены."""

import argparse
import hashlib
import json
import platform
from math import ceil, isclose
from pathlib import Path
from time import perf_counter

from pydantic import TypeAdapter

from app.matching.engine import rank
from app.matching.fixtures import candidates_from_fixture
from app.matching.metrics import METRIC_NAMES, measure
from app.matching.schemas import Dataset, Labels, Ranking
from app.tools.matching_check import main as matching_check
from app.tools.matching_check import prepare_output, write_json
from app.validation.calculations import control_aggregates, control_metrics
from app.validation.dataset import VERSION, write_data
from app.validation.experiments import COMPONENTS, ablate
from app.validation.summary import Attempt, HumanRegistry, summarize


def records(value: object) -> list[dict[str, object]]:
    """Проверяет простую границу JSON отчётов, не доверяя структуре файла."""
    if not isinstance(value, list):
        raise ValueError("report_records_required")
    output: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, dict) or not all(isinstance(k, str) for k in row):
            raise ValueError("report_object_required")
        output.append(dict(row))
    return output


def verify_calculations(
    dataset: Dataset,
    rankings: list[Ranking],
    labels: Labels,
    metrics: dict[str, object],
) -> int:
    """Сверяет каждую метрику и средние отдельной реализацией до публикации."""
    expected = control_metrics(dataset, rankings, labels)
    actual = records(metrics["records"])
    if len(actual) != len(expected):
        raise ValueError("metric_record_count")
    checks = 0
    for a, b in zip(actual, expected, strict=True):
        for key, value in b.items():
            result = a[key]
            equal = (
                isclose(value, result, abs_tol=1e-12, rel_tol=1e-12)
                if isinstance(value, (float, int)) and isinstance(result, (float, int))
                else value == result
            )
            if not equal:
                raise ValueError(f"control_metric_mismatch:{key}")
            checks += 1
    for metric in METRIC_NAMES:
        averages = control_aggregates(expected, metric)
        for row in records(metrics["averages_equal_weight_per_need"]):
            value = averages[(str(row["algorithm"]), str(row["group"]))]
            result = row[metric]
            if isinstance(value, (float, int)) and isinstance(result, (float, int)):
                equal = isclose(value, result, rel_tol=1e-12, abs_tol=1e-12)
            else:
                equal = value == result
            if not equal:
                raise ValueError(f"control_average_mismatch:{metric}")
            checks += 1
    control_differences: list[dict[str, object]] = []
    for row in records(metrics["paired_differences"]):
        selected = [
            r
            for r in expected
            if all(r[k] == row[k] for k in ("need_id", "grade", "group"))
        ]
        before = next(r for r in selected if r["algorithm"] == row["baseline"])
        after = next(r for r in selected if r["algorithm"] == "B2")
        difference = {k: row[k] for k in ("need_id", "grade", "group")}
        difference["algorithm"] = row["baseline"]
        for metric in METRIC_NAMES:
            initial_value, final_value = before[metric], after[metric]
            delta = (
                final_value - initial_value
                if isinstance(initial_value, (float, int))
                and isinstance(final_value, (float, int))
                else None
            )
            value = row[metric]
            if not (
                (delta is None and value is None)
                or (
                    isinstance(delta, (float, int))
                    and isinstance(value, (float, int))
                    and isclose(delta, value, rel_tol=1e-12, abs_tol=1e-12)
                )
            ):
                raise ValueError("control_paired_difference_mismatch")
            difference[metric] = delta
            checks += 1
        control_differences.append(difference)
    for metric in METRIC_NAMES:
        expected_differences = control_aggregates(control_differences, metric)
        for row in records(metrics["average_paired_differences_equal_weight_per_need"]):
            expected_value = expected_differences[
                (str(row["baseline"]), str(row["group"]))
            ]
            actual_value = row[metric]
            if not (
                expected_value is None
                and actual_value is None
                or isinstance(expected_value, (int, float))
                and isinstance(actual_value, (int, float))
                and isclose(expected_value, actual_value, rel_tol=1e-12, abs_tol=1e-12)
            ):
                raise ValueError("control_average_difference_mismatch")
            checks += 1
    return checks


def display(value: object) -> str:
    """Неполная разметка и пустой знаменатель не превращаются в нулевой успех."""
    return f"{value:.6f}" if isinstance(value, (float, int)) else "не измерено"


def make_report(output: Path) -> None:
    """Формирует безопасный отчёт, отделяя синтетику и реальные наблюдения."""
    metrics: dict[str, object] = json.loads(
        (output / "synthetic" / "metrics.json").read_bytes()
    )
    experiments: dict[str, object] = json.loads(
        (output / "component_experiments.json").read_bytes()
    )
    summary: dict[str, object] = json.loads(
        (output / "assessment_summary.json").read_bytes()
    )
    lines = [
        "# Контрольные измерения: этап 7",
        "",
        (
            "Только синтетические тестовые данные. Это проверка вычислений, а "
            "не оценка качества для реальных работодателей. Банк "
            "`not_admitted`; fixtures не поступают в продуктовую БД и "
            "подтверждённый подбор."
        ),
        "",
        (
            "Версия: `stage7-synthetic-v1`; seed `20261009`; as_of "
            "`2026-10-09T12:00:00Z`. 120 кандидатов, 12 потребностей, 6 "
            "искусственных работодателей; разработочная часть 40/4, "
            "контрольная 80/8. Баллы случайны независимо от номинального "
            "уровня; task-fit labels заданы искусственными темами, независимо "
            "от Score. Human labels пусты: все показатели человеческого "
            "качества — **не измерено**."
        ),
        "",
        (
            "Весовая формула неизменна: 55T + 25K + 8A + 7F + 5U − P. "
            "Настройка весов по контролю не выполнялась. B0 — фильтры/ID; B1 —"
            " тот же фильтр/стек; B2 — общая продуктовая логика. Группы не "
            "смешиваются; порядок B2 Score → T → K → candidate_id."
        ),
        "",
        (
            "Precision@10: релевантность ≥2, делитель 10 даже для короткой "
            "выдачи. Recall@20: полный размеченный пул релевантных кандидатов "
            "этой категории/группы; пустой знаменатель — не измерено. nDCG@10:"
            " gain 2^rel−1, полный идеальный пул. Среднее: равный вес "
            "потребностей, сначала категорий внутри потребности. Все 640 "
            "контрольных пар размечены только техническим oracle; человеческая"
            " разметка 0/640."
        ),
        "",
        "## Все восемь контрольных потребностей",
        "",
        (
            "| Потребность | Алгоритм | Группа | Выдано | Релевантных в oracle"
            " | P@10 | R@20 | nDCG@10 |"
        ),
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in records(metrics["records"]):
        lines.append(
            "| "
            + " | ".join(
                str(row[k]) if k not in METRIC_NAMES else display(row[k])
                for k in (
                    "need_id",
                    "algorithm",
                    "group",
                    "returned",
                    "relevant_in_oracle",
                    *METRIC_NAMES,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Средние и парные разности",
            "",
            "```json",
            json.dumps(
                {
                    k: metrics[k]
                    for k in (
                        "averages_equal_weight_per_need",
                        "paired_differences",
                        "average_paired_differences_equal_weight_per_need",
                    )
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Вклад компонентов",
            "",
            (
                "Фильтры, группы, вход, as_of и остальные веса фиксированы. Явные "
                "экспериментальные версии, не продуктовая выдача: FSP — F=0; "
                "актуальность — U=0 и P=0; доступность — A=0 (обязательная дата "
                "остаётся фильтром). Баллы пересчитываются до clamp; веса не "
                "нормируются. Сдвиг метрик на синтетических labels не доказывает "
                "пользу компонента человеку."
            ),
            "",
            "```json",
            json.dumps(experiments, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Реальные сохранённые прохождения",
            "",
            str(summary["status"]),
            "",
            "```json",
            json.dumps(summary, ensure_ascii=False, indent=2),
            "```",
            "",
            (
                "Цель пилота: 4 внешних участника × 2 цикла **одного** грейда X/Y."
                " Подтверждённых участников сейчас 0; проверка повторяемости, "
                "ложного подтверждения/отказа, объективности, сложности, атак и "
                "понятности шаблонов/объяснений/сравнения: **не измерено**. "
                "Переход Junior↔Middle — отдельный эксперимент, не повторяемость. "
                "Контакты с добровольцами и человеческие проверки не проводились; "
                "отложены до этапа 9."
            ),
            "",
            "## Ошибки и ограничения",
            "",
            (
                "Независимый контроль — отдельная реализация вычислений, не "
                "независимое человеческое review. В `human-unmeasured` неполная "
                "разметка даёт «не измерено» по всем потребностям. Технические "
                "ошибки assessment не являются ошибками кандидата. Отдельные "
                "результаты диагностики и заметки об условиях не сохраняются: «нет"
                " данных». Реальные ответы и закрытые материалы не экспортируются."
                " Времена в `timings.json` измеряют только вычисление matching на "
                "синтетике, не полный пользовательский путь; изменчивые "
                "duration/timings не входят в сравнение детерминированного "
                "содержимого."
            ),
            "",
            (
                "См. `run_manifest.json` для хешей входов/кода и протокола "
                "проверок; `synthetic` и `human-unmeasured` содержат четыре "
                "стандартных артефакта CLI. Изменение правил, данных, labels или "
                "оценщика требует новой версии и повторного контроля; человеческий"
                " контроль текущей версии ещё не выполнен."
            ),
        ]
    )
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(
    input_dir: Path, attempts_file: Path, registry_file: Path, output: Path
) -> None:
    """Использует существующий автономный CLI и сохраняет реальные измерения времени."""
    prepare_output(output)
    dataset = Dataset.model_validate_json(
        (input_dir / "control.dataset.json").read_bytes()
    )
    for label_kind, directory in (
        ("synthetic", "synthetic"),
        ("human.template", "human-unmeasured"),
    ):
        if (
            matching_check(
                [
                    "--input",
                    str(input_dir / "control.dataset.json"),
                    "--labels",
                    str(input_dir / f"control.labels.{label_kind}.json"),
                    "--output",
                    str(output / directory),
                ]
            )
            != 0
        ):
            raise ValueError("matching_cli_failed")
    rankings_data = json.loads((output / "synthetic" / "rankings.json").read_bytes())
    rankings = TypeAdapter(list[Ranking]).validate_python(rankings_data["rankings"])
    # Labels читаются только после построения общей выдачи.
    labels = Labels.model_validate_json(
        (input_dir / "control.labels.synthetic.json").read_bytes()
    )
    metrics = measure(dataset, rankings, labels)
    checks = verify_calculations(dataset, rankings, labels, metrics)
    experiments: dict[str, object] = {}
    baseline = [r for r in rankings if r.algorithm == "B2"]
    for component in COMPONENTS:
        alternative = [ablate(r, component) for r in baseline]
        experimental_rankings = [
            r for r in rankings if r.algorithm != "B2"
        ] + alternative
        alternative_metrics = measure(dataset, experimental_rankings, labels)
        verify_calculations(dataset, experimental_rankings, labels, alternative_metrics)
        comparisons: list[dict[str, object]] = []
        for before, after in zip(baseline, alternative, strict=True):
            by_id = {r.candidate_id: r for r in before.recommendations}
            comparisons.append(
                {
                    "need_id": before.need_id,
                    "score_changes": sum(
                        r.score != by_id[r.candidate_id].score
                        for r in after.recommendations
                    ),
                    "order_changed": [
                        r.candidate_id
                        for r in before.recommendations
                        if r.group != "excluded"
                    ]
                    != [
                        r.candidate_id
                        for r in after.recommendations
                        if r.group != "excluded"
                    ],
                    "groups_unchanged": all(
                        r.group == by_id[r.candidate_id].group
                        for r in after.recommendations
                    ),
                }
            )
        baseline_rows = records(metrics["records"])
        experimental_rows = [
            r for r in records(alternative_metrics["records"]) if r["algorithm"] == "B2"
        ]
        differences = []
        for result_row in experimental_rows:
            baseline_row = next(
                r
                for r in baseline_rows
                if r["algorithm"] == "B2"
                and all(r[k] == result_row[k] for k in ("need_id", "grade", "group"))
            )
            delta: dict[str, object] = {
                k: result_row[k] for k in ("need_id", "grade", "group")
            }
            for key in METRIC_NAMES:
                a, b = result_row[key], baseline_row[key]
                delta[key] = (
                    a - b
                    if isinstance(a, (int, float)) and isinstance(b, (int, float))
                    else None
                )
            differences.append(delta)
        experiments[f"B2-without-{component}-v1"] = {
            "not_product": True,
            "comparisons": comparisons,
            "metric_records": experimental_rows,
            "differences_vs_B2": differences,
        }
    write_json(output / "component_experiments.json", experiments)
    attempts = TypeAdapter(list[Attempt]).validate_json(attempts_file.read_bytes())
    registry = HumanRegistry.model_validate_json(registry_file.read_bytes())
    summary = summarize(attempts, registry)
    write_json(output / "assessment_summary.json", summary)
    candidates = candidates_from_fixture(dataset)
    methods = frozenset(c.assessment_scope.method_version for c in candidates)
    timings: list[dict[str, object]] = []
    for algorithm in ("B0", "B1", "B2"):
        elapsed = []
        for need in dataset.needs:
            started = perf_counter()
            rank(
                need,
                candidates,
                as_of=dataset.as_of,
                comparable_methods=methods,
                algorithm=algorithm,
            )
            seconds = perf_counter() - started
            elapsed.append(seconds)
            timings.append(
                {"algorithm": algorithm, "need_id": need.need_id, "seconds": seconds}
            )
        elapsed.sort()
        timings.append(
            {
                "algorithm": algorithm,
                "sample_unit": "one_need_matching_calculation",
                "n": len(elapsed),
                "p50_seconds": elapsed[ceil(0.5 * len(elapsed)) - 1],
                "p95_seconds": elapsed[ceil(0.95 * len(elapsed)) - 1],
            }
        )
    write_json(
        output / "timings.json",
        {
            "environment": {
                "python": platform.python_version(),
                "platform": platform.system(),
            },
            "synthetic_only": True,
            "samples": timings,
        },
    )
    root = Path(__file__).resolve().parents[1]
    paths = [
        *sorted((root / "validation").glob("*.py")),
        Path(__file__).resolve(),
        root / "tools" / "assessment_summary.py",
    ]
    write_json(
        output / "run_manifest.json",
        {
            "experiment_version": VERSION,
            "fixed_as_of": dataset.as_of.isoformat(),
            "weights_tuned": False,
            "human_review": "deferred_stage9",
            "bank_admission": "not_admitted",
            "control_metric_checks": checks,
            "source_sha256": {
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(input_dir.glob("*.json"))
            },
            "code_sha256": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in paths
            },
            "attempts_sha256": hashlib.sha256(attempts_file.read_bytes()).hexdigest(),
            "human_registry_sha256": hashlib.sha256(
                registry_file.read_bytes()
            ).hexdigest(),
            "variable_fields": ["timings.json", "*/run_manifest.json:duration_seconds"],
            "human_participants_verified": summary["observed_candidates"],
        },
    )
    make_report(output)


def main(argv: list[str] | None = None) -> int:
    """Работает по файлам без БД, почты, runner и продуктовых записей."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-data", type=Path)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--attempts-input", type=Path)
    parser.add_argument("--human-registry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.write_data:
        if args.input_dir or args.attempts_input or args.human_registry or args.output:
            parser.error("--write-data cannot be combined")
        write_data(args.write_data)
    else:
        if (
            not args.input_dir
            or not args.attempts_input
            or not args.human_registry
            or not args.output
        ):
            parser.error(
                "--input-dir, --attempts-input, --human-registry, --output required"
            )
        run(args.input_dir, args.attempts_input, args.human_registry, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
