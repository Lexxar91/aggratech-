"""Коллекции, страницы и повторы: результат отдельно от журнала вызовов."""

import random

from pydantic import JsonValue

from app.assessment.v3_cases import CaseBuilder, Pack
from app.assessment.v3_models import V3Card, V3Case
from app.assessment.v3_python_cases import adapter, invocation


def collections_cases(card: V3Card, seed: int) -> list[V3Case]:
    """Пакеты покрывают все опубликованные ограничения восьми карточек."""
    b = CaseBuilder(card, seed)
    middle = card.grade == "middle"
    rng = random.Random(seed)
    amount, n = 100 + seed % 13, seed % 1000 * 10
    if card.family_id == "X1":

        def total_case(
            pack: Pack,
            name: str,
            rows: list[JsonValue],
            paid: bool,
            *,
            stream: bool = False,
        ) -> None:
            chosen = rows
            if middle:
                latest: dict[int, dict[str, JsonValue]] = {}
                for raw in rows:
                    if not isinstance(raw, dict) or not isinstance(
                        raw["record_id"], int
                    ):
                        raise ValueError("bad_fixture")
                    old = latest.get(raw["record_id"])
                    if old is None or (raw["revision"], raw["revision_id"]) > (
                        old["revision"],
                        old["revision_id"],
                    ):
                        latest[raw["record_id"]] = raw
                chosen = list(latest.values())
            totals: dict[str, int] = {}
            for raw in chosen:
                if not isinstance(raw, dict) or not isinstance(raw["team"], str):
                    raise ValueError("bad_fixture")
                if paid and raw["status"] != "paid":
                    continue
                totals.setdefault(raw["team"], 0)
                if isinstance(raw["amount"], int):
                    totals[raw["team"]] += raw["amount"]
            result: list[JsonValue] = [
                {"team": team, "total": totals[team]} for team in sorted(totals)
            ]
            argument: JsonValue = {"$stream": "rows"} if stream else rows
            scenario: dict[str, JsonValue] = {
                "invocations": [
                    invocation(
                        "totals_latest" if middle else "totals", [argument, paid]
                    )
                ]
            }
            checks = [
                b.assertion("language_algorithms", ["results", "0", "value"], result)
            ]
            if stream:
                scenario["streams"] = {"rows": {"items": rows}}
                checks.append(
                    b.assertion(
                        "language_algorithms",
                        ["observed", "stream_reads", "rows"],
                        len(rows),
                    )
                )
            else:
                checks.append(
                    b.assertion(
                        "language_algorithms",
                        ["results", "0", "input_after", "0"],
                        rows,
                    )
                )
            b.add(pack, name, scenario, checks)

        def row(
            team: str,
            value: int | None,
            status: str = "paid",
            record: int = 1,
            revision: int = 1,
            revision_id: int = 1,
        ) -> JsonValue:
            fields: dict[str, JsonValue] = {
                "team": team,
                "amount": value,
                "status": status,
            }
            if middle:
                fields.update(
                    {
                        "record_id": n + record,
                        "revision": revision,
                        "revision_id": revision_id,
                    }
                )
            return fields

        total_case("A", "ordinary-one", [row("A", 2), row("A", 3, record=2)], False)
        total_case(
            "A", "ordinary-two", [row("B", amount), row("A", 1, record=2)], False
        )
        total_case("B", "empty", [], False)
        total_case("B", "none-only", [row("A", None)], True)
        total_case("B", "negative", [row("A", -amount)], True)
        total_case(
            "B",
            "cancelled",
            [row("A", amount, "cancelled"), row("B", None, record=2)],
            True,
        )
        if middle:
            versions = [row("A", amount), row("B", 20, "cancelled", revision=2)]
            total_case(
                "A",
                "two-revisions",
                [row("A", amount), row("A", 20, revision=2)],
                False,
            )
            total_case(
                "B",
                "revision-id-tie",
                [row("A", amount), row("B", 20, revision_id=2)],
                False,
            )
            total_case("B", "one-shot", versions, False, stream=True)
            total_case("B", "filter-after-version", versions, True)
            total_case("C", "move-team", versions, False, stream=True)
            total_case("C", "move-status", versions, True, stream=True)
        else:
            total_case(
                "C",
                "one-shot",
                [row("A", None), row("B", -amount), row("B", 20, "cancelled")],
                True,
                stream=True,
            )
        for i in range(3):
            mixed = [
                row("A", None),
                row("B", -amount, record=2),
                row("A", amount, "cancelled", record=3),
                row("B", 2, record=4),
            ]
            rng.shuffle(mixed)
            total_case("D", f"permutation-{i}", mixed, bool(i % 2), stream=bool(i % 2))
        count = 750000
        generated_row = row("RAM", 0)
        if middle:
            expected_sum = sum(i % 7 for i in range(count - 20, count))
        else:
            expected_sum = count // 7 * 21 + sum(range(count % 7))
        b.add(
            "C",
            "bounded-memory-one-shot",
            {
                "invocations": [
                    invocation(
                        "totals_latest" if middle else "totals",
                        [{"$generated": {"count": count, "row": generated_row}}, False],
                    )
                ]
            },
            [
                b.assertion(
                    "language_algorithms",
                    ["results", "0", "value"],
                    [{"team": "RAM", "total": expected_sum}],
                ),
                b.assertion(
                    "language_algorithms",
                    ["results", "0", "input_after", "0", "$generated_consumed"],
                    count,
                ),
            ],
        )

    elif card.family_id == "Y1":

        def page_case(
            pack: Pack,
            name: str,
            rows: list[JsonValue],
            limit: int,
            after: tuple[int, int] | None = None,
        ) -> None:
            selected: dict[int, dict[str, JsonValue]] = {}
            for raw in rows:
                if not isinstance(raw, dict) or not isinstance(raw["id"], int):
                    raise ValueError("bad_fixture")
                old = selected.get(raw["id"])
                if (
                    not middle
                    or old is None
                    or (raw["revision"], raw["revision_id"])
                    > (old["revision"], old["revision_id"])
                ):
                    selected[raw["id"]] = raw
            ordered = sorted(selected.values(), key=lambda r: (r["score"], r["id"]))
            filtered = [
                r
                for r in ordered
                if not middle or after is None or (r["score"], r["id"]) > after
            ]
            expected: JsonValue = (
                list(filtered[: max(limit, 0)])
                if middle
                else [r["id"] for r in filtered[: max(limit, 0)]]
            )
            args: list[JsonValue] = [rows, limit]
            if middle:
                args.append({"$tuple": list(after)} if after else None)
            b.add(
                pack,
                name,
                {
                    "invocations": [
                        invocation("next_page" if middle else "first_ids", args)
                    ]
                },
                [
                    b.assertion(
                        "language_algorithms", ["results", "0", "value"], expected
                    ),
                    b.assertion(
                        "language_algorithms",
                        ["results", "0", "input_after", "0"],
                        rows,
                    ),
                ],
            )

        def ranked_row(
            ident: int, score: int, revision: int = 1, revision_id: int = 1
        ) -> JsonValue:
            value: dict[str, JsonValue] = {"id": n + ident, "score": score}
            if middle:
                value.update({"revision": revision, "revision_id": revision_id})
            return value

        rows = [ranked_row(2, 3), ranked_row(1, 3), ranked_row(3, 1)]
        page_case("A", "first", rows, 2)
        page_case("A", "next", rows, 2, (3, n + 1)) if middle else page_case(
            "A", "limit-one", rows, 1
        )
        page_case("B", "empty", [], 2)
        page_case("B", "zero", rows, 0)
        page_case("B", "negative", rows, -1)
        page_case("B", "large-limit", rows, 20)
        page_case("B", "negative-score", [ranked_row(1, -3), ranked_row(2, -4)], 2)
        if middle:
            changed = [ranked_row(7, 9, 1), ranked_row(7, 1, 2)]
            page_case(
                "B",
                "revision-id-tie",
                [ranked_row(1, 5, 1, 1), ranked_row(1, 1, 1, 2)],
                2,
            )
            page_case("B", "after-last", rows, 2, (99, n + 99))
            page_case("C", "version-before-cursor", changed, 2, (3, n + 4))
            full = rows + changed
            page_case("D", "snapshot-page-one", full, 2)
            page_case("D", "snapshot-page-two", full, 2, (1, n + 7))
            page_case("D", "snapshot-page-three", full, 2, (3, n + 2))
        for i in range(3):
            tied = [ranked_row(1, -1), ranked_row(2, -1), ranked_row(3, -1)]
            rng.shuffle(tied)
            page_case("C" if i == 0 else "D", f"ties-{i}", tied, i + 1)
        page_case(
            "D",
            "big-id",
            [
                {
                    "id": 2**60,
                    "score": 0,
                    **({"revision": 1, "revision_id": 1} if middle else {}),
                },
                ranked_row(1, 0),
            ],
            2,
        )

    elif card.family_id == "X4":

        def pages_case(
            pack: Pack, name: str, pages: dict[str, JsonValue], limit: int
        ) -> None:
            items: list[JsonValue] = []
            calls: list[JsonValue] = []
            ids: set[int] = set()
            cursor = "a"
            stop = "limit"
            while limit > 0:
                if cursor in calls:
                    stop = "cursor_cycle"
                    break
                calls.append(cursor)
                page = pages[cursor]
                if not isinstance(page, dict) or not isinstance(page["items"], list):
                    raise ValueError("bad_fixture")
                for item in page["items"]:
                    if not isinstance(item, dict) or not isinstance(item["id"], int):
                        raise ValueError("bad_fixture")
                    if item["id"] not in ids:
                        ids.add(item["id"])
                        items.append(item)
                        if len(items) == limit:
                            break
                if len(items) == limit:
                    stop = "limit"
                    break
                if page["has_more"] is False:
                    stop = "end"
                    break
                if not isinstance(page["next_cursor"], str):
                    raise ValueError("bad_fixture")
                cursor = page["next_cursor"]
            checks = [
                b.assertion(
                    "language_algorithms",
                    ["results", "0", "value", "items" if middle else "0"],
                    items,
                ),
                b.assertion(
                    "http_api",
                    ["results", "0", "value", "calls" if middle else "1"],
                    calls,
                ),
                b.assertion("http_api", ["observed", "page_calls"], calls),
            ]
            if middle:
                checks.append(
                    b.assertion(
                        "language_algorithms", ["results", "0", "value", "stop"], stop
                    )
                )
            b.add(
                pack,
                name,
                {
                    "adapters": {"fetch": {"kind": "pages", "pages": pages}},
                    "invocations": [
                        invocation(
                            "collect_safe" if middle else "collect",
                            [adapter("fetch"), "a", limit],
                        )
                    ],
                },
                checks,
            )

        def page(
            items: list[JsonValue], more: bool = False, cursor: str | None = None
        ) -> JsonValue:
            return {"items": items, "has_more": more, "next_cursor": cursor}

        one: JsonValue = {"id": n + 1, "value": "first"}
        two: JsonValue = {"id": n + 2, "value": "second"}
        duplicate: JsonValue = {"id": n + 1, "value": "changed"}
        pages_case("A", "terminal", {"a": page([one])}, 10)
        pages_case(
            "A", "two-pages", {"a": page([one], True, "b"), "b": page([two])}, 10
        )
        pages_case("B", "zero", {"a": page([one])}, 0)
        pages_case("B", "negative", {"a": page([one])}, -1)
        pages_case("B", "exact-limit", {"a": page([one, two], True, "b")}, 2)
        pages_case(
            "B",
            "empty-intermediate",
            {"a": page([one], True, "b"), "b": page([], True, "c"), "c": page([two])},
            10,
        )
        pages_case(
            "B",
            "first-wins",
            {"a": page([one], True, "b"), "b": page([duplicate, two])},
            10,
        )
        if middle:
            pages_case(
                "A",
                "cursor-cycle",
                {"a": page([one], True, "b"), "b": page([two], True, "a")},
                10,
            )
            pages_case("B", "self-cycle", {"a": page([one], True, "a")}, 10)
            pages_case("B", "empty-terminal", {"a": page([])}, 10)
            pages_case(
                "C",
                "empty-cycle",
                {"a": page([one], True, "b"), "b": page([], True, "a")},
                10,
            )
            pages_case(
                "C",
                "limit-before-cycle",
                {"a": page([one], True, "b"), "b": page([], True, "a")},
                1,
            )
            pages_case("D", "terminal-backward", {"a": page([one], False, "a")}, 10)
            pages_case("D", "limit-before-end", {"a": page([one], False, "a")}, 1)
            pages_case(
                "D",
                "ids-cross-cycle",
                {"a": page([one], True, "b"), "b": page([duplicate, two], True, "a")},
                10,
            )
        else:
            pages_case(
                "C",
                "terminal-duplicate",
                {
                    "a": page([one], True, "b"),
                    "b": page([duplicate, two], False, "not_requested"),
                },
                10,
            )
            pages_case(
                "D",
                "many-empty",
                {"a": page([], True, "b"), "b": page([], True, "c"), "c": page([one])},
                10,
            )
            pages_case(
                "D",
                "inside-page-limit",
                {"a": page([one, duplicate, two, {"id": n + 3}])},
                2,
            )
            pages_case(
                "D", "same-page-duplicate", {"a": page([one, duplicate, two])}, 10
            )

    elif card.family_id == "Y4":

        def retry_case(
            pack: Pack,
            name: str,
            statuses: list[JsonValue],
            attempts: int,
            delay: int,
            *,
            retryable: list[JsonValue] | None = None,
            method: str = "GET",
            supported: bool = False,
            key: str | None = None,
            budget: int = 10,
        ) -> None:
            used, last, stop = 0, None, "attempts"
            waits: list[int] = []
            allowed = method in {"GET", "PUT", "DELETE"} or (
                method == "POST" and supported and bool(key)
            )
            for status in statuses[: max(0, attempts)]:
                used += 1
                last = None if status == "timeout" else status
                if last == 200:
                    stop = "success"
                    break
                permitted = (
                    last in (503, None) if middle else last in (retryable or [503])
                )
                if not permitted:
                    stop = "status"
                    break
                if used == attempts:
                    break
                if middle and not allowed:
                    stop = "unsafe"
                    break
                if middle and sum(waits) + delay > budget:
                    stop = "budget"
                    break
                waits.append(delay)
            result: dict[str, JsonValue] = {
                "attempts": used,
                "last_status": last,
                "waits": list(waits),
            }
            if middle:
                result["stop"] = stop
                args: list[JsonValue] = [
                    adapter("send"),
                    adapter("sleep"),
                    method,
                    supported,
                    key,
                    attempts,
                    delay,
                    budget,
                ]
            else:
                args = [adapter("send"), adapter("sleep"), attempts, delay]
                if retryable is not None:
                    args.append({"$frozenset": retryable})
            checks = [
                b.assertion(
                    "language_algorithms", ["results", "0", "value", "attempts"], used
                ),
                b.assertion(
                    "language_algorithms",
                    ["results", "0", "value", "waits"],
                    list(waits),
                ),
                b.assertion("http_api", ["results", "0", "value", "last_status"], last),
                b.assertion(
                    "http_api",
                    ["observed", "send_calls"],
                    [[method, key] if middle else [] for _ in range(used)],
                ),
                b.assertion(
                    "debug_reliability", ["observed", "wait_calls"], list(waits)
                ),
            ]
            if middle:
                checks.append(
                    b.assertion(
                        "language_algorithms", ["results", "0", "value", "stop"], stop
                    )
                )
            b.add(
                pack,
                name,
                {
                    "adapters": {
                        "send": {"kind": "send", "values": statuses},
                        "sleep": {"kind": "sleep"},
                    },
                    "invocations": [
                        invocation("retry_request" if middle else "retry", args)
                    ],
                },
                checks,
            )

        retry_case("A", "retry-success", [503, 200], 3, 1)
        retry_case(
            "A",
            "ordinary-success",
            [503, 200] if middle else [200],
            3,
            1,
            method="POST" if middle else "GET",
            supported=middle,
            key="key" if middle else None,
        )
        for status in (400, 401, 404):
            retry_case("B", f"permanent-{status}", [status, 200], 3, 1)
        retry_case("B", "zero-attempts", [200], 0, 1)
        retry_case("B", "negative-attempts", [200], -1, 1)
        retry_case("B", "one-attempt", [503, 200], 1, 1)
        retry_case("B", "zero-delay", [503, 200], 3, 0, budget=0)
        if middle:
            retry_case(
                "B", "key-not-guarantee", [503, 200], 3, 1, method="POST", key="present"
            )
            retry_case(
                "B",
                "guarantee-without-key",
                [503, 200],
                3,
                1,
                method="POST",
                supported=True,
            )
            retry_case(
                "B",
                "guarantee-empty-key",
                [503, 200],
                3,
                1,
                method="POST",
                supported=True,
                key="",
            )
            retry_case("B", "budget-insufficient", [503, 200], 3, 2, budget=1)
            retry_case("B", "budget-exact", [503, 200], 3, 2, budget=2)
            retry_case(
                "C",
                "timeout-unsafe",
                ["timeout", 200],
                3,
                1,
                method="POST",
                key="present",
            )
            retry_case(
                "C",
                "timeout-supported",
                ["timeout", 200],
                3,
                1,
                method="POST",
                key="present",
                supported=True,
            )
            for method in ("PUT", "DELETE"):
                retry_case(
                    "D", method.lower(), [503, "timeout", 200], 3, 1, method=method
                )
            retry_case(
                "D",
                "attempts-priority",
                ["timeout", 200],
                1,
                2,
                method="POST",
                budget=0,
            )
            retry_case("D", "budget-sum", [503, 503, 200], 4, 2, budget=3)
        else:
            retry_case("C", "429-added", [429, 200], 3, 1, retryable=[503, 429])
            retry_case("D", "exhausted", [503, 503, 503, 200], 3, 1)
            retry_case("D", "200-in-retryable", [200, 503], 3, 1, retryable=[200, 503])
        retry_case(
            "D",
            "seeded-delay",
            [503, 503, 200],
            3,
            seed % 7 + 1,
            budget=(seed % 7 + 1) * 2 if middle else 10,
        )
    else:
        raise ValueError("unsupported_collection_card")
    return b.cases
