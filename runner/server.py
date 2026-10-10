import asyncio
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, HTTPServer

from pydantic import ValidationError

from app.assessment.runner import (
    ExecutionRequest,
    ExecutionResult,
    RunnerUnavailable,
    V3ExecutionRequest,
    V3ExecutionResult,
    runtime_executor_hash,
)
from runner.sandbox import SandboxPolicy, execute, recover_tasks
from runner.v3_python import execute_python_v3
from runner.v3_sql import execute_sql_v3


def reject_constant(value: str) -> object:
    """Не допускает NaN и Infinity в JSON-входах."""
    raise ValueError("non_finite_number")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Отклоняет повторные JSON-ключи вместо незаметной замены значений."""
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def parse_request(body: bytes) -> ExecutionRequest:
    """Проверяет ограниченный JSON до обращения к Docker."""
    value = json.loads(
        body, parse_constant=reject_constant, object_pairs_hook=unique_object
    )
    return ExecutionRequest.model_validate(value)


def build_handler(policy: SandboxPolicy) -> type[BaseHTTPRequestHandler]:
    """Создаёт единственный служебный маршрут технического исполнения."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            """Принимает запрос только после проверки клиентского TLS-сертификата."""
            self.connection.settimeout(10)
            if self.path not in ("/execute", "/execute-v3"):
                self.reply(404, {"code": "not_found"})
                return
            try:
                result: ExecutionResult | V3ExecutionResult
                if self.headers.get("Transfer-Encoding"):
                    raise ValueError("unsupported_transfer_encoding")
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("json_required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= policy.input_bytes:
                    raise ValueError("invalid_content_length")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("incomplete_request")
                if self.path == "/execute-v3":
                    value = json.loads(
                        body,
                        parse_constant=reject_constant,
                        object_pairs_hook=unique_object,
                    )
                    v3_request = V3ExecutionRequest.model_validate(value)
                    result = asyncio.run(
                        execute_python_v3(v3_request)
                        if v3_request.language == "python"
                        else execute_sql_v3(v3_request)
                    )
                    result.executor_hash = runtime_executor_hash()
                else:
                    request = parse_request(body)
                    result = asyncio.run(execute(request, policy))
            except ValueError, ValidationError, RecursionError:
                self.reply(422, {"code": "invalid_execution_request"})
                return
            except OSError, RunnerUnavailable, TimeoutError:
                self.reply(503, {"code": "runner_unavailable"})
                return
            self.reply(200, result.model_dump())

        def reply(self, status: int, body: dict[str, object]) -> None:
            """Возвращает JSON без исходного кода, stderr и сведений об окружении."""
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            """Не пишет URL, запросы и секреты через стандартный HTTP access log."""

    return Handler


def main() -> None:
    """Запускает закрытый docker-limited контроллер с фиксированной политикой."""
    if os.environ.get("RUNNER_MODE") != "docker-limited":
        raise SystemExit("RUNNER_MODE=docker-limited required; see docs/05")
    policy = SandboxPolicy()
    asyncio.run(recover_tasks())
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(
        os.environ["RUNNER_SERVER_CERTIFICATE"], os.environ["RUNNER_SERVER_KEY"]
    )
    context.load_verify_locations(cafile=os.environ["RUNNER_CLIENT_CA"])
    with HTTPServer(
        (os.environ.get("RUNNER_BIND", "127.0.0.1"), 9443), build_handler(policy)
    ) as server:
        server.socket.settimeout(10)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
