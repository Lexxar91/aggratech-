import errno
import ssl
from time import monotonic

import httpx
import pytest

from app.assessment.runner import ExecutionRequest, RunnerClient
from app.core.config import Settings

pytestmark = pytest.mark.runner


async def test_real_isolation_and_fresh_state() -> None:
    client = RunnerClient(Settings())
    source = """
def solve(data):
    import ctypes, os, socket, time
    try:
        open('/root-write-probe', 'w').close()
        writable = True
    except OSError:
        writable = False
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=0.2).close()
        network = True
    except OSError:
        network = False
    status = open('/proc/self/status').read()
    library = ctypes.CDLL(None, use_errno=True)
    mount_result = library.mount(b'none', b'/tmp', b'tmpfs', 0, None)
    mount_error = ctypes.get_errno()
    started = time.monotonic()
    while time.monotonic() - started < 1.2:
        pass
    cpu_stats = open('/sys/fs/cgroup/cpu.stat').read().splitlines()
    throttled = int(next(line.split()[1] for line in cpu_stats
                        if line.startswith('nr_throttled ')))
    return {'uid': os.getuid(), 'root_writable': writable, 'network': network,
            'database_secret': 'APP_DATABASE_URL' in os.environ,
            'docker_socket': os.path.exists('/var/run/docker.sock'),
            'no_new_privileges': 'NoNewPrivs:\\t1' in status,
            'seccomp': 'Seccomp:\\t2' in status,
            'capabilities_dropped': 'CapEff:\\t0000000000000000' in status,
            'mount_result': mount_result, 'mount_error': mount_error,
            'cpu_throttled': throttled > 0,
            'interfaces': sorted(os.listdir('/sys/class/net')),
            'routes': len(open('/proc/net/route').read().splitlines()),
            'db_dns': 'db' in open('/etc/hosts').read(),
            'grader_files': any(os.path.exists(p) for p in
                ['/opt/aggratech', '/run/runner-client', '/run/runner-server',
                 '/bank/private/stage1.json']),
            'mounts': open('/proc/self/mountinfo').read(),
            'memory': open('/sys/fs/cgroup/memory.max').read().strip(),
            'pids': open('/sys/fs/cgroup/pids.max').read().strip(),
            'cpu': open('/sys/fs/cgroup/cpu.max').read().strip()}
"""
    try:
        result = await client.execute(ExecutionRequest(source=source, inputs=[None]))
        assert result.status == "completed"
        value = result.outputs[0]
        assert isinstance(value, dict)
        assert value["uid"] == 65534 and value["memory"] == "134217728"
        assert value["pids"] == "32" and value["cpu"] == "50000 100000"
        assert value["no_new_privileges"] is True and value["seccomp"] is True
        assert value["capabilities_dropped"] is True
        assert value["mount_result"] == -1 and value["mount_error"] == errno.EPERM
        assert value["cpu_throttled"] is True
        assert value["interfaces"] == ["lo"] and value["routes"] == 1
        mounts = value["mounts"]
        assert isinstance(mounts, str) and " /tmp " in mounts and " - tmpfs " in mounts
        for key in (
            "root_writable",
            "network",
            "database_secret",
            "docker_socket",
            "db_dns",
            "grader_files",
        ):
            assert value[key] is False
        write = await client.execute(
            ExecutionRequest(
                source=(
                    "def solve(x):\n"
                    "    open('/tmp/state-marker', 'w').write('state')\n"
                    "    return True"
                ),
                inputs=[None],
            )
        )
        read = await client.execute(
            ExecutionRequest(
                source=(
                    "def solve(x):\n    import os\n"
                    "    return os.path.exists('/tmp/state-marker')"
                ),
                inputs=[None],
            )
        )
        assert write.status == "completed" and read.outputs == [False]
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("source", "status"),
    [
        ("def solve(x):\n    while True: pass", "timeout"),
        ("def solve(x):\n    print('x' * 1000000)\n    return None", "output_limit"),
        (
            "def solve(x):\n    import sys\n"
            "    print('x' * 35000)\n    print('y' * 35000, file=sys.stderr)\n"
            "    return None",
            "output_limit",
        ),
    ],
)
async def test_real_resource_limits(source: str, status: str) -> None:
    client = RunnerClient(Settings())
    try:
        started = monotonic()
        result = await client.execute(ExecutionRequest(source=source, inputs=[None]))
        assert result.status == status
        assert monotonic() - started < 12
    finally:
        await client.close()


