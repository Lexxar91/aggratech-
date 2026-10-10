"""Общие строители закрытых сценариев v3 с отдельными наблюдениями навыков."""

from typing import Literal

from pydantic import JsonValue, TypeAdapter

from app.assessment.bank_models import Skill
from app.assessment.v3_models import V3Assertion, V3Card, V3Case

Pack = Literal["A", "B", "C", "D"]
JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class CaseBuilder:
    """Каждый признак имеет требование, навык, пакет и воспроизводимый seed."""

    def __init__(self, card: V3Card, seed: int) -> None:
        self.card, self.seed = card, seed
        self.cases: list[V3Case] = []

    def assertion(
        self,
        skill: Skill,
        path: list[str],
        expected: object,
        *,
        comparison: Literal[
            "exact",
            "unordered",
            "minimum",
            "maximum",
            "count",
            "contains",
            "excludes",
            "one_of",
        ] = "exact",
        critical: str | None = None,
    ) -> V3Assertion:
        requirement = next(r for r in self.card.requirements if r.skill == skill)
        return V3Assertion(
            path=path,
            expected=JSON_VALUE.validate_python(expected),
            requirement_id=requirement.id,
            skill=skill,
            comparison=comparison,
            critical=critical,
        )

    def add(
        self,
        pack: Pack,
        name: str,
        scenario: dict[str, JsonValue],
        assertions: list[V3Assertion],
        *,
        transfer: bool | None = None,
    ) -> None:
        phase: Literal["base", "transfer"] = (
            "transfer"
            if (pack in ("C", "D") if transfer is None else transfer)
            else "base"
        )
        self.cases.append(
            V3Case(
                id=f"{self.card.task_id}-{pack}-{name}-{self.seed}",
                pack=pack,
                phase=phase,
                seed=self.seed,
                scenario=scenario,
                assertions=assertions,
            )
        )


def cases_for(card: V3Card, seed: int) -> list[V3Case]:
    """Runtime выбирает сохранённый seed; LLM и случайные требования отсутствуют."""
    if seed not in card.seeds:
        raise ValueError("v3_seed_not_declared")
    if card.cases:
        selected = [case for case in card.cases if case.seed == seed]
        if not selected:
            raise ValueError("v3_frozen_seed_missing")
        return selected
    if card.language == "sql":
        from app.assessment.v3_sql_cases import sql_cases

        return sql_cases(card, seed)
    from app.assessment.v3_python_cases import python_cases

    return python_cases(card, seed)
