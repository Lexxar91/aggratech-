import asyncio
import json
import os

from app.assessment.runner import PYTHON_IMAGE, ExecutionRequest
from runner.sandbox import SandboxPolicy, docker_control, execute, task_scope


async def inspect_service(service: str) -> dict[str, object]:
    """Читает фактическую конфигурацию одного контейнера текущего Compose."""
    project = os.environ.get("RUNNER_COMPOSE_PROJECT", "aggratech-stage1")
    code, output = await docker_control(
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        f"label=com.docker.compose.service={service}",
    )
    identifiers = output.decode().splitlines()
    if code or len(identifiers) != 1:
        raise RuntimeError(f"expected_one_service:{service}")
    code, output = await docker_control("inspect", identifiers[0])
    if code:
        raise RuntimeError("inspect_failed")
    values: list[dict[str, object]] = json.loads(output)
    return values[0]


def mapping(value: object) -> dict[str, object]:
    """Проверяет объект Docker inspect без неограниченного Any."""
    if not isinstance(value, dict):
        raise ValueError("expected_object")
    return {str(key): item for key, item in value.items()}


def sequence(value: object) -> list[object]:
    """Проверяет массив Docker inspect; null означает отсутствие параметров."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("expected_array")
    return list(value)


async def run() -> None:
    """Проверяет inspect настоящей задачи и отсутствие socket у API/worker."""
    services = {
        name: await inspect_service(name)
        for name in ("api", "worker", "runner-controller", "db")
    }
    for name in ("api", "worker"):
        host = mapping(services[name]["HostConfig"])
        assert host["Privileged"] is False
        assert not any("docker.sock" in str(item) for item in sequence(host["Binds"]))
    controller = services["runner-controller"]
    assert mapping(controller["HostConfig"])["Privileged"] is False
    config = mapping(controller["Config"])
    assert not any(str(item).startswith("APP_") for item in sequence(config["Env"]))
    control_networks = mapping(mapping(controller["NetworkSettings"])["Networks"])
    for name in ("api", "db"):
        networks = mapping(mapping(services[name]["NetworkSettings"])["Networks"])
        assert not control_networks.keys() & networks.keys()
    task = asyncio.create_task(
        execute(
            ExecutionRequest(
                source=(
                    "def solve(x):\n    import time\n    time.sleep(2)\n    return 42"
                ),
                inputs=[None],
            ),
            SandboxPolicy(),
        )
    )
    try:
        identifier = ""
        for _ in range(30):
            code, output = await docker_control(
                "ps",
                "-q",
                "--filter",
                f"label=aggratech.runner.scope={task_scope()}",
            )
            identifiers = output.decode().splitlines()
            assert code == 0 and len(identifiers) <= 1
            if identifiers:
                identifier = identifiers[0]
                break
            await asyncio.sleep(0.1)
        assert identifier, "live_task_not_found"
        code, output = await docker_control("inspect", identifier)
        assert code == 0
        container = mapping(json.loads(output)[0])
        host = mapping(container["HostConfig"])
        config = mapping(container["Config"])
        assert host["Privileged"] is False and host["ReadonlyRootfs"] is True
        assert host["NetworkMode"] == "none" and config["User"] == "65534:65534"
        assert host["CapDrop"] == ["ALL"] and not host["CapAdd"]
        assert "no-new-privileges:true" in sequence(host["SecurityOpt"])
        assert "seccomp=unconfined" not in sequence(host["SecurityOpt"])
        assert host["Memory"] == host["MemorySwap"] == 134217728
        assert host["NanoCpus"] == 500000000 and host["PidsLimit"] == 32
        assert not host["Binds"] and not host.get("Mounts") and not container["Mounts"]
        assert mapping(host["Tmpfs"]) == {"/tmp": "rw,noexec,nosuid,nodev,size=16m"}
        assert config["Image"] == PYTHON_IMAGE
        assert not any(str(item).startswith("APP_") for item in sequence(config["Env"]))
    finally:
        result = await task
    assert result.status == "completed" and result.outputs == [42]
    code, output = await docker_control(
        "ps", "-aq", "--filter", f"label=aggratech.runner.scope={task_scope()}"
    )
    assert code == 0 and not output.strip(), "task_cleanup_failed"
    print(json.dumps({"docker_limited_inspect": "passed", "cleanup": "passed"}))


if __name__ == "__main__":
    asyncio.run(run())
