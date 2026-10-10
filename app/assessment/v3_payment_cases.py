"""Платежи: атомарные адаптеры, сохранённые идентификаторы и управляемые сбои."""

from pydantic import JsonValue

from app.assessment.v3_cases import CaseBuilder, Pack
from app.assessment.v3_models import V3Card, V3Case
from app.assessment.v3_python_cases import adapter, invocation


def payment_cases(card: V3Card, seed: int) -> list[V3Case]:
    """Повторное списание фиксируется отдельно от итогового task_score."""
    b = CaseBuilder(card, seed)
    account, amount, key = seed % 1000 + 1, seed % 13 + 100, f"key-{seed}"
    middle = card.grade == "middle"
    if not middle:

        def payment(
            pack: Pack,
            name: str,
            requests: list[tuple[int, str, int]],
            returns: list[JsonValue],
            count: int,
            *,
            parallel: bool = False,
            amounts: list[JsonValue] | None = None,
        ) -> None:
            invocations: list[JsonValue] = [
                invocation("create_payment", [a, k, value, adapter("ledger")])
                for a, k, value in requests
            ]
            checks = [
                b.assertion(
                    "http_api",
                    ["return_values"],
                    returns,
                    comparison="unordered" if parallel else "exact",
                ),
                b.assertion(
                    "debug_reliability",
                    ["observed", "payments"],
                    count,
                    comparison="count",
                ),
            ]
            checks.append(
                b.assertion(
                    "debug_reliability",
                    ["observed", "payment_count"],
                    count,
                    comparison="maximum",
                    critical="double_debit",
                )
            )
            unique: list[tuple[int, str]] = []
            for a, k, _ in requests:
                if (a, k) not in unique:
                    unique.append((a, k))
            for i, (a, k) in enumerate(unique):
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "payments", str(i), "scope"],
                        [a, "payments", k],
                    )
                )
            if amounts:
                checks.append(
                    b.assertion(
                        "debug_reliability",
                        ["observed", "payments", "0", "amount"],
                        amounts,
                        comparison="one_of",
                    )
                )
            scenario: dict[str, JsonValue] = {
                "adapters": {"ledger": {"kind": "ledger"}},
                "invocations": invocations,
                "parallel": parallel,
            }
            if parallel:
                scenario["barrier"] = "ledger.create_once"
            b.add(pack, name, scenario, checks)

        created: JsonValue = {"status": 201, "payment_id": 1}
        created_two: JsonValue = {"status": 201, "payment_id": 2}
        conflict: JsonValue = {"status": 409, "payment_id": None}
        payment("A", "new", [(account, key, amount)], [created], 1)
        payment(
            "A",
            "two-new-keys",
            [(account, key, amount), (account, "other", amount)],
            [created, created_two],
            2,
        )
        payment("B", "same", [(account, key, amount)] * 2, [created, created], 1)
        payment(
            "B",
            "conflict",
            [(account, key, amount), (account, key, amount + 1)],
            [created, conflict],
            1,
        )
        payment(
            "B",
            "account-scope",
            [(account, key, amount), (account + 1, key, amount)],
            [created, created_two],
            2,
        )
        payment(
            "C",
            "same-concurrent",
            [(account, key, amount)] * 2,
            [created, created],
            1,
            parallel=True,
        )
        payment(
            "D",
            "amount-conflict-concurrent",
            [(account, key, amount), (account, key, amount + 1)],
            [created, conflict],
            1,
            parallel=True,
            amounts=[amount, amount + 1],
        )
        payment(
            "D",
            "repeat-after-other-payments",
            [
                (account, key, amount),
                (account, "other", amount),
                (account, "third", amount),
                (account, key, amount),
            ],
            [created, created_two, {"status": 201, "payment_id": 3}, created],
            3,
        )
        payment(
            "D",
            "same-key-new-account",
            [(account, key, amount), (account + 1, key, amount + 1)],
            [created, created_two],
            2,
        )
    else:
        pending: JsonValue = {"status": 202, "payment_id": None}
        done: JsonValue = {"status": 201, "payment_id": 101}
        conflict = {"status": 409, "payment_id": None}

        def submit(a: int = account, k: str = key, value: int = amount) -> JsonValue:
            return invocation("submit_payment", [a, k, value, adapter("repo")])

        def deliver(operation: str = "op-1", *, restart: bool = False) -> JsonValue:
            return invocation(
                "deliver_payment",
                [operation, adapter("repo"), adapter("provider")],
                restart=restart,
            )

        def sequence(
            pack: Pack,
            name: str,
            invocations: list[JsonValue],
            returns: list[JsonValue],
            *,
            operations: int = 1,
            charges: int = 0,
            completed: bool = False,
            provider_timeout: bool = False,
            crash_complete: bool = False,
            prepare: bool = False,
            parallel: bool = False,
            provider_calls: int | None = None,
            error: str | None = None,
            scopes: list[JsonValue] | None = None,
        ) -> None:
            scenario: dict[str, JsonValue] = {
                "adapters": {
                    "repo": {
                        "kind": "payment_repo",
                        "crash_before_complete": crash_complete,
                    },
                    "provider": {
                        "kind": "provider",
                        "timeout_after_charge": provider_timeout,
                    },
                },
                "invocations": invocations,
                "parallel": parallel,
            }
            if prepare:
                scenario["preparation"] = [
                    {
                        "target": "repo",
                        "method": "reserve",
                        "args": [[account, "payments", key], amount],
                    }
                ]
            if parallel:
                scenario["barrier"] = "repo.get"
            checks = [
                b.assertion(
                    "http_api",
                    ["return_values"],
                    returns,
                    comparison="unordered" if parallel else "exact",
                ),
                b.assertion(
                    "debug_reliability",
                    ["observed", "operations"],
                    operations,
                    comparison="count",
                ),
                b.assertion("debug_reliability", ["observed", "charges"], charges),
                b.assertion(
                    "debug_reliability",
                    ["observed", "charges"],
                    charges,
                    comparison="maximum",
                    critical="double_debit",
                ),
            ]
            if not prepare:
                default_scope: JsonValue = [account, "payments", key]
                for i, scope in enumerate(scopes or [default_scope]):
                    checks.append(
                        b.assertion(
                            "security_validation",
                            ["observed", "operations", str(i), "scope"],
                            scope,
                        )
                    )
            if completed:
                checks += [
                    b.assertion(
                        "debug_reliability",
                        ["observed", "operations", "0", "state"],
                        "done",
                    ),
                    b.assertion(
                        "debug_reliability",
                        ["observed", "operations", "0", "payment_id"],
                        101,
                    ),
                    b.assertion(
                        "debug_reliability",
                        ["observed", "operations", "0", "outbox_done"],
                        True,
                    ),
                ]
            if provider_calls is not None:
                checks.append(
                    b.assertion(
                        "debug_reliability",
                        ["observed", "provider_calls"],
                        provider_calls,
                        comparison="count",
                    )
                )
            if error:
                checks.append(
                    b.assertion("debug_reliability", ["results", "0", "error"], error)
                )
            b.add(pack, name, scenario, checks)

        sequence(
            "A",
            "submit-deliver",
            [submit(), deliver()],
            [pending, done],
            charges=1,
            completed=True,
        )
        sequence(
            "A",
            "two-independent",
            [submit(), submit(k="other")],
            [pending, pending],
            operations=2,
            scopes=[[account, "payments", key], [account, "payments", "other"]],
        )
        sequence("B", "same", [submit(), submit()], [pending, pending])
        sequence(
            "B", "conflict", [submit(), submit(value=amount + 1)], [pending, conflict]
        )
        sequence(
            "B",
            "account-scope",
            [submit(), submit(a=account + 1)],
            [pending, pending],
            operations=2,
            scopes=[[account, "payments", key], [account + 1, "payments", key]],
        )
        sequence(
            "B",
            "done-no-provider-call",
            [submit(), deliver(), deliver()],
            [pending, done, done],
            charges=1,
            completed=True,
            provider_calls=1,
        )
        sequence(
            "C",
            "charged-timeout-restart",
            [submit(), deliver(), deliver(restart=True)],
            [pending, pending, done],
            charges=1,
            completed=True,
            provider_timeout=True,
            provider_calls=2,
        )
        sequence(
            "D",
            "crash-before-complete",
            [deliver(), deliver(restart=True)],
            [None, done],
            charges=1,
            completed=True,
            prepare=True,
            crash_complete=True,
            error="RuntimeError",
        )
        sequence(
            "D",
            "two-workers",
            [deliver(), deliver()],
            [done, done],
            charges=1,
            completed=True,
            prepare=True,
            parallel=True,
        )
        sequence(
            "D",
            "scope-after-restart",
            [submit(), submit(a=account + 1)],
            [pending, pending],
            operations=2,
            scopes=[[account, "payments", key], [account + 1, "payments", key]],
        )
        sequence(
            "D",
            "all-success-same-id",
            [submit(), deliver(), submit(), deliver()],
            [pending, done, done, done],
            charges=1,
            completed=True,
            provider_calls=1,
        )
    return b.cases
