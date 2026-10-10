import io
import json
import logging
import re
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.logging import SafeJsonFormatter
from app.main import create_app


def test_liveness_web_and_request_id_do_not_require_database() -> None:
    settings = Settings(
        database_url=SecretStr(
            "postgresql+asyncpg://missing:secret@127.0.0.1:1/missing"
        ),
        database_timeout_seconds=0.1,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health/live", headers={"X-Request-ID": "not-an-id"})
        assert response.status_code == 200
        UUID(response.headers["X-Request-ID"])
        assert response.json() == {"status": "alive"}
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json()["code"] == "database_not_ready"
        assert "secret" not in ready.text
        assert ready.json()["request_id"] == ready.headers["X-Request-ID"]
        page = client.get("/")
        assert page.status_code == 200
        assert 'id="root"' in page.text
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page.text)
        assert len(assets) == 2
        for asset in assets:
            response = client.get(asset)
            assert response.status_code == 200
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert client.get("/app.js").status_code == 404


def test_safe_logging_does_not_serialize_exception_or_payload() -> None:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(SafeJsonFormatter())
    record = logging.LogRecord(
        "third_party", logging.ERROR, "", 0, "password=hidden@example.com", (), None
    )
    record.payload = {"token": "secret"}
    handler.handle(record)
    data = json.loads(output.getvalue())
    assert data["event"] == "dependency_log"
    assert "secret" not in output.getvalue()
    assert "hidden@example.com" not in output.getvalue()
