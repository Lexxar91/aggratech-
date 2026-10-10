"""PostgreSQL 18 без сети; наблюдения получаются отдельными соединениями."""

import asyncio
import csv
import io
import json
import re
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

from pydantic import JsonValue

from app.assessment.runner import (
    POSTGRES_IMAGE,
    ExecutionStatus,
    RunnerUnavailable,
    V3ExecutionRequest,
    V3ExecutionResult,
)
from runner.sandbox import OutputLimit, docker_control, task_scope

# Схемы принадлежат стенду; запрос не может выбрать образ или выполнить admin SQL.
SCHEMAS: dict[str, dict[str, str]] = {
    "X1-SQL-J": {"payments": "team text NOT NULL, amount bigint, status text NOT NULL"},
    "X1-SQL-M": {
        "revisions": (
            "team text NOT NULL, record_id bigint NOT NULL, "
            "revision bigint NOT NULL, revision_id bigint NOT"
            " NULL, amount bigint, status text NOT NULL, "
            "UNIQUE(record_id,revision,revision_id)"
        )
    },
    "X3-J": {
        "orders": (
            "order_id bigint PRIMARY KEY, customer_id bigint "
            "NOT NULL, total_amount bigint NOT NULL"
        ),
        "order_lines": (
            "line_id bigint PRIMARY KEY, order_id bigint NOT "
            "NULL REFERENCES orders, qty bigint NOT NULL"
        ),
        "discounts": (
            "discount_id bigint PRIMARY KEY, order_id bigint "
            "NOT NULL REFERENCES orders, amount bigint NOT "
            "NULL"
        ),
    },
    "X3-M": {
        "orders": (
            "order_id bigint PRIMARY KEY, customer_id bigint "
            "NOT NULL, total_amount bigint NOT NULL"
        ),
        "order_lines": (
            "line_id bigint PRIMARY KEY, order_id bigint NOT "
            "NULL REFERENCES orders, qty bigint NOT NULL"
        ),
        "refunds": (
            "refund_id bigint PRIMARY KEY, order_id bigint "
            "NOT NULL REFERENCES orders, amount bigint NOT "
            "NULL"
        ),
    },
    "X5-J": {"users": "user_id bigint PRIMARY KEY", "blocked": "user_id bigint"},
    "X5-M": {
        "users": (
            "tenant_id bigint NOT NULL, user_id bigint NOT "
            "NULL, PRIMARY KEY(tenant_id,user_id)"
        ),
        "exclusions": (
            "tenant_id bigint NOT NULL, user_id bigint NOT "
            "NULL, active boolean NOT NULL"
        ),
        "extra_exclusions": "user_id bigint",
    },
    "Y1-SQL-J": {"scores": "id bigint PRIMARY KEY, score bigint NOT NULL"},
    "Y1-SQL-M": {
        "scores": (
            "id bigint NOT NULL, score bigint NOT NULL, "
            "revision bigint NOT NULL, revision_id bigint NOT"
            " NULL, UNIQUE(id,revision,revision_id)"
        )
    },
    "Y3-J": {"counters": "account_id bigint PRIMARY KEY, value bigint NOT NULL"},
    "Y3-M": {
        "counters": "account_id bigint PRIMARY KEY, value bigint NOT NULL",
        "applied": (
            "account_id bigint NOT NULL, event_id text NOT "
            "NULL, delta bigint NOT NULL, PRIMARY "
            "KEY(account_id,event_id)"
        ),
        "outbox": (
            "account_id bigint NOT NULL, event_id text NOT "
            "NULL, delta bigint NOT NULL, PRIMARY "
            "KEY(account_id,event_id)"
        ),
    },
    "Y5-J": {
        "events": (
            "key text NOT NULL, event_id bigint PRIMARY KEY, "
            "created_at bigint NOT NULL, value text NOT NULL"
        )
    },
    "Y5-M": {
        "events": (
            "key text NOT NULL, event_id bigint PRIMARY KEY, "
            "created_at bigint NOT NULL, value text NOT NULL,"
            " deleted boolean NOT NULL"
        )
    },
}

START_POSTGRES = """
set -eu
initdb -D /tmp/pgdata -U evaluator --no-locale --encoding=UTF8 \
 --auth-local=trust --auth-host=reject >/dev/null
exec postgres -D /tmp/pgdata -k /tmp -c listen_addresses='' -c max_connections=8 \
 -c shared_buffers=8MB -c work_mem=1MB -c maintenance_work_mem=8MB \
 -c max_parallel_workers=0 -c jit=off -c fsync=off -c synchronous_commit=off \
 -c statement_timeout=1500 -c lock_timeout=1000 \
 -c idle_in_transaction_session_timeout=3000 \
 -c log_statement=none -c log_min_error_statement=panic -c log_min_messages=panic
"""


