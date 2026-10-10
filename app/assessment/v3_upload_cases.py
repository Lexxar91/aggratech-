"""Реальные ZIP и одноразовые потоки: пределы, отказ и независимая очистка."""

import io
import struct
import warnings
import zipfile
import zlib

from pydantic import JsonValue

from app.assessment.v3_cases import CaseBuilder, Pack
from app.assessment.v3_models import V3Card, V3Case
from app.assessment.v3_python_cases import adapter, byte_input, invocation


def archive_bytes(entries: list[tuple[str, bytes, bool]]) -> bytes:
    """Строит воспроизводимый настоящий ZIP, включая диагностические имена."""
    if len(entries) == 1 and entries[0][0] == "":
        raw = entries[0][1]
        crc = zlib.crc32(raw)
        local = struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 33, crc, len(raw), len(raw), 0, 0
        )
        central = struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0,
            0,
            0,
            33,
            crc,
            len(raw),
            len(raw),
            0,
            0,
            0,
            0,
            0,
            0o100600 << 16,
            0,
        )
        end = struct.pack(
            "<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(local) + len(raw), 0
        )
        return local + raw + central + end
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", message="Duplicate name:.*", category=UserWarning
        )
        with zipfile.ZipFile(output, "w") as archive:
            for name, content, symlink in entries:
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o120777 if symlink else 0o100600) << 16
                archive.writestr(info, content)
    return output.getvalue()


