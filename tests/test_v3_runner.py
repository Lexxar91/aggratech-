"""Реальный v3 runner: изоляция Python, исполнение SQL и безопасные границы."""

import pytest
from pydantic import JsonValue

from app.assessment.runner import RunnerClient, V3ExecutionRequest
from app.core.config import Settings
from runner.v3_sql import sql_create_command


def test_sql_policy_never_mounts_host_or_enables_privileged() -> None:
    command = sql_create_command("test")
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--user") + 1] == "65534:65534"
    assert command[command.index("--pids-limit") + 1] == "32"
    assert "--read-only" in command and "no-new-privileges:true" in command
    assert not {"--privileged", "--volume", "--mount", "--env"}.intersection(command)
    assert "seccomp=unconfined" not in command
    assert any(value.startswith("/var/lib/postgresql:") for value in command)


@pytest.mark.runner
async def test_python_v3_real_isolation_and_cleanup() -> None:
    source = """
def totals(rows, paid_only=False):
    import os, socket
    status = open('/proc/self/status').read()
    try:
        open('/root-probe', 'w').close()
        root_writable = True
    except OSError:
        root_writable = False
    try:
        socket.create_connection(('1.1.1.1',443),timeout=.2).close()
        network = True
    except OSError:
        network = False
    return {'uid':os.getuid(), 'root_writable':root_writable, 'network':network,
      'memory':open('/sys/fs/cgroup/memory.max').read().strip(),
      'pids':open('/sys/fs/cgroup/pids.max').read().strip(),
      'cpu':open('/sys/fs/cgroup/cpu.max').read().strip(),
      'caps': 'CapEff:\\t0000000000000000' in status,
      'seccomp':'Seccomp:\\t2' in status,'no_new_privs':'NoNewPrivs:\\t1' in status,
      'secret':'APP_DATABASE_URL' in os.environ,
      'closed_files':any(os.path.exists(p) for p in ['/opt/aggratech',
        '/run/runner-server','/var/run/docker.sock']),
      'tmp_marker':os.path.exists('/tmp/v3-marker')}
"""
    client = RunnerClient(Settings())
    scenario: dict[str, JsonValue] = {
        "invocations": [{"function": "totals", "args": [[], False]}]
    }
    try:
        result = await client.execute_v3(
            V3ExecutionRequest(
                task_id="X1-PY-J",
                language="python",
                source=source,
                scenarios=[scenario],
            )
        )
        assert result.status == "completed"
        observation = result.outputs[0]
        assert isinstance(observation, dict)
        returns = observation["return_values"]
        assert isinstance(returns, list) and isinstance(returns[0], dict)
        value = returns[0]
        assert value["uid"] == 65534 and value["memory"] == "134217728"
        assert value["pids"] == "32" and value["cpu"] == "50000 100000"
        assert value["caps"] is value["seccomp"] is value["no_new_privs"] is True
        assert all(
            value[k] is False
            for k in [
                "root_writable",
                "network",
                "secret",
                "closed_files",
                "tmp_marker",
            ]
        )
        written = await client.execute_v3(
            V3ExecutionRequest(
                task_id="X1-PY-J",
                language="python",
                source=(
                    "def totals(*args):\n "
                    "open('/tmp/v3-marker','w').close()\n return True"
                ),
                scenarios=[scenario],
            )
        )
        assert written.status == "completed"
        clean = await client.execute_v3(
            V3ExecutionRequest(
                task_id="X1-PY-J",
                language="python",
                source=(
                    "def totals(*args):\n import os\n return "
                    "os.path.exists('/tmp/v3-marker')"
                ),
                scenarios=[scenario],
            )
        )
        assert clean.status == "completed"
        observed = clean.outputs[0]
        assert isinstance(observed, dict) and observed["return_values"] == [False]
    finally:
        await client.close()


@pytest.mark.runner
async def test_postgres18_runs_alternative_and_denies_os_files() -> None:
    client = RunnerClient(Settings())
    scenario: dict[str, JsonValue] = {
        "tables": {"payments": [["A", 2, "paid"], ["B", None, "paid"]]},
        "params": {"paid_only": True},
    }
    try:
        result = await client.execute_v3(
            V3ExecutionRequest(
                task_id="X1-SQL-J",
                language="sql",
                source=(
                    "SELECT team, COALESCE(SUM(amount),0) AS total "
                    "FROM payments WHERE NOT :paid_only OR "
                    "status='paid' GROUP BY team ORDER BY team"
                ),
                scenarios=[scenario],
            )
        )
        assert result.status == "completed"
        observation = result.outputs[0]
        assert isinstance(observation, dict) and observation["status"] == "completed"
        assert observation["rows"] == [
            {"team": "A", "total": 2},
            {"team": "B", "total": 0},
        ]
        assert observation["columns"] == ["team", "total"]
        denied = await client.execute_v3(
            V3ExecutionRequest(
                task_id="X1-SQL-J",
                language="sql",
                source="SELECT pg_read_file('/etc/passwd') AS secret",
                scenarios=[scenario],
            )
        )
        assert denied.status == "completed"
        bad = denied.outputs[0]
        assert isinstance(bad, dict) and bad["status"] == "candidate_error"
        assert "secret" not in bad and "rows" not in bad
    finally:
        await client.close()


@pytest.mark.runner
@pytest.mark.parametrize(
    "source,status",
    [
        ("def totals(*args):\n while True: pass", "timeout"),
        (
            (
                "def totals(*args):\n import sys\n "
                "sys.stderr.write('x'*1000000)\n return []"
            ),
            "output_limit",
        ),
    ],
)
async def test_python_v3_time_and_output_limits(source: str, status: str) -> None:
    client = RunnerClient(Settings())
    try:
        result = await client.execute_v3(
            V3ExecutionRequest(
                task_id="X1-PY-J",
                language="python",
                source=source,
                scenarios=[
                    {"invocations": [{"function": "totals", "args": [[], False]}]}
                ],
            )
        )
        assert result.status == status
    finally:
        await client.close()
