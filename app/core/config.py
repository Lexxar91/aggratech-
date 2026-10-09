from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки процесса без подключения внешних зависимостей при импорте."""

    model_config = SettingsConfigDict(
        env_prefix="APP_", env_file=".env", extra="ignore"
    )

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://aggratech:local-development@localhost:5432/aggratech"
    )
    database_timeout_seconds: float = Field(default=3, gt=0, le=30)
    worker_poll_seconds: float = Field(default=1, gt=0, le=60)
    job_lease_seconds: int = Field(default=60, ge=5, le=300)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    assessment_bank: Path = Path("bank/private/full.json")
    assessment_report: Path = Path("bank/private/technical_report.json")
    assessment_reviews: Path | None = None
    runner_url: str | None = None
    runner_ca: Path | None = None
    runner_client_certificate: Path | None = None
    runner_client_key: Path | None = None
    runner_timeout_seconds: float = Field(default=15, gt=0, le=60)
    jwt_secret: SecretStr = SecretStr("")
    jwt_secret_file: Path = Path("/run/app-secret/jwt-key")
    jwt_issuer: str = "aggratech"
    jwt_audience: str = "aggratech-api"
    public_origin: str = "http://127.0.0.1:18000"
    allowed_origins: list[str] = ["http://localhost:18000"]
    auth_rate_limit: int = Field(default=10, ge=1, le=1000)
    smtp_host: str = "mailpit"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_from: str = "noreply@aggratech.local"
