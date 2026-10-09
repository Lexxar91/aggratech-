"""Явные экспериментальные отключения компонентов; продуктовые веса неизменны."""

from typing import Literal

from app.matching.schemas import Ranking, Recommendation

Component = Literal["fsp", "freshness", "availability"]
COMPONENTS: tuple[Component, ...] = ("fsp", "freshness", "availability")


def ablate(ranking: Ranking, component: Component) -> Ranking:
    """Пересчитывает до clamp, сохраняя фильтры и группы исходной выдачи B2."""
    if ranking.algorithm != "B2":
        raise ValueError("ablation_requires_B2")
    rows: list[Recommendation] = []
    for row in ranking.recommendations:
        if row.group == "excluded":
            rows.append(row)
            continue
        values = row.components.model_dump()
        if component == "fsp":
            values["F"] = 0
        elif component == "freshness":
            values["U"] = 0
            values["P"] = 0
        else:
            values["A"] = 0
        score = max(
            0,
            min(
                100,
                55 * values["T"]
                + 25 * values["K"]
                + 8 * values["A"]
                + 7 * values["F"]
                + 5 * values["U"]
                - values["P"],
            ),
        )
        rows.append(
            row.model_copy(
                update={
                    "score": round(score, 6),
                    "components": row.components.model_copy(update=values),
                    "explanations": [
                        f"Технический эксперимент B2-without-{component}-v1; "
                        "не продуктовая выдача."
                    ],
                }
            )
        )
    rows.sort(
        key=lambda r: (
            r.grade,
            {"eligible": 0, "needs_clarification": 1, "excluded": 2}[r.group],
            -r.score,
            -r.components.T,
            -r.components.K,
            r.candidate_id,
        )
    )
    return ranking.model_copy(update={"recommendations": rows})