def sql_create_command(name: str) -> list[str]:
    """Фиксирует все ограничения; volumes, privileged и сеть отсутствуют."""
    return [
        "docker",
        "create",
        "--name",
        name,
        "--network",
        "none",
        "--runtime",
        "runc",
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "32",
        "--ulimit",
        "nofile=128:128",
        "--ulimit",
        "core=0:0",
        "--ulimit",
        "fsize=33554432:33554432",
        "--log-driver",
        "none",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=96m,uid=65534,gid=65534,mode=0700",
        "--tmpfs",
        (
            "/var/lib/postgresql:rw,noexec,nosuid,nodev,size="
            "1m,uid=65534,gid=65534,mode=0700"
        ),
        "--label",
        "aggratech.runner=true",
        "--label",
        f"aggratech.runner.scope={task_scope()}",
        "--workdir",
        "/tmp",
        "--entrypoint",
        "/bin/sh",
        POSTGRES_IMAGE,
        "-c",
        START_POSTGRES,
    ]


def literal(value: JsonValue) -> str:
    """Экранирует значения доверенной фикстуры; SQL кандидата здесь не выполняется."""
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "TRUE" if value else "FALSE"
    if type(value) is int:
        return str(value)
    if isinstance(value, str) and "\x00" not in value:
        return "'" + value.replace("'", "''") + "'"
    raise ValueError("unsupported_sql_fixture_value")


def bind_query(
    source: str, params: dict[str, JsonValue]
) -> tuple[str, list[JsonValue]]:
    """Переводит :name в $n вне строк/комментариев; значения связывает libpq."""
    tokens = re.compile(
        (
            "('(?:''|[^'])*'|\\\"(?:\\\"\\\"|[^\\\"])*\\\"|\\$(?:[A-Za-z"
            "_]\\w*)?\\$.*?\\$(?:[A-Za-z_]\\w*)?\\$|--[^\\n]*|/\\*.*"
            "?\\*/|::|:[A-Za-z_]\\w*|\\\\|;)"
        ),
        re.S,
    )
    values: list[JsonValue] = []
    indexes: dict[str, int] = {}
    tail = source.rstrip().removesuffix(";")

    def replace(match: re.Match[str]) -> str:
        token = match.group()
        if token in ("\\", ";"):
            raise ValueError("sql_must_be_one_statement_without_psql_commands")
        if token.startswith(":") and token != "::":
            key = token[1:]
            if key not in params:
                raise ValueError("sql_unknown_parameter")
            if key not in indexes:
                values.append(params[key])
                indexes[key] = len(values)
            return f"${indexes[key]}"
        return token

    return tokens.sub(replace, tail), values


def bind_values(values: list[JsonValue]) -> str:
    """Передаёт значения в psql \\bind, использующий extended-query protocol."""
    result: list[str] = []
    for value in values:
        if value is None:
            result.append("NULL")
        else:
            raw = str(value).lower() if type(value) is bool else str(value)
            if any(c in raw for c in ("\x00", "\n", "\r")):
                raise ValueError("invalid_bound_parameter")
            result.append("'" + raw.replace("\\", "\\\\").replace("'", "\\'") + "'")
    return "\\bind " + " ".join(result) + "\n" if values else ""


async def start_psql(
    name: str, *, candidate: bool = False, application_name: str = "v3-harness"
) -> asyncio.subprocess.Process:
    """Каждый вызов создаёт настоящее отдельное соединение PostgreSQL."""
    return await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        "--interactive",
        name,
        "psql",
        "-X",
        "--quiet",
        "--csv",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        "VERBOSITY=sqlstate",
        "-h",
        "/tmp",
        "-U",
        "candidate" if candidate else "evaluator",
        "-d",
        f"dbname=postgres application_name={application_name}",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=65536,
    )


