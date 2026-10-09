"""Отдельный контрольный расчёт метрик, без вызова рабочего оценщика."""

from math import fsum, log2

from app.matching.schemas import Dataset, Labels, Ranking


def control_metrics(
    dataset: Dataset, rankings: list[Ranking], labels: Labels
) -> list[dict[str, object]]:
    """Считает полные пулы и знаменатели независимо от app.matching.metrics."""
    lookup = {(p.need_id, p.candidate_id): p for p in labels.pairs}
    output: list[dict[str, object]] = []
    for ranking in rankings:
        need = next(n for n in dataset.needs if n.need_id == ranking.need_id)
        complete = all(
            (need.need_id, c.candidate_id) in lookup for c in dataset.candidates
        )
        for grade in need.accepted_grades:
            for group in ("eligible", "needs_clarification"):
                row: dict[str, object] = {
                    "need_id": need.need_id,
                    "algorithm": ranking.algorithm,
                    "grade": grade,
                    "group": group,
                    "status": "measured" if complete else "not_measured",
                    "precision_at_10": None,
                    "recall_at_20": None,
                    "ndcg_at_10": None,
                    "relevant_in_oracle": None,
                }
                if complete:
                    actual = [
                        r.candidate_id
                        for r in ranking.recommendations
                        if r.grade == grade and r.group == group
                    ]
                    oracle = [
                        lookup[(need.need_id, c.candidate_id)].relevance
                        for c in dataset.candidates
                        if c.grade == grade
                        and lookup[(need.need_id, c.candidate_id)].eligibility == group
                    ]
                    grades = [
                        lookup[(need.need_id, cid)].relevance
                        if lookup[(need.need_id, cid)].eligibility == group
                        else 0
                        for cid in actual
                    ]
                    denominator = len([rel for rel in oracle if rel >= 2])
                    dcg = fsum(
                        (pow(2, rel) - 1) / log2(position)
                        for position, rel in enumerate(grades[:10], start=2)
                    )
                    ideal = fsum(
                        (pow(2, rel) - 1) / log2(position)
                        for position, rel in enumerate(
                            sorted(oracle, reverse=True)[:10], start=2
                        )
                    )
                    row.update(
                        {
                            "precision_at_10": len(
                                [rel for rel in grades[:10] if rel >= 2]
                            )
                            / 10,
                            "recall_at_20": len(
                                [rel for rel in grades[:20] if rel >= 2]
                            )
                            / denominator
                            if denominator
                            else None,
                            "ndcg_at_10": dcg / ideal if ideal else None,
                            "relevant_in_oracle": denominator,
                        }
                    )
                output.append(row)
    return output


def control_aggregates(
    records: list[dict[str, object]], key: str
) -> dict[tuple[str, str], float | None]:
    """Даёт равный вес потребностям, сначала усредняя категории внутри каждой."""
    output: dict[tuple[str, str], float | None] = {}
    for algorithm in ("B0", "B1", "B2"):
        for group in ("eligible", "needs_clarification"):
            needs: dict[str, list[float]] = {}
            for row in records:
                value = row[key]
                if (
                    row["algorithm"] == algorithm
                    and row["group"] == group
                    and isinstance(value, (float, int))
                ):
                    needs.setdefault(str(row["need_id"]), []).append(float(value))
            means = [fsum(values) / len(values) for values in needs.values()]
            output[(algorithm, group)] = fsum(means) / len(means) if means else None
    return output
