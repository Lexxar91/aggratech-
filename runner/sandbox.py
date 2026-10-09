import asyncio
import json
import os
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from app.assessment.runner import (
    PYTHON_IMAGE,
    ExecutionRequest,
    ExecutionResult,
    RunnerUnavailable,
)

# Этот код выполняется исключительно внутри одноразового контейнера задачи.
WRAPPER = """
import json, sys
request = json.load(sys.stdin)
outputs = []
for value in request['inputs']:
    namespace = {'__name__': '__candidate__'}
    try:
        exec(compile(request['source'], '<candidate>', 'exec'), namespace)
        outputs.append(namespace['solve'](value))
    except Exception:
        sys.exit(10)
print(json.dumps(outputs, allow_nan=False, separators=(',', ':')))
"""


@dataclass(frozen=True)
class SandboxPolicy:
    """Фиксированные ограничения исполнения, не задаваемые запросом кандидата."""

    runtime: str = "runc"
    timeout_seconds: float = 5
    output_bytes: int = 65536
    input_bytes: int = 131072


def task_scope() -> str:
    """Разделяет задачи независимых Compose-проектов на одном Docker daemon."""
    return os.environ.get("RUNNER_COMPOSE_PROJECT", "aggratech-stage1")


def create_command(name: str, policy: SandboxPolicy) -> list[str]:
    """Создаёт контейнер без сети, секретов, томов хоста и привилегий."""
    if policy.runtime != "runc":
        raise ValueError("runtime_not_allowed")
    return [
        "docker",
        "create",
        "--name",
        name,
        "--interactive",
        "--network",
        "none",
        "--runtime",
        policy.runtime,
        "--read-only",
        "--user",
        "65534:65534",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "128m",
        "--memory-swap",
        "128m",
        "--cpus",
        "0.5",
        "--pids-limit",
        "32",
        "--ulimit",
        "nofile=64:64",
        "--ulimit",
        "core=0:0",
        "--ulimit",
        "fsize=1048576:1048576",
        "--log-driver",
        "none",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,size=16m",
        "--label",
        "aggratech.runner=true",
        "--label",
        f"aggratech.runner.scope={task_scope()}",
        "--workdir",
        "/tmp",
        PYTHON_IMAGE,
        "python",
        "-I",
        "-B",
        "-c",
        WRAPPER,
    ]


async def docker_control(*arguments: str) -> tuple[int, bytes]:
    """Выполняет фиксированную команду Docker с ограниченным ожиданием."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), timeout=15)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise RunnerUnavailable("docker_control_timeout") from None
    return process.returncode or 0, output


class OutputLimit(RuntimeError):
    """Совокупный stdout/stderr задачи превысил допустимый объём."""


async def recover_tasks() -> None:
    """Удаляет только задачи этого runner, оставшиеся после аварии контроллера."""
    code, output = await docker_control(
        "ps", "-aq", "--filter", f"label=aggratech.runner.scope={task_scope()}"
    )
    if code:
        raise RunnerUnavailable("docker_unavailable")
    for identifier in output.decode("ascii").splitlines():
        if not 12 <= len(identifier) <= 64 or any(
            character not in "0123456789abcdef" for character in identifier
        ):
            raise RunnerUnavailable("invalid_container_identifier")
        code, _ = await docker_control("rm", "--force", identifier)
        if code:
            raise RunnerUnavailable("startup_cleanup_failed")


async def execute(request: ExecutionRequest, policy: SandboxPolicy) -> ExecutionResult:
    """Исполняет код в чистом контейнере и безусловно удаляет его после проверки."""
    data = request.model_dump_json().encode()
    if len(data) > policy.input_bytes:
        raise ValueError("input_too_large")
    name = f"aggratech-task-{uuid4().hex}"
    started = perf_counter()
    status = "completed"
    outputs: list[object] = []
    process: asyncio.subprocess.Process | None = None
    created = False
    try:
        command = create_command(name, policy)
        code, _ = await docker_control(*command[1:])
        if code != 0:
            raise RunnerUnavailable("container_creation_failed")
        created = True
        process = await asyncio.create_subprocess_exec(
            "docker",
            "start",
            "--attach",
            "--interactive",
            name,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin and process.stdout and process.stderr
        total = 0

        async def read_limited(stream: asyncio.StreamReader) -> bytes:
            nonlocal total
            chunks: list[bytes] = []
            while chunk := await stream.read(4096):
                total += len(chunk)
                if total > policy.output_bytes:
                    raise OutputLimit
                chunks.append(chunk)
            return b"".join(chunks)

        async def communicate() -> bytes:
            assert process is not None and process.stdin
            assert process.stdout and process.stderr
            async with asyncio.TaskGroup() as group:
                stdout = group.create_task(read_limited(process.stdout))
                group.create_task(read_limited(process.stderr))
                process.stdin.write(data)
                try:
                    await process.stdin.drain()
                except BrokenPipeError, ConnectionResetError:
                    pass
                process.stdin.close()
            await process.wait()
            return stdout.result()

        try:
            async with asyncio.timeout(policy.timeout_seconds):
                try:
                    raw = await communicate()
                except* OutputLimit:
                    status = "output_limit"
        except TimeoutError:
            status = "timeout"
        if status == "completed":
            if process.returncode == 10:
                status = "candidate_error"
            elif process.returncode != 0:
                status = "runtime_error"
            else:
                try:
                    decoded = json.loads(raw)
                    if not isinstance(decoded, list):
                        raise ValueError("invalid_output")
                    outputs = decoded
                except ValueError, UnicodeDecodeError:
                    status = "candidate_error"
    finally:
        # Сначала удаляется контейнер, чтобы тайм-аут Docker CLI не оставил задачу.
        code = 0
        if created:
            code, _ = await docker_control("rm", "--force", name)
        if process is not None:
            if process.returncode is None:
                process.kill()

            async def discard(stream: asyncio.StreamReader) -> None:
                # Отменённый reader оставляет pipe заполненным: wait() может
                # зависнуть даже после выхода CLI. Остаток удаляется без накопления.
                while await stream.read(4096):
                    pass

            assert process.stdout and process.stderr
            try:
                async with asyncio.timeout(3):
                    async with asyncio.TaskGroup() as group:
                        group.create_task(discard(process.stdout))
                        group.create_task(discard(process.stderr))
                        group.create_task(process.wait())
            except TimeoutError:
                raise RunnerUnavailable("attach_cleanup_failed") from None
        if code != 0:
            raise RunnerUnavailable("container_cleanup_failed")
    return ExecutionResult.model_validate(
        {
            "status": status,
            "outputs": outputs,
            "runtime_image": PYTHON_IMAGE,
            "duration_ms": round((perf_counter() - started) * 1000, 2),
        }
    )
