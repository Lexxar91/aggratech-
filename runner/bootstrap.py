import os
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from app.tools.create_runner_pki import create_pki


def certificate_valid(path: Path) -> bool:
    """Повторно использует сертификаты демо, если до истечения больше суток."""
    if not path.is_file():
        return False
    return (
        subprocess.run(
            ["openssl", "x509", "-checkend", "86400", "-noout", "-in", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        ).returncode
        == 0
    )


def main() -> None:
    """Создаёт mTLS bundles в отдельных Compose volumes без сохранения CA key."""
    server = Path("/certificates/server")
    client = Path("/certificates/client")
    if certificate_valid(server / "server.crt") and certificate_valid(
        client / "client.crt"
    ):
        print("Existing demo certificates valid")
        return
    with TemporaryDirectory() as directory:
        source = Path(directory) / "pki"
        create_pki(source, "runner-controller")
        for name, destination in (("server", server), ("client", client)):
            destination.mkdir(parents=True, exist_ok=True)
            for filename in ("ca.crt", f"{name}.crt", f"{name}.key"):
                path = destination / filename
                shutil.copyfile(source / name / filename, path)
                path.chmod(0o600)
                uid = 10001 if name == "client" else 0
                os.chown(path, uid, uid)
            destination.chmod(0o700)
            os.chown(destination, uid, uid)
    print("Demo mTLS certificates ready; CA private key removed")


if __name__ == "__main__":
    main()
