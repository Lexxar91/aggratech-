"""Доверенные fake-адаптеры вне процесса кандидата: независимые журналы и эффекты."""

import copy
import hashlib
import hmac
import io
import json
import zipfile

from pydantic import JsonValue


def object_value(value: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ValueError("object_required")
    return value


def list_value(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ValueError("list_required")
    return value


def integer_value(value: JsonValue) -> int:
    if type(value) is not int:
        raise ValueError("integer_required")
    return value


def string_value(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise ValueError("string_required")
    return value


def byte_value(value: JsonValue) -> bytes:
    return bytes.fromhex(string_value(object_value(value)["$bytes"]))


class AdapterSession:
    """Решение получает RPC-прокси; состояния и журналы ему не передаются."""

    def __init__(self, scenario: dict[str, JsonValue]) -> None:
        self.spec = copy.deepcopy(scenario)
        self.adapters = object_value(self.spec.get("adapters", {}))
        self.streams = object_value(self.spec.get("streams", {}))
        self.positions: dict[str, int] = {}
        self.iterations: dict[str, int] = {}
        self.calls: list[JsonValue] = []
        self.trace: list[JsonValue] = []
        self.events: dict[str, str] = {}
        self.outbox: dict[str, str] = {}
        self.applied_events: list[str] = []
        self.payments: dict[str, dict[str, JsonValue]] = {}
        self.operations: dict[str, dict[str, JsonValue]] = {}
        self.charges: dict[str, dict[str, JsonValue]] = {}
        self.temp: bytes | None = None
        self.published: list[str] = []
        self.commit_count = 0
        self.abort_count = 0
        self.digest_count = 0
        self.crashes = 0
        self.invoice = copy.deepcopy(self.spec.get("invoice"))
        self.invoices = object_value(copy.deepcopy(self.spec.get("invoices", {})))
        self.version = 0
        self.cas_count = 0
        self.snapshots = 0
        self.invoice_writes: list[JsonValue] = []
        self.streaming_valid = True
        self.pending_chunk = False
        for raw in list_value(self.spec.get("preparation", [])):
            step = object_value(raw)
            self.call(
                string_value(step["target"]),
                string_value(step["method"]),
                list_value(step["args"]),
            )

    def dispatch(self, target: str, method: str, args: list[JsonValue]) -> JsonValue:
        """Разрешает только опубликованные методы; Python решения не исполняется."""
        try:
            return self.call(target, method, args)
        except StopIteration:
            return {"$exception": "StopIteration"}
        except TimeoutError:
            return {"$exception": "TimeoutError"}
        except OSError:
            return {"$exception": "OSError"}
        except ValueError:
            return {"$exception": "ValueError"}
        except RuntimeError:
            return {"$exception": "RuntimeError"}

    def call(self, target: str, method: str, args: list[JsonValue]) -> JsonValue:
        """Вызовы и побочные эффекты сохраняются независимо от результата функции."""
        if target == "digest" and method == "compare":
            self.digest_count += 1
            if isinstance(args[0], str) and isinstance(args[1], str):
                return hmac.compare_digest(args[0], args[1])
            return hmac.compare_digest(byte_value(args[0]), byte_value(args[1]))
        if target.startswith("stream:"):
            return self.stream(target[7:], method)
        if target == "temp":
            return self.storage(method, args)
        adapter = object_value(self.adapters.get(target, {}))
        kind = string_value(adapter.get("kind", ""))
        self.calls.append(
            {"target": target, "method": method, "args": copy.deepcopy(args)}
        )
        self.trace.append(f"{target}.{method}")
        if kind == "pages" and method == "call":
            pages = object_value(adapter["pages"])
            return copy.deepcopy(pages[string_value(args[0])])
        if kind == "enqueue" and method == "call":
            return None
        if kind == "send" and method == "call":
            values = list_value(adapter["values"])
            position = self.positions.get(target, 0)
            self.positions[target] = position + 1
            if position >= len(values):
                raise RuntimeError("send_sequence_exhausted")
            value = values[position]
            if value == "timeout":
                raise TimeoutError
            return value
        if kind == "sleep" and method == "call":
            return None
        if kind == "events" and method == "record":
            event_id, raw = string_value(args[0]), byte_value(args[1]).hex()
            if event_id in self.events:
                return "same" if self.events[event_id] == raw else "conflict"
            self.events[event_id] = raw
            self.outbox[event_id] = raw
            return "new"
        if kind == "ledger" and method == "create_once":
            scope = list_value(args[0])
            amount = integer_value(args[1])
            key = json.dumps(scope, separators=(",", ":"))
            old = self.payments.get(key)
            if old:
                return (
                    ["same", old["payment_id"]]
                    if old["amount"] == amount
                    else ["conflict", None]
                )
            payment_id = len(self.payments) + 1
            self.payments[key] = {
                "scope": scope,
                "amount": amount,
                "payment_id": payment_id,
            }
            return ["new", payment_id]
        if kind == "payment_repo":
            return self.payment_repo(method, args, adapter)
        if kind == "provider" and method == "charge":
            operation_id, amount = string_value(args[0]), integer_value(args[1])
            old = self.charges.get(operation_id)
            if old:
                if old["amount"] != amount:
                    raise ValueError("provider_conflict")
                return old["payment_id"]
            payment_id = len(self.charges) + 101
            self.charges[operation_id] = {"amount": amount, "payment_id": payment_id}
            if adapter.get("timeout_after_charge"):
                adapter["timeout_after_charge"] = False
                raise TimeoutError
            return payment_id
        if kind == "invoice_repo":
            return self.invoice_repo(method, args)
        if kind == "scoped_repo":
            return self.scoped_repo(method, args, adapter)
        if kind == "storage" and method == "begin":
            self.temp = b""
            return {"$adapter": "temp"}
        if kind == "archive" and method == "call":
            return self.inspect_archive(adapter)
        raise ValueError("adapter_method_not_allowed")

    def stream(self, target: str, method: str) -> JsonValue:
        spec = object_value(self.streams[target])
        if method == "iter":
            self.iterations[target] = self.iterations.get(target, 0) + 1
            return None
        if method != "next":
            raise ValueError("stream_method_not_allowed")
        position = self.positions.get(target, 0)
        if spec.get("error_at") == position:
            self.trace.append(f"{target}.error")
            if spec.get("error") == "ValueError":
                raise ValueError
            raise OSError
        values = list_value(spec["items"])
        if position >= len(values):
            self.trace.append(f"{target}.end")
            raise StopIteration
        self.positions[target] = position + 1
        self.trace.append(f"{target}.read")
        if target == "chunks" and isinstance(values[position], dict):
            item = object_value(values[position])
            if item.get("$bytes"):
                self.streaming_valid = self.streaming_valid and not self.pending_chunk
                self.pending_chunk = True
        return copy.deepcopy(values[position])

    def payment_repo(
        self, method: str, args: list[JsonValue], adapter: dict[str, JsonValue]
    ) -> JsonValue:
        if method == "reserve":
            scope, amount = list_value(args[0]), integer_value(args[1])
            key = json.dumps(scope, separators=(",", ":"))
            for operation in self.operations.values():
                if operation["scope"] == scope:
                    return {
                        "conflict": operation["amount"] != amount,
                        "operation_id": operation["operation_id"],
                        "state": operation["state"],
                        "payment_id": operation["payment_id"],
                    }
            operation_id = f"op-{len(self.operations) + 1}"
            operation = {
                "scope": scope,
                "amount": amount,
                "operation_id": operation_id,
                "state": "pending",
                "payment_id": None,
                "outbox_done": False,
            }
            self.operations[operation_id] = operation
            self.outbox[key] = operation_id
            return {
                "conflict": False,
                "operation_id": operation_id,
                "state": "pending",
                "payment_id": None,
            }
        if method == "get":
            operation = self.operations[string_value(args[0])]
            return {key: operation[key] for key in ("amount", "state", "payment_id")}
        if method == "complete":
            operation = self.operations[string_value(args[0])]
            payment_id = integer_value(args[1])
            if adapter.get("crash_before_complete"):
                adapter["crash_before_complete"] = False
                self.crashes += 1
                raise RuntimeError("simulated_process_crash")
            if operation["state"] == "done" and operation["payment_id"] != payment_id:
                raise ValueError("complete_conflict")
            operation["state"] = "done"
            operation["payment_id"] = payment_id
            operation["outbox_done"] = True
            return None
        raise ValueError("repo_method_not_allowed")

    def invoice_repo(self, method: str, args: list[JsonValue]) -> JsonValue:
        invoice_id = str(integer_value(args[0]))
        if method == "get":
            return copy.deepcopy(self.invoices.get(invoice_id))
        if method == "set_amount":
            row = object_value(self.invoices[invoice_id])
            row["amount"] = integer_value(args[1])
            self.invoice_writes.append(
                {"invoice_id": int(invoice_id), "amount": row["amount"]}
            )
            return None
        raise ValueError("invoice_method_not_allowed")

    def scoped_repo(
        self, method: str, args: list[JsonValue], adapter: dict[str, JsonValue]
    ) -> JsonValue:
        if method == "snapshot":
            self.snapshots += 1
            return {
                "token": self.version,
                "tenant_id": adapter.get("tenant_id", 1),
                "role": adapter.get("role", "editor"),
                "invoice": copy.deepcopy(self.invoice),
            }
        if method == "cas_update":
            self.cas_count += 1
            changes = list_value(adapter.get("changes", []))
            if changes:
                change = object_value(changes.pop(0))
                if "role" in change:
                    adapter["role"] = change["role"]
                if "tenant_id" in change:
                    adapter["tenant_id"] = change["tenant_id"]
                if "deleted" in change and self.invoice is not None:
                    object_value(self.invoice)["deleted"] = change["deleted"]
                self.version += 1
            conflicts = integer_value(adapter.get("conflicts", 0))
            if conflicts:
                adapter["conflicts"] = conflicts - 1
                self.version += 1
            if args[0] != self.version:
                return False
            row = object_value(self.invoice)
            row["amount"] = integer_value(args[1])
            self.version += 1
            self.invoice_writes.append(
                {"amount": row["amount"], "tenant_id": row["tenant_id"]}
            )
            return True
        raise ValueError("scoped_method_not_allowed")

    def storage(self, method: str, args: list[JsonValue]) -> JsonValue:
        self.trace.append(f"temp.{method}")
        if self.temp is None:
            raise ValueError("temp_not_active")
        if method == "write":
            self.temp += byte_value(args[0])
            if byte_value(args[0]):
                self.pending_chunk = False
            if len(self.temp) > 65536:
                raise ValueError("adapter_storage_limit")
        elif method == "abort":
            self.abort_count += 1
            self.temp = None
        elif method == "commit":
            self.commit_count += 1
            self.published.append(self.temp.hex())
            self.temp = None
        else:
            raise ValueError("temp_method_not_allowed")
        return None

    def inspect_archive(self, adapter: dict[str, JsonValue]) -> JsonValue:
        """Реальный ZIP разбирается предоставленным адаптером, не кандидатом."""
        if self.temp is None:
            raise ValueError("temp_not_active")
        try:
            with zipfile.ZipFile(io.BytesIO(self.temp)) as archive:
                entries: list[JsonValue] = []
                expanded_size = 0
                for i, item in enumerate(archive.infolist()):
                    with archive.open(item) as expanded:
                        raw = expanded.read(65537 - expanded_size)
                    expanded_size += len(raw)
                    if expanded_size > 65536:
                        raise ValueError("fixture_archive_too_large")
                    stream_id = f"expanded-{i}"
                    chunks: list[JsonValue] = [
                        {"$bytes": raw[j : j + 3].hex()} for j in range(0, len(raw), 3)
                    ]
                    self.streams[stream_id] = {"items": chunks}
                    if adapter.get("expanded_error_at") is not None:
                        object_value(self.streams[stream_id])["error_at"] = adapter[
                            "expanded_error_at"
                        ]
                    entries.append(
                        {
                            "name": item.filename,
                            "is_symlink": (item.external_attr >> 16) & 0o170000
                            == 0o120000,
                            "chunks": {"$stream": stream_id},
                        }
                    )
        except zipfile.BadZipFile, RuntimeError:
            raise ValueError("invalid_zip") from None
        self.streams["archive-entries"] = {"items": entries}
        if adapter.get("error_at") is not None:
            object_value(self.streams["archive-entries"]).update(
                {"error_at": adapter["error_at"], "error": "ValueError"}
            )
        return {"$stream": "archive-entries"}

    def observation(self) -> dict[str, JsonValue]:
        """Наблюдения не зависят от словаря, возвращённого решением кандидата."""
        # Доставку предоставляет стенд; только сохранённая outbox даёт эффект.
        for event_id in self.events:
            if event_id in self.outbox and event_id not in self.applied_events:
                self.applied_events.append(event_id)
        return {
            "calls": self.calls,
            "trace": self.trace,
            "stream_reads": {
                name: self.positions.get(name, 0) for name in self.streams
            },
            "stream_iterations": {
                name: self.iterations.get(name, 0) for name in self.streams
            },
            "events": len(self.events),
            "outbox": len(self.outbox),
            "event_effects": len(self.applied_events),
            "payments": list(self.payments.values()),
            "payment_count": len(self.payments),
            "operations": list(self.operations.values()),
            "charges": len(self.charges),
            "charge_details": dict(self.charges),
            "invoices": self.invoices,
            "provider_calls": [
                list_value(object_value(c)["args"])
                for c in self.calls
                if object_value(
                    self.adapters.get(string_value(object_value(c)["target"]), {})
                ).get("kind")
                == "provider"
            ],
            "invoice": self.invoice,
            "invoice_writes": self.invoice_writes,
            "snapshot_count": self.snapshots,
            "cas_count": self.cas_count,
            "published": list(self.published),
            "temp_exists": self.temp is not None,
            "commit_count": self.commit_count,
            "abort_count": self.abort_count,
            "digest_count": self.digest_count,
            "crashes": self.crashes,
            "streaming_valid": self.streaming_valid,
            "page_calls": [
                list_value(object_value(c)["args"])[0]
                for c in self.calls
                if object_value(c)["method"] == "call"
                and object_value(
                    self.adapters.get(string_value(object_value(c)["target"]), {})
                ).get("kind")
                == "pages"
            ],
            "send_calls": [
                object_value(c)["args"]
                for c in self.calls
                if object_value(c)["method"] == "call"
                and object_value(
                    self.adapters.get(string_value(object_value(c)["target"]), {})
                ).get("kind")
                == "send"
            ],
            "wait_calls": [
                list_value(object_value(c)["args"])[0]
                for c in self.calls
                if object_value(c)["method"] == "call"
                and object_value(
                    self.adapters.get(string_value(object_value(c)["target"]), {})
                ).get("kind")
                == "sleep"
            ],
            "enqueue_calls": [
                list_value(object_value(c)["args"])[0]
                for c in self.calls
                if object_value(c)["method"] == "call"
                and object_value(
                    self.adapters.get(string_value(object_value(c)["target"]), {})
                ).get("kind")
                == "enqueue"
            ],
            "published_hashes": [
                hashlib.sha256(bytes.fromhex(v)).hexdigest() for v in self.published
            ],
        }
