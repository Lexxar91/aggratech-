"""Подписи и доступ: HTTP-ответы отдельно от сохранённых изменений."""

import hashlib
import hmac
import json

from pydantic import JsonValue

from app.assessment.v3_cases import CaseBuilder, Pack
from app.assessment.v3_models import V3Card, V3Case
from app.assessment.v3_python_cases import adapter, byte_input, invocation


def boundary_cases(card: V3Card, seed: int) -> list[V3Case]:
    """Каждому обязательному отказу соответствует отдельный исполняемый случай."""
    if card.family_id == "Y6":
        from app.assessment.v3_upload_cases import upload_cases

        return upload_cases(card, seed)
    b = CaseBuilder(card, seed)
    middle = card.grade == "middle"
    n, now, window = seed % 1000 * 10, 10000 + seed, 30
    if card.family_id == "X2":
        secret = f"fake-only-{seed}".encode()

        def signature(raw: bytes) -> str:
            return hmac.new(secret, raw, hashlib.sha256).hexdigest()

        def body(
            event: str = "evt",
            timestamp: int | bool | None = None,
            data: JsonValue = None,
        ) -> bytes:
            return json.dumps(
                {
                    "event_id": event,
                    "timestamp": now if timestamp is None else timestamp,
                    "data": {} if data is None else data,
                },
                separators=(",", ":"),
            ).encode()

        def event_case(
            pack: Pack,
            name: str,
            requests: list[tuple[bytes, str, str]],
            statuses: list[JsonValue],
            *,
            events: int,
            parallel: bool = False,
            restart: bool = False,
        ) -> None:
            invocations: list[JsonValue] = []
            enqueued: list[JsonValue] = []
            for i, (raw, sig, content_type) in enumerate(requests):
                args: list[JsonValue] = [byte_input(raw), sig, byte_input(secret)]
                if middle:
                    args += [now, window, adapter("store")]
                else:
                    args += [content_type, adapter("enqueue")]
                    if statuses[i] == 202:
                        enqueued.append(json.loads(raw))
                invocations.append(
                    invocation(
                        "accept_event" if middle else "webhook",
                        args,
                        restart=restart and i > 0,
                    )
                )
            checks = [
                b.assertion(
                    "http_api",
                    ["return_values"],
                    statuses,
                    comparison="unordered" if parallel else "exact",
                )
            ]
            if middle:
                checks.extend(
                    [
                        b.assertion(
                            "security_validation", ["observed", "events"], events
                        ),
                        b.assertion(
                            "security_validation", ["observed", "outbox"], events
                        ),
                        b.assertion(
                            "security_validation", ["observed", "event_effects"], events
                        ),
                    ]
                )
                if events == 0 and any(
                    sig != signature(raw) for raw, sig, _ in requests
                ):
                    checks.append(
                        b.assertion(
                            "security_validation",
                            ["observed", "events"],
                            0,
                            comparison="maximum",
                            critical="unsigned_event",
                        )
                    )
            else:
                checks.append(
                    b.assertion(
                        "security_validation", ["observed", "enqueue_calls"], enqueued
                    )
                )
                if not enqueued and any(status == 401 for status in statuses):
                    checks.append(
                        b.assertion(
                            "security_validation",
                            ["observed", "enqueue_calls"],
                            0,
                            comparison="count",
                            critical="unsigned_event",
                        )
                    )
            valid_format = sum(
                len(sig) == 64 and all(c in "0123456789abcdef" for c in sig)
                for _, sig, _ in requests
            )
            if valid_format and pack == "D":
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "digest_count"],
                        valid_format,
                        comparison="minimum",
                    )
                )
            scenario: dict[str, JsonValue] = {
                "adapters": {"store": {"kind": "events"}}
                if middle
                else {"enqueue": {"kind": "enqueue"}},
                "invocations": invocations,
                "parallel": parallel,
            }
            if parallel:
                scenario["barrier"] = "store.record"
            b.add(pack, name, scenario, checks)

        good = body() if middle else b'{ "value": 1, "extra": "allowed" }'
        second = body("evt-two") if middle else b'{"other":2}'
        event_case(
            "A",
            "valid-one",
            [(good, signature(good), "application/json")],
            [202],
            events=1,
        )
        event_case(
            "A",
            "valid-two",
            [(second, signature(second), "application/json")],
            [202],
            events=1,
        )
        event_case(
            "B",
            "bad-signature",
            [(good, "0" * 64, "application/json")],
            [401],
            events=0,
        )
        event_case(
            "B",
            "signed-array",
            [(b"[]", signature(b"[]"), "application/json")],
            [400],
            events=0,
        )
        event_case(
            "B",
            "signed-invalid-json",
            [(b"{bad", signature(b"{bad"), "application/json")],
            [400],
            events=0,
        )
        event_case(
            "B",
            "raw-space-changed",
            [(good + b" ", signature(good), "application/json")],
            [401],
            events=0,
        )
        if middle:
            invalid_bodies = [
                body(""),
                body(timestamp=True),
                b'{"event_id":"evt","timestamp":1,"data":[]}',
                b'{"event_id":"evt","data":{}}',
            ]
            for i, raw in enumerate(invalid_bodies):
                event_case(
                    "B",
                    f"schema-{i}",
                    [(raw, signature(raw), "application/json")],
                    [400],
                    events=0,
                )
            for distance in (-window, window, -window - 1, window + 1):
                raw = body(timestamp=now + distance)
                status = 202 if abs(distance) <= window else 401
                event_case(
                    "B",
                    f"window-{distance}",
                    [(raw, signature(raw), "application/json")],
                    [status],
                    events=int(status == 202),
                )
            conflict = body(data={"changed": True})
            event_case(
                "B",
                "same",
                [(good, signature(good), "application/json")] * 2,
                [202, 202],
                events=1,
            )
            event_case(
                "B",
                "conflict",
                [
                    (good, signature(good), "application/json"),
                    (conflict, signature(conflict), "application/json"),
                ],
                [202, 409],
                events=1,
            )
            event_case(
                "C",
                "restart-before-dispatch",
                [(good, signature(good), "application/json")] * 2,
                [202, 202],
                events=1,
                restart=True,
            )
            event_case(
                "D",
                "same-same-barrier",
                [(good, signature(good), "application/json")] * 2,
                [202, 202],
                events=1,
                parallel=True,
            )
            event_case(
                "D",
                "same-conflict-barrier",
                [
                    (good, signature(good), "application/json"),
                    (conflict, signature(conflict), "application/json"),
                ],
                [202, 409],
                events=1,
                parallel=True,
            )
            changed = body(timestamp=now + 1)
            event_case(
                "D",
                "unsigned-timestamp-change",
                [(changed, signature(good), "application/json")],
                [401],
                events=0,
            )
            reordered = json.dumps(
                {"data": {}, "timestamp": now, "event_id": "evt"}
            ).encode()
            event_case(
                "D",
                "raw-order-conflict",
                [
                    (good, signature(good), "application/json"),
                    (reordered, signature(reordered), "application/json"),
                ],
                [202, 409],
                events=1,
            )
        else:
            event_case(
                "C",
                "signature-before-type",
                [(good, "0" * 64, "text/plain")],
                [401],
                events=0,
            )
            event_case(
                "C",
                "type-before-json",
                [(b"{bad", signature(b"{bad"), "text/plain")],
                [415],
                events=0,
            )
            event_case(
                "C",
                "good-text-type",
                [(good, signature(good), "text/plain")],
                [415],
                events=0,
            )
        for _pack, name, raw, sig in [
            ("D", "invalid-utf8", b"\xff", signature(b"\xff")),
            ("D", "missing-signature", good, ""),
            ("D", "empty-body", b"", signature(b"")),
        ]:
            event_case(
                "D",
                name,
                [(raw, sig, "application/json")],
                [401 if not sig else 400],
                events=0,
            )

    elif card.family_id == "Y2" and not middle:
        invoices: dict[str, JsonValue] = {
            str(n + 1): {"invoice_id": n + 1, "owner_id": 1, "amount": 100},
            str(n + 2): {"invoice_id": n + 2, "owner_id": 1, "amount": 200},
            str(n + 3): {"invoice_id": n + 3, "owner_id": 2, "amount": 300},
        }

        def invoice_case(
            pack: Pack,
            name: str,
            principal: JsonValue,
            ident: int,
            method: str,
            status: int,
            *,
            amount: int = 7,
        ) -> None:
            expected = {
                key: dict(value)
                for key, value in invoices.items()
                if isinstance(value, dict)
            }
            writes: list[JsonValue] = []
            if method == "PATCH" and status == 200:
                expected[str(ident)]["amount"] = amount
                writes = [{"invoice_id": ident, "amount": amount}]
            checks = [
                b.assertion("http_api", ["return_values"], [status]),
                b.assertion("security_validation", ["observed", "invoices"], expected),
                b.assertion(
                    "security_validation", ["observed", "invoice_writes"], writes
                ),
            ]
            if principal is None:
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "calls"],
                        0,
                        comparison="count",
                    )
                )
            if ident == n + 3:
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "invoice_writes"],
                        0,
                        comparison="count",
                        critical="foreign_data",
                    )
                )
            b.add(
                pack,
                name,
                {
                    "invoices": invoices,
                    "adapters": {"repo": {"kind": "invoice_repo"}},
                    "invocations": [
                        invocation(
                            "handle_invoice",
                            [principal, ident, method, amount, adapter("repo")],
                        )
                    ],
                },
                checks,
            )

        owner: JsonValue = {"user_id": 1}
        invoice_case("A", "own-one", owner, n + 1, "GET", 200)
        invoice_case("A", "own-two", owner, n + 2, "GET", 200)
        invoice_case("B", "anonymous", None, n + 1, "GET", 401)
        invoice_case("B", "foreign", owner, n + 3, "GET", 404)
        invoice_case("B", "missing", owner, n + 99, "GET", 404)
        invoice_case("C", "patch-own", owner, n + 1, "PATCH", 200)
        invoice_case("C", "patch-foreign", owner, n + 3, "PATCH", 404)
        invoice_case("D", "patch-missing", owner, n + 99, "PATCH", 404)
        invoice_case("D", "amount-zero", owner, n + 2, "PATCH", 200, amount=0)
        b.add(
            "D",
            "refusal-then-own",
            {
                "invoices": invoices,
                "adapters": {"repo": {"kind": "invoice_repo"}},
                "invocations": [
                    invocation(
                        "handle_invoice", [owner, n + 3, "GET", 7, adapter("repo")]
                    ),
                    invocation(
                        "handle_invoice", [owner, n + 1, "GET", 7, adapter("repo")]
                    ),
                ],
            },
            [
                b.assertion("http_api", ["return_values"], [404, 200]),
                b.assertion(
                    "security_validation",
                    ["observed", "invoice_writes"],
                    [],
                    critical="foreign_data",
                ),
            ],
        )

    elif card.family_id == "Y2":

        def scoped(
            pack: Pack,
            name: str,
            method: str,
            status: int,
            *,
            user: int | None = 1,
            role: str = "editor",
            tenant: int = 1,
            invoice: JsonValue = None,
            missing: bool = False,
            changes: list[JsonValue] | None = None,
            conflicts: int = 0,
            cas_count: int | None = None,
            minimum_snapshots: int | None = None,
        ) -> None:
            row: JsonValue = (
                None
                if missing
                else (
                    invoice
                    if invoice is not None
                    else {"tenant_id": 1, "deleted": False, "amount": 100}
                )
            )
            expected = dict(row) if isinstance(row, dict) else None
            if (
                expected
                and changes
                and any(isinstance(v, dict) and v.get("deleted") for v in changes)
            ):
                expected["deleted"] = True
            writes: list[JsonValue] = []
            if status == 200 and method == "PATCH" and expected:
                expected["amount"] = 7
                writes = [{"tenant_id": expected["tenant_id"], "amount": 7}]
            checks = [
                b.assertion("http_api", ["return_values"], [status]),
                b.assertion("security_validation", ["observed", "invoice"], expected),
                b.assertion(
                    "security_validation", ["observed", "invoice_writes"], writes
                ),
            ]
            if status in (401, 403, 404):
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "invoice_writes"],
                        0,
                        comparison="count",
                        critical="foreign_data",
                    )
                )
            if user is None:
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "calls"],
                        0,
                        comparison="count",
                    )
                )
            if cas_count is not None:
                checks.append(
                    b.assertion("http_api", ["observed", "cas_count"], cas_count)
                )
            if minimum_snapshots:
                checks.append(
                    b.assertion(
                        "security_validation",
                        ["observed", "snapshot_count"],
                        minimum_snapshots,
                        comparison="minimum",
                    )
                )
            b.add(
                pack,
                name,
                {
                    "invoice": row,
                    "adapters": {
                        "repo": {
                            "kind": "scoped_repo",
                            "role": role,
                            "tenant_id": tenant,
                            "changes": changes or [],
                            "conflicts": conflicts,
                        }
                    },
                    "invocations": [
                        invocation(
                            "handle_scoped_invoice",
                            [user, n + 1, method, 7, adapter("repo")],
                        )
                    ],
                },
                checks,
            )

        scoped("A", "reader-get", "GET", 200, role="reader")
        scoped("A", "editor-patch", "PATCH", 200)
        scoped("B", "anonymous", "GET", 401, user=None)
        scoped("B", "reader-patch", "PATCH", 403, role="reader")
        scoped("B", "foreign", "PATCH", 404, tenant=2)
        scoped(
            "B",
            "deleted",
            "PATCH",
            404,
            invoice={"tenant_id": 1, "deleted": True, "amount": 100},
        )
        scoped("B", "missing", "PATCH", 404, missing=True)
        scoped(
            "C",
            "role-revoked",
            "PATCH",
            403,
            changes=[{"role": "reader"}],
            cas_count=1,
            minimum_snapshots=2,
        )
        scoped(
            "C",
            "deleted-before-write",
            "PATCH",
            404,
            changes=[{"deleted": True}],
            cas_count=1,
            minimum_snapshots=2,
        )
        scoped("D", "three-conflicts", "PATCH", 409, conflicts=3, cas_count=3)
        scoped(
            "D",
            "tenant-changed",
            "PATCH",
            404,
            changes=[{"tenant_id": 2}],
            cas_count=1,
            minimum_snapshots=2,
        )
        scoped("D", "conflict-then-success", "PATCH", 200, conflicts=1, cas_count=2)
        scoped("D", "foreign-before-role", "PATCH", 404, tenant=2, role="reader")
    else:
        raise ValueError("unsupported_boundary_card")
    return b.cases
