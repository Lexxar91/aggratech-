"""Закрытые Python-сценарии v3; адаптеры и ожидания хранятся отдельно."""

from pydantic import JsonValue

from app.assessment.v3_models import V3Card, V3Case


def invocation(
    function: str, args: list[JsonValue], *, restart: bool = False
) -> dict[str, JsonValue]:
    return {"function": function, "args": args, "restart": restart}


def adapter(name: str) -> JsonValue:
    return {"$adapter": name}


def byte_input(value: bytes) -> JsonValue:
    return {"$bytes": value.hex()}


def python_cases(card: V3Card, seed: int) -> list[V3Case]:
    """Выбирает заранее определённый генератор семейства, без исполнения решения."""
    if card.family_id in {"X1", "X4", "Y1", "Y4"}:
        from app.assessment.v3_collections_cases import collections_cases

        return collections_cases(card, seed)
    if card.family_id == "X6":
        from app.assessment.v3_payment_cases import payment_cases

        return payment_cases(card, seed)
    from app.assessment.v3_boundary_cases import boundary_cases

    return boundary_cases(card, seed)