async def test_real_memory_and_process_limits() -> None:
    client = RunnerClient(Settings())
    try:
        memory = await client.execute(
            ExecutionRequest(
                source="def solve(x):\n    return len(bytearray(1024 * 1024 * 512))",
                inputs=[None],
            )
        )
        assert memory.status in ("candidate_error", "runtime_error")
        forks = await client.execute(
            ExecutionRequest(
                source="""
def solve(x):
    import os, signal, time
    children = []
    try:
        for _ in range(64):
            try:
                pid = os.fork()
            except OSError:
                return {'limited': True, 'children': len(children)}
            if pid == 0:
                time.sleep(60)
                os._exit(0)
            children.append(pid)
        return {'limited': False, 'children': len(children)}
    finally:
        for pid in children:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
""",
                inputs=[None],
            )
        )
        assert forks.status == "completed"
        value = forks.outputs[0]
        assert isinstance(value, dict) and value["limited"] is True
    finally:
        await client.close()


async def test_mtls_rejects_missing_client_certificate() -> None:
    settings = Settings()
    assert settings.runner_url is not None and settings.runner_ca is not None
    context = ssl.create_default_context(cafile=str(settings.runner_ca))
    async with httpx.AsyncClient(verify=context, trust_env=False, timeout=10) as client:
        with pytest.raises(httpx.HTTPError):
            await client.post(
                settings.runner_url + "/execute",
                json={
                    "source": "def solve(x): return x",
                    "inputs": [1],
                },
            )


async def test_controller_rejects_docker_options_and_raw_commands() -> None:
    client = RunnerClient(Settings())
    try:
        for option, value in (
            ("image", "alpine"),
            ("privileged", True),
            ("mounts", ["/:/host"]),
            ("network", "host"),
            ("command", ["sh"]),
            ("security_opt", ["seccomp=unconfined"]),
            ("runtime", "custom"),
            ("memory", "1g"),
            ("timeout_seconds", 100),
        ):
            response = await client.client.post(
                "/execute",
                json={"source": "def solve(x): return x", "inputs": [1], option: value},
            )
            assert response.status_code == 422
        response = await client.client.post("/containers/create", json={})
        assert response.status_code == 404
        result = await client.execute(
            ExecutionRequest(source="def solve(x): return x", inputs=[42])
        )
        assert result.status == "completed" and result.outputs == [42]
    finally:
        await client.close()


async def test_temporary_area_limit_and_cleanup_after_failures() -> None:
    client = RunnerClient(Settings())
    try:
        result = await client.execute(
            ExecutionRequest(
                source="""
def solve(x):
    import errno, os
    open('/tmp/marker', 'w').write('marker')
    try:
        for i in range(24):
            with open('/tmp/file-' + str(i), 'wb') as output:
                output.write(b'x' * (1024 * 1024))
        return False
    except OSError as error:
        return error.errno == errno.ENOSPC
""",
                inputs=[None],
            )
        )
        assert result.status == "completed" and result.outputs == [True]
        for source, expected in (
            (
                "def solve(x):\n    raise ValueError('candidate error')",
                "candidate_error",
            ),
            (
                "def solve(x):\n    open('/tmp/marker', 'w').close()\n"
                "    while True: pass",
                "timeout",
            ),
        ):
            result = await client.execute(
                ExecutionRequest(source=source, inputs=[None])
            )
            assert result.status == expected
        fresh = await client.execute(
            ExecutionRequest(
                source="def solve(x):\n    import os\n    return os.listdir('/tmp')",
                inputs=[None],
            )
        )
        assert fresh.status == "completed" and fresh.outputs == [[]]
    finally:
        await client.close()
