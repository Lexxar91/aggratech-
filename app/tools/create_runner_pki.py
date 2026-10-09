import argparse
import os
import subprocess
from pathlib import Path


def openssl(directory: Path, *arguments: str) -> None:
    """Создаёт сертификаты без записи приватных ключей в логи."""
    subprocess.run(
        ["openssl", *arguments],
        cwd=directory,
        check=True,
        timeout=30,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_pki(output: Path, hostname: str) -> None:
    """Готовит отдельные CA/server/client bundles для mTLS закрытого прототипа."""
    if not hostname or any(
        character
        not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-"
        for character in hostname
    ):
        raise ValueError("invalid_hostname")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(output.iterdir()):
        raise ValueError("output_directory_not_empty")
    old_mask = os.umask(0o077)
    try:
        openssl(
            output,
            "req",
            "-x509",
            "-newkey",
            "rsa:3072",
            "-nodes",
            "-keyout",
            "ca.key",
            "-out",
            "ca.crt",
            "-days",
            "30",
            "-subj",
            "/CN=Aggratech runner CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        )
        for name, usage in (("server", "serverAuth"), ("client", "clientAuth")):
            directory = output / name
            directory.mkdir(mode=0o700)
            openssl(
                directory,
                "req",
                "-newkey",
                "rsa:3072",
                "-nodes",
                "-keyout",
                f"{name}.key",
                "-out",
                f"{name}.csr",
                "-subj",
                f"/CN={hostname if name == 'server' else 'aggratech-worker'}",
            )
            extensions = (
                f"basicConstraints=critical,CA:FALSE\nextendedKeyUsage={usage}\n"
            )
            if name == "server":
                extensions += f"subjectAltName=DNS:{hostname}\n"
            (directory / "extensions.cnf").write_text(extensions)
            openssl(
                directory,
                "x509",
                "-req",
                "-in",
                f"{name}.csr",
                "-CA",
                "../ca.crt",
                "-CAkey",
                "../ca.key",
                "-CAcreateserial",
                "-out",
                f"{name}.crt",
                "-days",
                "7",
                "-extfile",
                "extensions.cnf",
            )
            (directory / "ca.crt").write_bytes((output / "ca.crt").read_bytes())
    finally:
        os.umask(old_mask)


def main() -> None:
    """Запускает создание ключей в игнорируемой папке и запрещает перезапись."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".pki"))
    parser.add_argument("--hostname", default="runner.internal")
    args = parser.parse_args()
    create_pki(args.output, args.hostname)
    print("mTLS bundles created; keep CA private key on the operator machine")


if __name__ == "__main__":
    main()
