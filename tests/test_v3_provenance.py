"""Происхождение runner и границы доверенного ZIP-адаптера; без оценок людей."""

import io
import zipfile
from pathlib import Path

import httpx
import pytest

from app.assessment import v3_admission
from app.assessment.runner import (
    PYTHON_IMAGE,
    RunnerClient,
    RunnerUnavailable,
    V3ExecutionRequest,
    V3ExecutionResult,
    runtime_executor_hash,
)
from app.assessment.v3_models import V3TaskGrade
from runner.v3_adapters import AdapterSession


@pytest.mark.parametrize("hash_kind", ["actual", "missing", "stale"])
async def test_actual_controller_hash_is_required(hash_kind: str) -> None:
    expected = runtime_executor_hash()
    value = (
        expected
        if hash_kind == "actual"
        else None
        if hash_kind == "missing"
        else "0" * 64
    )

    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=V3ExecutionResult(
                status="completed",
                runtime_image=PYTHON_IMAGE,
                outputs=[{}],
                duration_ms=1,
                executor_hash=value,
            ).model_dump(),
        )

    client = object.__new__(RunnerClient)
    client.client = httpx.AsyncClient(
        base_url="https://runner.test", transport=httpx.MockTransport(response)
    )
    request = V3ExecutionRequest(
        task_id="X1-PY-J", language="python", source="test-only", scenarios=[{}]
    )
    try:
        if hash_kind == "actual":
            assert (await client.execute_v3(request)).executor_hash == expected
        else:
            with pytest.raises(RunnerUnavailable, match="executor_version_mismatch"):
                await client.execute_v3(request)
    finally:
        await client.close()


@pytest.mark.parametrize("sizes", [[100000], [40000, 40000]])
def test_zip_adapter_bounds_total_expansion_before_allocating(
    sizes: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, size in enumerate(sizes):
            archive.writestr(str(index), b"x" * size)
    session = AdapterSession({})
    session.temp = buffer.getvalue()

    def forbidden(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("unbounded ZipFile.read must never be called")

    monkeypatch.setattr(zipfile.ZipFile, "read", forbidden)
    with pytest.raises(ValueError, match="fixture_archive_too_large"):
        session.inspect_archive({})


async def test_changed_evaluator_during_check_cannot_be_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hashes = iter(["0" * 64, "1" * 64])
    monkeypatch.setattr(v3_admission, "evaluator_hash_v3", lambda: next(hashes))

    async def grade(*args: object, **kwargs: object) -> V3TaskGrade:
        return V3TaskGrade(status="completed", task_score=4)

    async def unused(request: V3ExecutionRequest) -> V3ExecutionResult:
        raise AssertionError("unit guard does not execute code")

    monkeypatch.setattr(v3_admission, "grade_v3", grade)
    report = await v3_admission.check_bank_v3(Path("bank/private/v3.json"), unused)
    assert report.grader_hash == "0" * 64
    assert report.technical_status == "incomplete"
    assert report.admission_status == "not_admitted"
    assert "evaluator_changed_during_check" in report.technical_errors