async def communicate_sql(
    process: asyncio.subprocess.Process, statement: str
) -> tuple[int, str, str]:
    """Ограничивает stdout/stderr и время; ошибка SQL не становится infra-сбоем."""
    assert process.stdin and process.stdout and process.stderr
    total = 0

    async def read(stream: asyncio.StreamReader) -> bytes:
        nonlocal total
        result: list[bytes] = []
        while data := await stream.read(4096):
            total += len(data)
            if total > 65536:
                raise OutputLimit
            result.append(data)
        return b"".join(result)

    try:
        async with asyncio.timeout(5):
            exceeded = False
            try:
                async with asyncio.TaskGroup() as tasks:
                    out = tasks.create_task(read(process.stdout))
                    err = tasks.create_task(read(process.stderr))
                    process.stdin.write(statement.encode())
                    try:
                        await process.stdin.drain()
                    except BrokenPipeError, ConnectionResetError:
                        pass
                    process.stdin.close()
            except* OutputLimit:
                exceeded = True
            if exceeded:
                raise OutputLimit
            await process.wait()
        return process.returncode or 0, out.result().decode(), err.result().decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def query(
    name: str, sql: str, *, candidate: bool = False
) -> tuple[int, str, str]:
    """Отправляет доверенную команду или единственную кандидатскую транзакцию."""
    return await communicate_sql(await start_psql(name, candidate=candidate), sql)


async def initialise(name: str, task_id: str, tables: JsonValue) -> None:
    """Пересоздаёт только фиксированную схему задачи; роли не имеют host-доступа."""
    if not isinstance(tables, dict) or set(tables) - set(SCHEMAS[task_id]):
        raise ValueError("unknown_sql_fixture_table")
    statements = [
        (
            "DROP SCHEMA IF EXISTS task CASCADE; CREATE "
            "SCHEMA task; SET search_path=task,pg_catalog;"
        )
    ]
    for table, columns in SCHEMAS[task_id].items():
        statements.append(f"CREATE TABLE task.{table} ({columns});")
        rows = tables.get(table, [])
        if not isinstance(rows, list) or len(rows) > 64:
            raise ValueError("invalid_sql_fixture_rows")
        for row in rows:
            if not isinstance(row, list):
                raise ValueError("invalid_sql_fixture_row")
            statements.append(
                f"INSERT INTO task.{table} VALUES ("
                + ",".join(literal(v) for v in row)
                + ");"
            )
    statements.append(
        "GRANT USAGE ON SCHEMA task TO candidate; GRANT "
        "SELECT ON ALL TABLES IN SCHEMA task TO "
        "candidate;"
    )
    if task_id.startswith("Y3"):
        statements.append("GRANT UPDATE ON task.counters TO candidate;")
        if task_id == "Y3-M":
            statements.append(
                "GRANT CREATE ON SCHEMA task TO candidate; GRANT "
                "INSERT ON task.applied,task.outbox TO candidate;"
            )
    code, _, _ = await query(name, "\n".join(statements))
    if code:
        raise RunnerUnavailable("sql_fixture_initialisation_failed")


def parse_rows(raw: str) -> list[JsonValue]:
    """JSON сохраняет числовые типы и порядок полей фактического результата."""
    rows = list(csv.reader(io.StringIO(raw)))
    if not rows:
        return []

    def exact_number(value: str) -> int | str:
        number = Decimal(value)
        return int(number) if number == number.to_integral_value() else str(number)

    return [json.loads(row[0], parse_float=exact_number) for row in rows[1:] if row]


async def select_case(
    name: str, source: str, scenario: dict[str, JsonValue]
) -> JsonValue:
    """Исполняет SELECT с native bind и запретом изменений таблиц."""
    params = scenario.get("params", {})
    if not isinstance(params, dict):
        raise ValueError("invalid_sql_parameters")
    try:
        statement, values = bind_query(source, params)
    except ValueError:
        return {"status": "candidate_error"}
    wrapped = (
        "SELECT row_to_json(candidate_row) FROM (\n" + statement + "\n) candidate_row\n"
    )
    script = (
        "BEGIN READ ONLY; SET LOCAL search_path=task,pg_catalog;\n"
        + statement
        + "\n\\gdesc\n\\echo V3_METADATA_END\n\\r\n"
        + wrapped
        + bind_values(values)
        + "\\g\nCOMMIT;\n"
    )
    code, output, error = await query(name, script, candidate=True)
    if code:
        return {"status": "review_required" if "57014" in error else "candidate_error"}
    metadata, result = output.split("V3_METADATA_END\n", 1)
    descriptions = list(csv.reader(io.StringIO(metadata)))
    return {
        "status": "completed",
        "rows": parse_rows(result),
        "columns": [row[0] for row in descriptions[1:]],
        "types": [row[1] for row in descriptions[1:]],
    }


