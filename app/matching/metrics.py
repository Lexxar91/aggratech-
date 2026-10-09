"""Оценка готовой выдачи по внешним labels; разметка не передаётся в matching."""

from math import log2
from statistics import mean

from app.matching.schemas import Dataset, Labels, Ranking

METRIC_NAMES = ("precision_at_10", "recall_at_20", "ndcg_at_10")


def measure(
    dataset: Dataset, rankings: list[Ranking], labels: Labels | None
) -> dict[str, object]:
    """Применяет полный независимый пул, отдельные группы и правила короткой выдачи."""
    pairs = {(p.need_id, p.candidate_id): p for p in labels.pairs} if labels else {}
    candidates = {c.candidate_id: c for c in dataset.candidates}
    records: list[dict[str, object]] = []
    for ranking in rankings:
        need = next(n for n in dataset.needs if n.need_id == ranking.need_id)
        missing = [cid for cid in candidates if (need.need_id, cid) not in pairs]
        complete = not missing and labels is not None
        indexed = {r.candidate_id: r for r in ranking.recommendations}
        mismatches = [
            {
                "candidate_id": cid,
                "expected": pair.eligibility,
                "actual": indexed[cid].group,
            }
            for (nid, cid), pair in pairs.items()
            if nid == need.need_id and indexed[cid].group != pair.eligibility
        ]
        violations = [
            r.candidate_id
            for r in ranking.recommendations
            if r.group != "excluded"
            and (
                not candidates[r.candidate_id].visibility.consent_to_match
                or need.employer_id
                in candidates[r.candidate_id].visibility.blocked_employer_ids
            )
        ]
        for grade in need.accepted_grades:
            for group in ["eligible", "needs_clarification"]:
                rows = [
                    r
                    for r in ranking.recommendations
                    if r.grade == grade and r.group == group
                ]
                values: dict[str, float | None] = {key: None for key in METRIC_NAMES}
                status = "not_measured"
                relevant_total = 0
                fraction: float | None = None
                if complete:
                    oracle = [
                        p
                        for (nid, cid), p in pairs.items()
                        if nid == need.need_id
                        and p.eligibility == group
                        and candidates[cid].grade == grade
                    ]
                    relevant_total = sum(p.relevance >= 2 for p in oracle)
                    gains = [
                        pairs[(need.need_id, r.candidate_id)].relevance
                        if pairs[(need.need_id, r.candidate_id)].eligibility == group
                        else 0
                        for r in rows
                    ]

                    def relevant(limit: int, values: list[int] = gains) -> int:
                        return sum(x >= 2 for x in values[:limit])

                    ideal = sorted((p.relevance for p in oracle), reverse=True)[:10]
                    idcg = sum(
                        (2**rel - 1) / log2(pos + 2) for pos, rel in enumerate(ideal)
                    )
                    dcg = sum(
                        (2**rel - 1) / log2(pos + 2)
                        for pos, rel in enumerate(gains[:10])
                    )
                    values = {
                        "precision_at_10": relevant(10) / 10,
                        "recall_at_20": relevant(20) / relevant_total
                        if relevant_total
                        else None,
                        "ndcg_at_10": dcg / idcg if idcg else None,
                    }
                    fraction = relevant(len(rows)) / len(rows) if rows else None
                    status = "measured"
                records.append(
                    {
                        "need_id": need.need_id,
                        "grade": grade,
                        "group": group,
                        "algorithm": ranking.algorithm,
                        "status": status,
                        **values,
                        "returned": len(rows),
                        "relevant_in_oracle": relevant_total if complete else None,
                        "relevant_fraction_of_returned": fraction,
                        "missing_pairs": missing,
                        "eligibility_errors": mismatches,
                        "privacy_violations": violations,
                    }
                )
    averages: list[dict[str, object]] = []
    for algorithm in ["B0", "B1", "B2"]:
        for group in ["eligible", "needs_clarification"]:
            result: dict[str, object] = {"algorithm": algorithm, "group": group}
            for metric in METRIC_NAMES:
                per_need: list[float] = []
                for need in dataset.needs:
                    measured = [
                        float(value)
                        for r in records
                        for value in [r[metric]]
                        if r["need_id"] == need.need_id
                        and r["algorithm"] == algorithm
                        and r["group"] == group
                        and isinstance(value, (int, float))
                    ]
                    if measured:
                        per_need.append(mean(measured))
                result[metric] = mean(per_need) if per_need else None
            averages.append(result)
    deltas: list[dict[str, object]] = []
    for row in records:
        if row["algorithm"] != "B2":
            continue
        for baseline in ["B0", "B1"]:
            before = next(
                r
                for r in records
                if r["need_id"] == row["need_id"]
                and r["grade"] == row["grade"]
                and r["group"] == row["group"]
                and r["algorithm"] == baseline
            )
            differences: dict[str, float | None] = {}
            for key in METRIC_NAMES:
                a, b = row[key], before[key]
                differences[key] = (
                    float(a) - float(b)
                    if isinstance(a, (int, float)) and isinstance(b, (int, float))
                    else None
                )
            deltas.append(
                {
                    "need_id": row["need_id"],
                    "grade": row["grade"],
                    "group": row["group"],
                    "baseline": baseline,
                    **differences,
                }
            )
    average_deltas: list[dict[str, object]] = []
    for baseline in ["B0", "B1"]:
        for group in ["eligible", "needs_clarification"]:
            average: dict[str, object] = {"baseline": baseline, "group": group}
            for metric in METRIC_NAMES:
                by_need: list[float] = []
                for need in dataset.needs:
                    category_deltas = [
                        float(value)
                        for r in deltas
                        for value in [r[metric]]
                        if r["need_id"] == need.need_id
                        and r["baseline"] == baseline
                        and r["group"] == group
                        and isinstance(value, (float, int))
                    ]
                    if category_deltas:
                        by_need.append(mean(category_deltas))
                average[metric] = mean(by_need) if by_need else None
            average_deltas.append(average)
    return {
        "label_source": "caller_provided; independent human review not verified",
        "fixture_only": True,
        "records": records,
        "averages_equal_weight_per_need": averages,
        "paired_differences": deltas,
        "average_paired_differences_equal_weight_per_need": average_deltas,
    }
