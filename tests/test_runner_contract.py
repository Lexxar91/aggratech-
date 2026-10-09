import pytest
from pydantic import ValidationError

from app.assessment.runner import (
    PYTHON_IMAGE,
    ExecutionRequest,
    RunnerClient,
    RunnerUnavailable,
)
from app.core.config import Settings
from runner.sandbox import SandboxPolicy, create_command
from runner.server import parse_request


def test_sandbox_policy_is_fixed_and_does_not_mount_host_or_disable_seccomp() -> None:
    command = create_command("test-container", SandboxPolicy())
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "128m"
    assert command[command.index("--pids-limit") + 1] == "32"
    assert command[command.index("--user") + 1] == "65534:65534"
    assert "--read-only" in command and "ALL" in command
    assert "no-new-privileges:true" in command and PYTHON_IMAGE in command
    assert not {"--privileged", "--volume", "--mount", "--env"}.intersection(command)
    assert "seccomp=unconfined" not in command
    with pytest.raises(ValueError):
        create_command("test", SandboxPolicy(runtime="custom"))


@pytest.mark.parametrize(
    "body",
    [
        b'{"source":"x","source":"y","inputs":[null]}',
        b'{"source":"x","inputs":[NaN]}',
        b'{"source":"x","inputs":[1e999]}',
        b'{"source":"x","inputs":[null],"image":"unsafe"}',
        b'{"source":"x","inputs":[null],"privileged":true}',
        b'{"source":"x","inputs":[null],"volumes":["/:/host"]}',
        b'{"source":"x","inputs":[]}',
    ],
)
def test_execution_boundary_rejects_unsafe_or_unsupported_input(body: bytes) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_request(body)


def test_unconfigured_runner_never_executes_in_app_process() -> None:
    with pytest.raises(RunnerUnavailable):
        RunnerClient(Settings(runner_url=None))
    assert ExecutionRequest(source="def solve(x): return x", inputs=[1]).inputs == [1]
