"""Все SQL-карточки v3: отдельные входы, oracle и управляемые транзакции."""

import random
from itertools import permutations

from pydantic import JsonValue

from app.assessment.v3_cases import CaseBuilder, Pack
from app.assessment.v3_models import V3Card, V3Case


def fixture_row(value: JsonValue) -> list[JsonValue]:
    """Некорректная закрытая фикстура — ошибка задания, не ошибка кандидата."""
    if not isinstance(value, list):
        raise ValueError("invalid_sql_fixture_row")
    return value


def fixture_integer(value: JsonValue) -> int:
    if type(value) is not int:
        raise ValueError("invalid_sql_fixture_integer")
    return value


def sql_cases(card: V3Card, seed: int) -> list[V3Case]:
    """Обязательные диагностические ситуации сохраняются на каждом seed."""
    b = CaseBuilder(card, seed)
    rng = random.Random(seed)
    n, amount = seed % 1000 * 10, 100 + seed % 13
    middle = card.grade == "middle"

    def select(
        pack: Pack,
        name: str,
        tables: dict[str, JsonValue],
        params: dict[str, JsonValue],
        rows: list[JsonValue],
        columns: list[str],
        *,
        debug_field: str | None = None,
        forbidden: list[JsonValue] | None = None,
    ) -> None:
        numeric = ["smallint", "integer", "bigint", "numeric"]
        checks = [
            b.assertion("sql_data", ["rows"], rows),
            b.assertion("sql_data", ["columns"], list(columns)),
        ]
        for i, column in enumerate(columns):
            checks.append(
                b.assertion(
                    "sql_data",
                    ["types", str(i)],
                    ["text"] if column in {"team", "key", "value"} else numeric,
                    comparison="one_of",
                )
            )
        if any(r.skill == "debug_reliability" for r in card.requirements):
            if rows and debug_field:
                first = rows[0]
                if not isinstance(first, dict):
                    raise ValueError("invalid_expected_sql_row")
                checks.append(
                    b.assertion(
                        "debug_reliability",
                        ["rows", "0", debug_field],
                        first[debug_field],
                    )
                )
            else:
                checks.append(
                    b.assertion(
                        "debug_reliability", ["rows"], len(rows), comparison="count"
                    )
                )
        if forbidden:
            checks.append(
                b.assertion(
                    "sql_data",
                    ["rows"],
                    forbidden,
                    comparison="excludes",
                    critical="foreign_data",
                )
            )
        b.add(pack, name, {"tables": tables, "params": params}, checks)

    if card.family_id == "X1":
        if not middle:

            def x1(
                pack: Pack, name: str, payments: list[JsonValue], paid: bool
            ) -> None:
                totals: dict[str, int] = {}
                for value in payments:
                    if not isinstance(value, list):
                        raise ValueError("bad_fixture")
                    team, value_amount, status = value
                    if paid and status != "paid":
                        continue
                    if not isinstance(team, str):
                        raise ValueError("bad_fixture")
                    totals.setdefault(team, 0)
                    if isinstance(value_amount, int):
                        totals[team] += value_amount
                rows: list[JsonValue] = [
                    {"team": key, "total": totals[key]} for key in sorted(totals)
                ]
                select(
                    pack,
                    name,
                    {"payments": payments},
                    {"paid_only": paid},
                    rows,
                    ["team", "total"],
                )

            x1("A", "one-team", [["A", 2, "paid"], ["A", 3, "paid"]], False)
            x1("A", "two-teams", [["B", amount, "paid"], ["A", 1, "paid"]], False)
            x1("B", "empty", [], False)
            x1("B", "null", [["A", None, "paid"]], False)
            x1("B", "negative", [["A", -amount, "paid"]], True)
            x1("B", "paid-false", [["A", 1, "paid"], ["A", 7, "cancelled"]], False)
            x1("B", "paid-true", [["A", 1, "paid"], ["A", 7, "cancelled"]], True)
            x1(
                "C",
                "filter-before-groups",
                [["A", amount, "cancelled"], ["B", None, "paid"]],
                True,
            )
            mix: list[JsonValue] = [
                ["A", None, "paid"],
                ["B", None, "paid"],
                ["A", -amount, "paid"],
                ["A", amount, "cancelled"],
                ["B", None, "cancelled"],
            ]
            for i in range(3):
                rng.shuffle(mix)
                x1("D", f"permutation-{i}", list(mix), bool(i % 2))
        else:

            def latest(
                pack: Pack, name: str, revisions: list[JsonValue], paid: bool
            ) -> None:
                selected: dict[int, list[JsonValue]] = {}
                for value in revisions:
                    if not isinstance(value, list) or not isinstance(value[1], int):
                        raise ValueError("bad_fixture")
                    old = selected.get(value[1])
                    if old is None or (value[2], value[3]) > (old[2], old[3]):
                        selected[value[1]] = value
                sums: dict[str, int] = {}
                for row in selected.values():
                    team = row[0]
                    if not isinstance(team, str) or (paid and row[5] != "paid"):
                        continue
                    sums.setdefault(team, 0)
                    if isinstance(row[4], int):
                        sums[team] += row[4]
                rows: list[JsonValue] = [
                    {"team": key, "total": sums[key]} for key in sorted(sums)
                ]
                select(
                    pack,
                    name,
                    {"revisions": revisions},
                    {"paid_only": paid},
                    rows,
                    ["team", "total"],
                )

            latest("A", "one-version", [["A", n + 1, 1, 1, amount, "paid"]], False)
            latest(
                "A",
                "latest-revision",
                [
                    ["A", n + 1, 1, 1, amount, "paid"],
                    ["B", n + 1, 2, 1, 20, "paid"],
                    ["A", n + 2, 1, 1, 30, "paid"],
                ],
                False,
            )
            latest(
                "B",
                "revision-id-tie",
                [["A", n + 1, 1, 1, 30, "paid"], ["B", n + 1, 1, 2, amount, "paid"]],
                False,
            )
            latest("B", "null", [["A", n + 1, 1, 1, None, "paid"]], True)
            latest("B", "empty", [], False)
            changed: list[JsonValue] = [
                ["A", n + 1, 1, 1, amount, "paid"],
                ["B", n + 1, 2, 1, 20, "cancelled"],
            ]
            latest("B", "filter-after-version", changed, True)
            latest("C", "move-team", changed, False)
            latest("C", "move-status", changed, True)
            mix = changed + [
                ["A", n + 2, 1, 1, -amount, "paid"],
                ["A", n + 2, 1, 2, None, "paid"],
            ]
            for i in range(3):
                rng.shuffle(mix)
                latest("D", f"permutation-{i}", list(mix), bool(i % 2))

    elif card.family_id == "X3":

        def orders(
            pack: Pack,
            name: str,
            orders_rows: list[JsonValue],
            lines: list[JsonValue],
            many: list[JsonValue],
        ) -> None:
            tables: dict[str, JsonValue] = {
                "orders": orders_rows,
                "order_lines": lines,
                "refunds" if middle else "discounts": many,
            }
            rows: list[JsonValue] = []
            if middle:
                groups: dict[int, list[int]] = {}
                for row in orders_rows:
                    if not isinstance(row, list) or not all(
                        isinstance(x, int) for x in row
                    ):
                        raise ValueError("bad_fixture")
                    order_id, customer_id, total = row
                    if not isinstance(customer_id, int) or not isinstance(total, int):
                        raise ValueError("bad_fixture")
                    group = groups.setdefault(customer_id, [0, 0, 0])
                    group[0] += 1
                    group[1] += total
                    group[2] += sum(
                        int(r[2])
                        for r in many
                        if isinstance(r, list)
                        and r[1] == order_id
                        and isinstance(r[2], int)
                    )
                rows = [
                    {
                        "customer_id": key,
                        "order_count": groups[key][0],
                        "gross_total": groups[key][1],
                        "refund_total": groups[key][2],
                    }
                    for key in sorted(groups)
                ]
                columns = ["customer_id", "order_count", "gross_total", "refund_total"]
                debug_field = "gross_total"
            else:
                for row in sorted(
                    orders_rows, key=lambda r: fixture_integer(fixture_row(r)[0])
                ):
                    if not isinstance(row, list):
                        raise ValueError("bad_fixture")
                    rows.append(
                        {
                            "order_id": row[0],
                            "total_amount": row[2],
                            "line_count": sum(
                                1
                                for line in lines
                                if isinstance(line, list) and line[1] == row[0]
                            ),
                        }
                    )
                columns = ["order_id", "total_amount", "line_count"]
                debug_field = "line_count"
            select(pack, name, tables, {}, rows, columns, debug_field=debug_field)

        orders(
            "A",
            "one-order",
            [[n + 1, 1, amount]],
            [[1, n + 1, 1], [2, n + 1, 1]],
            [[1, n + 1, 10], [2, n + 1, 20]] if middle else [],
        )
        orders(
            "A",
            "two-clients",
            [[n + 1, 1, amount], [n + 2, 2, 50]],
            [[1, n + 1, 1], [2, n + 2, 1]],
            [],
        )
        orders("B", "no-links", [[n + 1, 1, amount]], [], [])
        orders("B", "empty", [], [], [])
        orders(
            "B",
            "quantity-or-same-amount",
            [[n + 1, 1, amount], [n + 2, 1, amount]],
            [[1, n + 1, 5]],
            [],
        )
        orders(
            "C",
            "independent-links",
            [[n + 1, 1, amount], [n + 2, 1, 50]],
            [[1, n + 1, 1], [2, n + 1, 2]],
            [[1, n + 1, 10], [2, n + 1, 20]],
        )
        for i in range(3):
            order_rows: list[JsonValue] = [
                [n + 1, 1, amount],
                [n + 2, 1, amount],
                [n + 3, 2, 0],
            ]
            line_rows: list[JsonValue] = [[1, n + 1, 5], [2, n + 1, 0], [3, n + 2, -1]]
            many_rows: list[JsonValue] = [
                [1, n + 1, -10],
                [2, n + 1, 20],
                [3, n + 2, 0],
            ]
            rng.shuffle(order_rows)
            rng.shuffle(line_rows)
            rng.shuffle(many_rows)
            orders("D", f"multiplicity-{i}", order_rows, line_rows, many_rows)

    elif card.family_id == "X5":

        def excluded(
            pack: Pack,
            name: str,
            users: list[JsonValue],
            blocks: list[JsonValue],
            extra: list[JsonValue],
            tenant: int = 2,
        ) -> None:
            if middle:
                filtered = [
                    row[1]
                    for row in users
                    if isinstance(row, list)
                    and row[0] == tenant
                    and not any(
                        isinstance(e, list)
                        and e[0] == tenant
                        and e[1] == row[1]
                        and e[2] is True
                        for e in blocks
                    )
                    and not any(isinstance(e, list) and e[0] == row[1] for e in extra)
                ]
                tables: dict[str, JsonValue] = {
                    "users": users,
                    "exclusions": blocks,
                    "extra_exclusions": extra,
                }
                forbidden: list[JsonValue] = [
                    {"user_id": row[1]}
                    for row in users
                    if isinstance(row, list)
                    and row[0] != tenant
                    and not any(
                        isinstance(other, list)
                        and other[0] == tenant
                        and other[1] == row[1]
                        for other in users
                    )
                ]
                params: dict[str, JsonValue] = {"tenant_id": tenant}
            else:
                filtered = [
                    row[0]
                    for row in users
                    if isinstance(row, list)
                    and not any(isinstance(e, list) and e[0] == row[0] for e in blocks)
                ]
                tables = {"users": users, "blocked": blocks}
                forbidden, params = [], {}
            rows: list[JsonValue] = [
                {"user_id": value} for value in sorted(filtered, key=fixture_integer)
            ]
            select(pack, name, tables, params, rows, ["user_id"], forbidden=forbidden)

        if middle:
            users: list[JsonValue] = [[1, n + 7], [2, n + 7], [2, n + 8], [1, n + 99]]
            excluded("A", "own-active", users, [[2, n + 7, True]], [])
            excluded("A", "inactive", users, [[2, n + 7, False]], [])
            excluded("B", "empty", [], [], [])
            excluded("B", "null-duplicates", users, [], [[None], [n + 8], [n + 8]])
            excluded("B", "unknown-company", users, [], [], 99)
            excluded("C", "other-company", users, [[1, n + 7, True]], [])
            excluded(
                "D", "global-exclusion", users, [[1, n + 7, True]], [[n + 7], [None]]
            )
            excluded(
                "D",
                "mixed-companies",
                users,
                [[1, n + 8, True], [2, n + 7, False], [2, n + 8, True]],
                [[None], [None]],
            )
        else:
            users = [[n + 1], [n + 2], [n + 3]]
            excluded("A", "one-block", users, [[n + 2]], [])
            excluded("A", "empty-blocks", users, [], [])
            excluded("B", "empty-users", [], [[n + 2]], [])
            excluded("B", "duplicates", users, [[n + 2], [n + 2]], [])
            excluded("B", "unknown-id", users, [[n + 99]], [])
            excluded("C", "block-and-null", users, [[n + 2], [None]], [])
            excluded("C", "only-null", users, [[None]], [])
            excluded(
                "D",
                "many-nulls",
                list(reversed(users)),
                [[None], [n + 2], [None], [n + 2]],
                [],
            )
            excluded("D", "all-blocked", users, [[n + 3], [n + 1], [n + 2]], [])

    elif card.family_id == "Y1":

        def page(
            pack: Pack,
            name: str,
            scores: list[JsonValue],
            limit: int,
            after: tuple[int, int] | None = None,
        ) -> None:
            if middle:
                selected: dict[int, list[JsonValue]] = {}
                for row in scores:
                    if not isinstance(row, list) or not isinstance(row[0], int):
                        raise ValueError("bad_fixture")
                    old = selected.get(row[0])
                    if old is None or (row[2], row[3]) > (old[2], old[3]):
                        selected[row[0]] = row
                ordered = sorted(selected.values(), key=lambda r: (r[1], r[0]))
                filtered = [r for r in ordered if after is None or (r[1], r[0]) > after]
                rows: list[JsonValue] = [
                    {"id": r[0], "score": r[1]} for r in filtered[: max(0, limit)]
                ]
                params: dict[str, JsonValue] = {
                    "limit": limit,
                    "has_after": after is not None,
                    "after_score": after[0] if after else 0,
                    "after_id": after[1] if after else 0,
                }
                columns = ["id", "score"]
            else:
                rows = (
                    [
                        {"id": fixture_row(r)[0]}
                        for r in sorted(
                            scores,
                            key=lambda r: (
                                fixture_integer(fixture_row(r)[1]),
                                fixture_integer(fixture_row(r)[0]),
                            ),
                        )[: max(0, limit)]
                    ]
                    if scores
                    else []
                )
                params, columns = {"limit": limit}, ["id"]
            select(pack, name, {"scores": scores}, params, rows, columns)

        base: list[JsonValue] = (
            [[n + 2, 3, 1, 1], [n + 1, 3, 1, 1], [n + 3, 1, 1, 1]]
            if middle
            else [[n + 2, 3], [n + 1, 3], [n + 3, 1]]
        )
        page("A", "first-page", base, 2)
        page("A", "following-page", base, 2, (3, n + 1)) if middle else page(
            "A", "limit-one", base, 1
        )
        page("B", "empty", [], 2)
        page("B", "zero-limit", base, 0)
        page("B", "negative-limit", base, -1)
        page("B", "large-limit", base, 20)
        if middle:
            ties: list[JsonValue] = [
                [n + 7, 9, 2, 1],
                [n + 7, 1, 2, 2],
                [n + 8, -3, 1, 1],
            ]
            page("B", "revision-id-tie", ties, 3)
            page("B", "after-end", base, 2, (99, n + 99))
            page("C", "version-before-cursor", ties, 3, (3, n + 4))
            page("D", "all-pages-first", base + ties, 2)
            page("D", "all-pages-second", base + ties, 2, (1, n + 7))
            page("D", "all-pages-third", base + ties, 2, (3, n + 2))
        for i in range(3):
            tied: list[JsonValue] = (
                [[2**60 + 2, -1, 1, 1], [2**60 + 1, -1, 1, 1], [n + 3, -1, 1, 1]]
                if middle
                else [[2**60 + 2, -1], [2**60 + 1, -1], [n + 3, -1]]
            )
            rng.shuffle(tied)
            page("C" if i == 0 else "D", f"tie-permutation-{i}", tied, i + 1)

    elif card.family_id == "Y5":

        def event(pack: Pack, name: str, events: list[JsonValue]) -> None:
            winners: dict[str, list[JsonValue]] = {}
            for row in events:
                if not isinstance(row, list) or not isinstance(row[0], str):
                    raise ValueError("bad_fixture")
                old = winners.get(row[0])
                if old is None or (row[2], row[1]) > (old[2], old[1]):
                    winners[row[0]] = row
            rows: list[JsonValue] = [
                {
                    "key": row[0],
                    "event_id": row[1],
                    "created_at": row[2],
                    "value": row[3],
                }
                for key in sorted(winners)
                if not (middle and winners[key][4] is True)
                for row in [winners[key]]
            ]
            select(
                pack,
                name,
                {"events": events},
                {},
                rows,
                ["key", "event_id", "created_at", "value"],
                debug_field="event_id",
            )

        def row(
            key: str, ident: int, timestamp: int, value: str, deleted: bool = False
        ) -> JsonValue:
            return (
                [key, n + ident, timestamp, value, deleted]
                if middle
                else [key, n + ident, timestamp, value]
            )

        event("A", "one", [row("A", 1, 10, "first")])
        event(
            "A",
            "keys-or-deleted",
            [
                row("A", 1, 10, "first"),
                row("A", 2, 20, "last", middle),
                row("B", 3, 10, "other"),
            ],
        )
        event("B", "empty", [])
        event("B", "tie", [row("A", 8, 10, "eight"), row("A", 9, 10, "nine")])
        if middle:
            event("B", "deleted-only", [row("A", 1, 1, "gone", True)])
            event(
                "C",
                "restore",
                [
                    row("A", 1, 1, "old"),
                    row("A", 2, 2, "gone", True),
                    row("A", 3, 3, "new"),
                ],
            )
        else:
            event(
                "C", "tie-forward", [row("A", 8, 10, "eight"), row("A", 9, 10, "nine")]
            )
            event(
                "C", "tie-reversed", [row("A", 9, 10, "nine"), row("A", 8, 10, "eight")]
            )
        event("D", "big-id-old", [row("A", 99, 1, "old"), row("A", 1, 2, "new")])
        event(
            "D",
            "ties-before-delete",
            [
                row("A", 1, 10, "first"),
                row("A", 2, 10, "last", middle),
                row("B", 3, 10, "b"),
                row("B", 4, 10, "bb"),
            ],
        )
        event(
            "D",
            "insertion-reversed",
            [
                row("B", 4, 10, "bb"),
                row("A", 2, 10, "last", middle),
                row("B", 3, 10, "b"),
                row("A", 1, 10, "first"),
            ],
        )

    elif card.family_id == "Y3":

        def operation(
            account: int, delta: int, event: str = "evt", rollback: bool = False
        ) -> dict[str, JsonValue]:
            return {
                "account_id": account,
                "delta": delta,
                "event_id": event,
                "rollback": rollback,
            }

        def transaction(
            pack: Pack,
            name: str,
            counters: list[JsonValue],
            operations: list[dict[str, JsonValue]],
            *,
            concurrent: bool = False,
        ) -> None:
            state: dict[int, int] = {
                r[0]: r[1]
                for r in counters
                if isinstance(r, list)
                and isinstance(r[0], int)
                and isinstance(r[1], int)
            }
            applied: dict[tuple[int, str], int] = {}
            responses: list[JsonValue] = []
            for op in operations:
                account, delta, event_id = op["account_id"], op["delta"], op["event_id"]
                if (
                    not isinstance(account, int)
                    or not isinstance(delta, int)
                    or not isinstance(event_id, str)
                ):
                    raise ValueError("bad_fixture")
                previous = applied.get((account, event_id))
                if middle and previous is not None:
                    responses.append("duplicate" if previous == delta else "conflict")
                else:
                    responses.append("applied" if middle else state[account] + delta)
                    if not op["rollback"]:
                        state[account] += delta
                        if middle:
                            applied[(account, event_id)] = delta
            counter_state: list[JsonValue] = [
                {"account_id": account, "value": state[account]}
                for account in sorted(state)
            ]
            checks = [
                b.assertion(
                    "sql_data",
                    ["returns"],
                    responses,
                    comparison="unordered" if concurrent else "exact",
                ),
                b.assertion("debug_reliability", ["state", "counters"], counter_state),
            ]
            if concurrent and not middle:
                # Первый worker удерживается барьером; остальные могут
                # сериализоваться в любом порядке. Возвраты принадлежат worker.
                possible: list[JsonValue] = []
                for order in permutations(range(1, len(operations))):
                    values = {
                        r[0]: r[1]
                        for r in counters
                        if isinstance(r, list)
                        and isinstance(r[0], int)
                        and isinstance(r[1], int)
                    }
                    returned: list[JsonValue] = [None] * len(operations)
                    for index in (0, *order):
                        op = operations[index]
                        account, delta = op["account_id"], op["delta"]
                        if not isinstance(account, int) or not isinstance(delta, int):
                            raise ValueError("bad_fixture")
                        values[account] += delta
                        returned[index] = values[account]
                    possible.append(returned)
                checks[0] = b.assertion(
                    "sql_data", ["returns"], possible, comparison="one_of"
                )
            if middle:
                event_rows: list[JsonValue] = [
                    {
                        "account_id": account,
                        "event_id": event,
                        "delta": applied[(account, event)],
                    }
                    for account, event in sorted(applied)
                ]
                checks.extend(
                    [
                        b.assertion("sql_data", ["state", "applied"], event_rows),
                        b.assertion(
                            "debug_reliability", ["state", "outbox"], event_rows
                        ),
                    ]
                )
                checks.append(
                    b.assertion(
                        "debug_reliability",
                        ["state", "outbox"],
                        len(event_rows),
                        comparison="count",
                        critical="double_debit",
                    )
                )
                if len({(op["account_id"], op["event_id"]) for op in operations}) < len(
                    operations
                ):
                    for index, account in enumerate(sorted(state)):
                        delta = next(
                            op["delta"]
                            for op in operations
                            if op["account_id"] == account
                        )
                        if not isinstance(delta, int):
                            raise ValueError("bad_fixture")
                        checks.append(
                            b.assertion(
                                "debug_reliability",
                                ["state", "counters", str(index), "value"],
                                state[account],
                                comparison="maximum" if delta >= 0 else "minimum",
                                critical="double_debit",
                            )
                        )
            if concurrent:
                checks.append(
                    b.assertion("debug_reliability", ["connections"], len(operations))
                )
            b.add(
                pack,
                name,
                {
                    "tables": {"counters": counters},
                    "operations": list(operations),
                    "concurrent": concurrent,
                },
                checks,
            )

        transaction("A", "first", [[n + 1, 10]], [operation(n + 1, 3)])
        transaction("A", "other", [[n + 2, 0]], [operation(n + 2, 2)])
        if middle:
            transaction(
                "A",
                "two-events",
                [[n + 1, 10]],
                [operation(n + 1, 3, "one"), operation(n + 1, 2, "two")],
            )
            transaction(
                "B",
                "duplicate",
                [[n + 1, 10]],
                [operation(n + 1, 3), operation(n + 1, 3)],
            )
            transaction(
                "B",
                "conflict",
                [[n + 1, 10]],
                [operation(n + 1, 3), operation(n + 1, 7)],
            )
            transaction(
                "B",
                "same-event-two-accounts",
                [[n + 1, 10], [n + 2, 0]],
                [operation(n + 1, 3), operation(n + 2, 2)],
            )
            transaction("B", "negative", [[n + 1, 0]], [operation(n + 1, -3)])
            transaction(
                "C",
                "rollback-then-delivery",
                [[n + 1, 10]],
                [
                    operation(n + 1, 3, rollback=True),
                    operation(n + 1, 3),
                    operation(n + 1, 3),
                ],
            )
            transaction(
                "D",
                "same-event-race",
                [[n + 1, 10]],
                [operation(n + 1, 3), operation(n + 1, 3)],
                concurrent=True,
            )
            transaction(
                "D",
                "different-events-race",
                [[n + 1, 10]],
                [
                    operation(n + 1, 3, "one"),
                    operation(n + 1, 2, "two"),
                    operation(n + 1, -1, "three"),
                ],
                concurrent=True,
            )
        else:
            transaction(
                "B",
                "two-connections",
                [[n + 1, 10]],
                [operation(n + 1, 3), operation(n + 1, 2)],
                concurrent=True,
            )
            transaction(
                "B",
                "independent-accounts",
                [[n + 1, 10], [n + 2, 20]],
                [operation(n + 1, 3), operation(n + 2, 2)],
                concurrent=True,
            )
            transaction("C", "zero", [[n + 1, 10]], [operation(n + 1, 0)])
            transaction("C", "negative-result", [[n + 1, 0]], [operation(n + 1, -3)])
            transaction(
                "D",
                "mixed-concurrent",
                [[n + 1, 10]],
                [operation(n + 1, 3), operation(n + 1, -2), operation(n + 1, 0)],
                concurrent=True,
            )
            transaction(
                "D",
                "each-only-one-row",
                [[n + 1, 10], [n + 2, 20]],
                [operation(n + 1, 3), operation(n + 2, -5)],
                concurrent=True,
            )
        transaction(
            "D",
            "seeded-amounts",
            [[n + 1, amount]],
            [
                operation(n + 1, seed % 17 + 1, "seed-one"),
                operation(n + 1, -(seed % 7 + 1), "seed-two"),
            ],
            concurrent=True,
        )
    else:
        raise ValueError("unsupported_v3_sql_card")
    return b.cases
