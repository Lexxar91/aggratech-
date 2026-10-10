import asyncio
import hashlib
import json
import ssl
from math import isfinite
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.core.config import Settings

PYTHON_IMAGE = (
    "python:3.14.4-slim@sha256:"
    "2ca02f32b4d9d893863367ce07ec1972819f476dd38d8612f2a9cb6a41cbb727"
)
POSTGRES_IMAGE = (
    "postgres:18-bookworm@sha256:"
    "afc7e2d441324c0388fa80c3d24f733b4194a4eb7f47dd8ee2b08eb1a24a647c"
)
POSTGRES_VERSION = "18.6"
ExecutionStatus = Literal[
    "completed", "candidate_error", "timeout", "output_limit", "runtime_error"
]


def runtime_executor_hash() -> str:
    """Связывает ответ mTLS controller с установленными адаптерами и кодом."""
    paths = (
        "app/assessment/runner.py",
        "app/core/config.py",
        "runner/sandbox.py",
        "runner/server.py",
        "runner/v3_python.py",
        "runner/v3_sql.py",
        "runner/v3_adapters.py",
    )
    value = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class V3ExecutionRequest(BaseModel):
    """Закрытый runner получает только ответ и сценарии, без эталонных ожиданий."""

    model_config = ConfigDict(extra="forbid", strict=True)
    task_id: str = Field(pattern=r"^[XY][1-6](?:-(?:PY|SQL))?-[JM]$")
    language: Literal["python", "sql"]
    source: str = Field(min_length=1, max_length=32768)
    scenarios: list[dict[str, JsonValue]] = Field(min_length=1, max_length=16)

    @field_validator("source")
    @classmethod
    def bounded_source(cls, value: str) -> str:
        """Ограничивает именно объём передаваемых байтов."""
        if len(value.encode()) > 32768:
            raise ValueError("source_too_large")
        return value

    @field_validator("scenarios")
    @classmethod
    def no_closed_expectations(
        cls, values: list[dict[str, JsonValue]]
    ) -> list[dict[str, JsonValue]]:
        """Ожидания, рубрики и решения не являются частью протокола исполнения."""
        if any(
            set(value) & {"expected", "assertions", "rubric", "reference", "solutions"}
            for value in values
        ):
            raise ValueError("closed_material_in_execution_request")

        def finite(value: JsonValue) -> None:
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("non_finite_input")
            if isinstance(value, (list, dict)):
                for item in value.values() if isinstance(value, dict) else value:
                    finite(item)

        for value in values:
            finite(value)
        return values


class V3ExecutionResult(BaseModel):
    """Наблюдения стенда отделены от сравнения с закрытыми ожиданиями."""

    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal[
        "completed", "candidate_error", "timeout", "output_limit", "runtime_error"
    ]
    outputs: list[JsonValue] = Field(default_factory=list, max_length=16)
    runtime_image: str
    duration_ms: float = Field(ge=0)
    executor_hash: str | None = None


class ExecutionRequest(BaseModel):
    """Ограниченный запрос: только код и JSON-входы, без образов и команд Docker."""

    model_config = ConfigDict(extra="forbid", strict=True)
    source: str = Field(min_length=1, max_length=32768)
    inputs: list[JsonValue] = Field(min_length=1, max_length=16)

    @field_validator("source")
    @classmethod
    def source_size(cls, value: str) -> str:
        """Ограничивает байты исходного кода, а не только число символов."""
        if len(value.encode("utf-8")) > 32768:
            raise ValueError("source_too_large")
        return value

    @field_validator("inputs")
    @classmethod
    def finite_inputs(cls, values: list[JsonValue]) -> list[JsonValue]:
        """Отклоняет бесконечности, включая переполнение JSON-числа 1e999."""

        def check(value: JsonValue) -> None:
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("non_finite_input")
            if isinstance(value, list):
                for item in value:
                    check(item)
            elif isinstance(value, dict):
                for item in value.values():
                    check(item)

        for value in values:
            check(value)
        return values


class ExecutionResult(BaseModel):
    """Технический результат исполнения без эталонов и выставления грейда."""

    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal[
        "completed", "candidate_error", "timeout", "output_limit", "runtime_error"
    ]
    outputs: list[JsonValue] = Field(default_factory=list, max_length=16)
    runtime_image: str
    duration_ms: float = Field(ge=0)


class RunnerUnavailable(RuntimeError):
    """Инфраструктурный сбой, который не оценивает навыки кандидата."""


class RunnerClient:
    """Обращается к отдельному runner по HTTPS с взаимной аутентификацией."""

    def __init__(self, settings: Settings) -> None:
        if not settings.runner_url or not settings.runner_url.startswith("https://"):
            raise RunnerUnavailable("runner_https_not_configured")
        if not all(
            (
                settings.runner_ca,
                settings.runner_client_certificate,
                settings.runner_client_key,
            )
        ):
            raise RunnerUnavailable("runner_tls_not_configured")
        assert settings.runner_ca is not None
        assert settings.runner_client_certificate is not None
        assert settings.runner_client_key is not None
        context = ssl.create_default_context(cafile=str(settings.runner_ca))
        context.load_cert_chain(
            str(settings.runner_client_certificate), str(settings.runner_client_key)
        )
        self.client = httpx.AsyncClient(
            base_url=settings.runner_url,
            verify=context,
            trust_env=False,
            timeout=settings.runner_timeout_seconds,
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Возвращает проверенный технический результат либо ошибку инфраструктуры."""
        try:
            async with self.client.stream(
                "POST",
                "/execute",
                content=request.model_dump_json(),
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 131072:
                        raise RunnerUnavailable("runner_response_too_large")
                    chunks.append(chunk)
                result = ExecutionResult.model_validate_json(b"".join(chunks))
        except (httpx.HTTPError, ValueError) as error:
            raise RunnerUnavailable("runner_unavailable_or_invalid_response") from error
        if result.runtime_image != PYTHON_IMAGE:
            raise RunnerUnavailable("unexpected_runtime_image")
        if result.status == "completed" and len(result.outputs) != len(request.inputs):
            raise RunnerUnavailable("runner_output_count_mismatch")
        return result

    async def close(self) -> None:
        """Закрывает соединения независимо от результата проверки."""
        await self.client.aclose()

    async def execute_v3(self, request: V3ExecutionRequest) -> V3ExecutionResult:
        """Исполняет v3 на фиксированном runtime, не передавая выбор образа клиенту."""
        try:
            async with self.client.stream(
                "POST",
                "/execute-v3",
                content=request.model_dump_json(),
                headers={"Content-Type": "application/json"},
                timeout=60,
            ) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 131072:
                        raise RunnerUnavailable("runner_response_too_large")
                    chunks.append(chunk)
                result = V3ExecutionResult.model_validate_json(b"".join(chunks))
        except (httpx.HTTPError, ValueError) as error:
            raise RunnerUnavailable(
                "runner_v3_unavailable_or_invalid_response"
            ) from error
        expected_image = (
            PYTHON_IMAGE if request.language == "python" else POSTGRES_IMAGE
        )
        if result.runtime_image != expected_image:
            raise RunnerUnavailable("unexpected_runtime_image")
        if result.executor_hash != await asyncio.to_thread(runtime_executor_hash):
            raise RunnerUnavailable("runner_executor_version_mismatch")
        if result.status == "completed" and len(result.outputs) != len(
            request.scenarios
        ):
            raise RunnerUnavailable("runner_output_count_mismatch")
        return result