def upload_cases(card: V3Card, seed: int) -> list[V3Case]:
    """Отказы не оцениваются по одному коду: проверяются публикация и чтения."""
    b = CaseBuilder(card, seed)
    middle = card.grade == "middle"
    payload = (f"data-{seed}").encode()

    def upload(
        pack: Pack,
        name: str,
        chunks: list[bytes],
        max_bytes: int,
        status: int,
        *,
        read_count: int | None = None,
        error_at: int | None = None,
        content_type: str = "application/zip",
        expanded_limit: int = 1000,
        max_files: int = 10,
        archive_config: dict[str, JsonValue] | None = None,
        expanded_reads: dict[str, int] | None = None,
    ) -> None:
        parts: list[JsonValue] = [byte_input(chunk) for chunk in chunks]
        streams: dict[str, JsonValue] = {"chunks": {"items": parts}}
        if error_at is not None:
            streams["chunks"] = {"items": parts, "error_at": error_at}
        adapters: dict[str, JsonValue] = {"storage": {"kind": "storage"}}
        args: list[JsonValue] = [{"$stream": "chunks"}]
        if middle:
            adapters["inspect"] = {"kind": "archive", **(archive_config or {})}
            args += [
                content_type,
                max_bytes,
                expanded_limit,
                max_files,
                adapter("storage"),
                adapter("inspect"),
            ]
        else:
            args += [max_bytes, adapter("storage")]
        count = len(chunks) if read_count is None else read_count
        publication: list[JsonValue] = [b"".join(chunks).hex()] if status == 201 else []
        checks = [
            b.assertion("http_api", ["return_values"], [status]),
            b.assertion("http_api", ["observed", "temp_exists"], False),
            b.assertion("http_api", ["observed", "commit_count"], int(status == 201)),
            b.assertion("security_validation", ["observed", "published"], publication),
            b.assertion("security_validation", ["observed", "temp_exists"], False),
            b.assertion(
                "language_algorithms", ["observed", "stream_reads", "chunks"], count
            ),
            b.assertion("language_algorithms", ["observed", "streaming_valid"], True),
        ]
        for stream_name, consumed in (expanded_reads or {}).items():
            checks.append(
                b.assertion(
                    "language_algorithms",
                    ["observed", "stream_reads", stream_name],
                    consumed,
                )
            )
        b.add(
            pack,
            name,
            {
                "streams": streams,
                "adapters": adapters,
                "invocations": [
                    invocation("upload_archive" if middle else "upload", args)
                ],
            },
            checks,
        )

    if not middle:
        upload("A", "one-chunk", [payload], len(payload) + 10, 201)
        upload(
            "A", "several-chunks", [payload[:3], payload[3:]], len(payload) + 10, 201
        )
        upload("B", "empty", [], 10, 400)
        upload("B", "empty-parts", [b"", b""], 10, 400)
        upload("B", "exact-boundary", [payload], len(payload), 201)
        upload(
            "B",
            "above-boundary",
            [payload, b"never-read"],
            len(payload) - 1,
            413,
            read_count=1,
        )
        upload("B", "zero-limit-empty", [], 0, 400)
        upload("B", "zero-limit-data", [b"x", b"never-read"], 0, 413, read_count=1)
        upload(
            "C",
            "read-failure",
            [payload, b"not-read"],
            100,
            503,
            error_at=1,
            read_count=1,
        )
        upload("D", "stop-after-limit", [b"xx", b"never-read"], 1, 413, read_count=1)
        upload(
            "D", "many-short-parts", [bytes([65 + i % 20]) for i in range(80)], 80, 201
        )
        upload(
            "D",
            "empty-mixed",
            [b"", payload[:2], b"", payload[2:], b""],
            len(payload),
            201,
        )
    else:
        safe = archive_bytes([("safe.txt", payload, False)])
        two = archive_bytes(
            [("a/one.txt", payload, False), ("a/two.txt", b"two", False)]
        )
        upload("A", "one-file", [safe], len(safe) + 10, 201)
        upload("A", "two-files", [two[:20], two[20:]], len(two) + 10, 201)
        upload(
            "B", "mime", [safe], len(safe), 415, content_type="text/plain", read_count=0
        )
        upload("B", "invalid-format", [b"not-a-zip"], 100, 415)
        upload("B", "empty-stream", [], 100, 400)
        upload("B", "empty-parts", [b"", b""], 100, 400)
        upload("B", "compressed-boundary", [safe], len(safe), 201)
        upload(
            "B",
            "compressed-over-limit",
            [safe, b"not-read"],
            len(safe) - 1,
            413,
            read_count=1,
        )
        for i, name in enumerate(
            ["", "../file", "/file", "a\\b", "c:file", "a//b", "a/./b", "a/../b"]
        ):
            raw = archive_bytes([(name, payload, False)])
            upload("B", f"path-{i}", [raw], len(raw), 400)
        raw = archive_bytes([("link", payload, True)])
        upload("B", "symlink", [raw], len(raw), 400)
        duplicate = archive_bytes(
            [("same.txt", b"one", False), ("same.txt", b"two", False)]
        )
        upload("B", "duplicate-name", [duplicate], len(duplicate), 400)
        expanded = archive_bytes([("big.txt", b"x" * 300, False)])
        upload(
            "C",
            "actual-expanded-limit",
            [expanded],
            len(expanded),
            413,
            expanded_limit=5,
            expanded_reads={"expanded-0": 2},
        )
        upload("C", "file-count-limit", [two], len(two), 413, max_files=1)
        upload(
            "D",
            "value-error-mid-inspection",
            [two],
            len(two),
            415,
            archive_config={"error_at": 1},
        )
        upload(
            "D",
            "oserror-mid-expansion",
            [safe],
            len(safe),
            503,
            archive_config={"expanded_error_at": 1},
        )
        upload(
            "D",
            "expanded-exact-boundary",
            [safe],
            len(safe),
            201,
            expanded_limit=len(payload),
            max_files=1,
        )
        invalid = archive_bytes([("../bad", payload, False)])
        upload("D", "path-before-count", [invalid], len(invalid), 400, max_files=0)
        upload("D", "zero-file-limit", [safe], len(safe), 413, max_files=0)
        upload(
            "D",
            "stop-reading-compressed",
            [safe, b"never-read"],
            len(safe) - 1,
            413,
            read_count=1,
        )
        upload(
            "D",
            "many-compressed-parts",
            [safe[i : i + 10] for i in range(0, len(safe), 10)],
            len(safe),
            201,
        )
        upload(
            "D",
            "read-failure",
            [safe[:10], safe[10:]],
            len(safe),
            503,
            error_at=1,
            read_count=1,
        )
    return b.cases
