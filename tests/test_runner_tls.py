import ssl
import threading
from http.server import HTTPServer
from pathlib import Path

import httpx
import pytest

from app.tools.create_runner_pki import create_pki
from runner.sandbox import SandboxPolicy
from runner.server import build_handler


def test_real_mtls_protocol_without_executing_candidate_code(tmp_path: Path) -> None:
    create_pki(tmp_path, "localhost")
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.verify_mode = ssl.CERT_REQUIRED
    server_context.load_cert_chain(
        tmp_path / "server/server.crt", tmp_path / "server/server.key"
    )
    server_context.load_verify_locations(tmp_path / "ca.crt")
    server = HTTPServer(("127.0.0.1", 0), build_handler(SandboxPolicy()))
    server.socket.settimeout(2)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"https://localhost:{server.server_port}/not-an-execution-route"
    try:
        context = ssl.create_default_context(cafile=str(tmp_path / "ca.crt"))
        with httpx.Client(verify=context, trust_env=False, timeout=3) as client:
            with pytest.raises(httpx.HTTPError):
                client.post(url, json={})
        context.load_cert_chain(
            tmp_path / "client/client.crt", tmp_path / "client/client.key"
        )
        with httpx.Client(verify=context, trust_env=False, timeout=3) as client:
            response = client.post(url, json={})
            assert response.status_code == 404
            assert response.json() == {"code": "not_found"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_pki_rejects_invalid_hostname_and_overwrite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid_hostname"):
        create_pki(tmp_path, "name; injected command")
    (tmp_path / "existing").write_text("keep")
    with pytest.raises(ValueError, match="not_empty"):
        create_pki(tmp_path, "localhost")