def transaction_script(
    task_id: str, source: str, operation: dict[str, JsonValue]
) -> str:
    """Параметры операции связываются отдельно от присланного SQL."""
    if task_id == "Y3-M":
        source = "SELECT task.apply_event(:account_id,:event_id,:delta) AS status"
    statement, values = bind_query(source, operation)
    isolation = "SERIALIZABLE" if task_id == "Y3-M" else "READ COMMITTED"
    return (
        f"BEGIN ISOLATION LEVEL {isolation}; SET LOCAL search_path=task,pg_catalog;\n"
        + statement
        + "\n"
        + bind_values(values)
        + "\\g\n"
    )


def scalar_output(raw: str) -> JsonValue:
    rows = list(csv.reader(io.StringIO(raw)))
    if len(rows) != 2 or len(rows[1]) != 1:
        raise ValueError("sql_operation_must_return_one_scalar")
    value = rows[1][0]
    return int(value) if re.fullmatch(r"-?\d+", value) else value


async def state_snapshot(name: str, task_id: str) -> dict[str, JsonValue]:
    """Читает итог через доверенное соединение, независимо от ответа кандидата."""
    result: dict[str, JsonValue] = {}
    for table in SCHEMAS[task_id]:
        code, raw, _ = await query(
            name,
            f"SELECT row_to_json(t) FROM (SELECT * FROM task.{table} ORDER BY 1,2) t;",
        )
        if code:
            raise RunnerUnavailable("sql_state_read_failed")
        result[table] = parse_rows(raw)
    return result


async def retry_operation(
    name: str, task_id: str, source: str, operation: dict[str, JsonValue], index: int
) -> tuple[JsonValue, int]:
    """Повторяет всю SERIALIZABLE-транзакцию лишь при SQLSTATE 40001."""
    script = transaction_script(task_id, source, operation)
    retries = 0
    for attempt in range(5 if task_id == "Y3-M" else 1):
        process = await start_psql(
            name, candidate=True, application_name=f"v3-racer-{index}"
        )
        code, out, err = await communicate_sql(
            process,
            script + ("ROLLBACK;\n" if operation.get("rollback") else "COMMIT;\n"),
        )
        if code == 0:
            try:
                return scalar_output(out), retries
            except ValueError:
                return {"status": "candidate_error"}, retries
        if "40001" not in err or task_id != "Y3-M":
            return {
                "status": "environment_error"
                if "55P03" in err
                else ("review_required" if "57014" in err else "candidate_error")
            }, retries
        retries = attempt + 1
    return {
        "status": "environment_error",
        "reason": "serialization_retry_exhausted",
    }, retries


async def controlled_race(
    name: str, task_id: str, source: str, operations: list[dict[str, JsonValue]]
) -> tuple[list[JsonValue], int]:
    """Удерживает первую транзакцию до наблюдаемого блокирования других соединений."""
    first = await start_psql(name, candidate=True, application_name="v3-barrier-owner")
    assert first.stdin and first.stdout
    first.stdin.write(
        (
            transaction_script(task_id, source, operations[0])
            + "\\echo V3_BARRIER_READY\n"
        ).encode()
    )
    await first.stdin.drain()
    captured: list[bytes] = []
    racers: list[asyncio.Task[tuple[JsonValue, int]]] = []
    try:
        async with asyncio.timeout(3):
            while line := await first.stdout.readline():
                if line.strip() == b"V3_BARRIER_READY":
                    break
                captured.append(line)
            else:
                # Ошибочный SQL первого участника не является поломкой барьера.
                return [{"status": "candidate_error"}], 0
        racers = [
            asyncio.create_task(retry_operation(name, task_id, source, op, i + 1))
            for i, op in enumerate(operations[1:])
        ]
        # Ожидаем состояние PostgreSQL, а не предполагаемый порядок после sleep.
        async with asyncio.timeout(1):
            while True:
                code, raw, _ = await query(
                    name,
                    (
                        "SELECT count(*) FROM pg_stat_activity WHERE "
                        "application_name LIKE 'v3-racer-%' AND "
                        "wait_event_type='Lock';"
                    ),
                )
                if code:
                    raise RunnerUnavailable("sql_barrier_observation_failed")
                count = scalar_output(raw)
                if count == len(racers) or all(t.done() for t in racers):
                    break
                await asyncio.sleep(0)
        first.stdin.write(b"COMMIT;\n")
        await first.stdin.drain()
        first.stdin.close()
        await first.wait()
        results = await asyncio.gather(*racers)
        try:
            initial = scalar_output(b"".join(captured).decode())
        except ValueError:
            initial = {"status": "candidate_error"}
        return [initial, *(value for value, _ in results)], sum(
            retries for _, retries in results
        )
    finally:
        if first.returncode is None:
            first.kill()
            await first.wait()
        for racer in racers:
            if not racer.done():
                racer.cancel()
        if racers:
            await asyncio.gather(*racers, return_exceptions=True)


