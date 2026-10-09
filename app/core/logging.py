import json
import logging
import sys
from datetime import UTC, datetime


class SafeJsonFormatter(logging.Formatter):
    """Сериализует только разрешённые поля, не сообщения и traceback зависимостей."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, object] = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "dependency_log"),
        }
        for key in (
            "request_id",
            "job_id",
            "duration_ms",
            "http_status",
            "error_code",
            "queue_size",
            "attempt_count",
        ):
            if hasattr(record, key):
                data[key] = getattr(record, key)
        return json.dumps(data, ensure_ascii=False)


def configure_logging() -> None:
    """Настраивает JSON-логирование без токенов, контактов и содержимого заданий."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SafeJsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
