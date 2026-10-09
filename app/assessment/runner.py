import ssl
from math import isfinite
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.core.config import Settings

PYTHON_IMAGE = (
    "python:3.14.4-slim@sha256:"
    "2ca02f32b4d9d893863367ce07ec1972819f476dd38d8612f2a9cb6a41cbb727"
)


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
