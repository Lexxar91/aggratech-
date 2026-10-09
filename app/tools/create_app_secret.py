import os
import secrets
from pathlib import Path


def main() -> None:
    """Один раз создаёт секрет JWT в отдельном named volume без вывода значения."""
    directory = Path("/run/app-secret")
    directory.mkdir(exist_ok=True)
    path = directory / "jwt-key"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(48))
    # CHOWN разрешает вернуть владение root; FOWNER добавлять не требуется.
    os.chown(path, 0, 0)
    os.chmod(path, 0o400)
    os.chown(path, 10001, 10001)
    os.chown(directory, 0, 0)
    os.chmod(directory, 0o700)
    os.chown(directory, 10001, 10001)


if __name__ == "__main__":
    main()