async def transaction_case(
    name: str, task_id: str, source: str, scenario: dict[str, JsonValue]
) -> JsonValue:
    """Исполняет Y3 и возвращает фактические ответы, состояния и повторы."""
    operations_raw = scenario.get("operations", [])
    if not isinstance(operations_raw, list) or not 1 <= len(operations_raw) <= 4:
        raise ValueError("invalid_sql_operations")
    operations: list[dict[str, JsonValue]] = []
    for value in operations_raw:
        if not isinstance(value, dict):
            raise ValueError("invalid_sql_operation")
        operations.append(value)
    if task_id == "Y3-M":
        try:
            statement, _ = bind_query(source, {})
        except ValueError:
            return {"status": "candidate_error"}
        code, _, _ = await query(
            name,
            "SET search_path=task,pg_catalog;\n" + statement + ";\n",
            candidate=True,
        )
        if code:
            return {"status": "candidate_error"}
    returns: list[JsonValue] = []
    retries = 0
    if scenario.get("concurrent") is True:
        try:
            returns, retries = await controlled_race(name, task_id, source, operations)
        except TimeoutError:
            return {
                "status": "environment_error",
                "reason": "transaction_barrier_timeout",
            }
    else:
        for i, operation in enumerate(operations):
            value, attempts = await retry_operation(name, task_id, source, operation, i)
            returns.append(value)
            retries += attempts
    failures = [
        r for r in returns if isinstance(r, dict) and r.get("status") != "completed"
    ]
    return {
        "status": failures[0].get("status", "candidate_error")
        if failures and isinstance(failures[0], dict)
        else "completed",
        "returns": returns,
        "state": await state_snapshot(name, task_id),
        "connections": len(operations) if scenario.get("concurrent") else 1,
        "serialization_retries": retries,
    }


async def execute_sql_v3(request: V3ExecutionRequest) -> V3ExecutionResult:
    """Контейнер уничтожается вместе с tmpfs при любом результате."""
    if request.language != "sql" or request.task_id not in SCHEMAS:
        raise ValueError("sql_task_not_allowed")
    if len(request.model_dump_json().encode()) > 131072:
        raise ValueError("input_too_large")
    name = f"aggratech-task-{uuid4().hex}"
    started = perf_counter()
    created = False
    outputs: list[JsonValue] = []
    status: ExecutionStatus = "completed"
    try:
        code, _ = await docker_control(*sql_create_command(name)[1:])
        if code:
            raise RunnerUnavailable("sql_container_creation_failed")
        created = True
        code, _ = await docker_control("start", name)
        if code:
            raise RunnerUnavailable("sql_container_start_failed")
        async with asyncio.timeout(45):
            for _ in range(40):
                code, _ = await docker_control(
                    "exec", name, "pg_isready", "-h", "/tmp", "-U", "evaluator"
                )
                if code == 0:
                    break
                await asyncio.sleep(0.05)
            else:
                raise RunnerUnavailable("sql_runtime_not_ready")
            code, _, _ = await query(
                name,
                (
                    "CREATE ROLE candidate LOGIN NOSUPERUSER "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION "
                    "NOBYPASSRLS CONNECTION LIMIT 4; REVOKE ALL ON "
                    "DATABASE postgres FROM PUBLIC; GRANT CONNECT ON "
                    "DATABASE postgres TO candidate; REVOKE CREATE ON"
                    " SCHEMA public FROM PUBLIC;"
                ),
            )
            if code:
                raise RunnerUnavailable("sql_role_initialisation_failed")
            for scenario in request.scenarios:
                await initialise(name, request.task_id, scenario.get("tables", {}))
                if request.task_id.startswith("Y3"):
                    # Состояния и управляемые транзакции реализуются тем же стендом.
                    outputs.append(
                        await transaction_case(
                            name, request.task_id, request.source, scenario
                        )
                    )
                else:
                    outputs.append(await select_case(name, request.source, scenario))
    except TimeoutError:
        status = "timeout"
    except OutputLimit:
        status = "output_limit"
    finally:
        if created:
            code, _ = await docker_control("rm", "--force", name)
            if code:
                raise RunnerUnavailable("sql_container_cleanup_failed")
    return V3ExecutionResult(
        status=status,
        outputs=outputs,
        runtime_image=POSTGRES_IMAGE,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
