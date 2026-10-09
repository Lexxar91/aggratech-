"""Ограниченный файловый вход жюри: строгий JSON и маркированные DTO в памяти."""

import hashlib
import json
import math
from pathlib import Path
from typing import Any  # JSON-пример содержит разнородные вложенные значения.

from pydantic import ValidationError

from app.matching.catalog import dictionary
from app.matching.schemas import Candidate, ContractModel, Dataset, Evidence, Labels

MAX_BYTES = 10 * 1024 * 1024


class InputError(ValueError):
    """Безопасная ошибка с путём, без копирования входного профиля."""

    def __init__(self, field: str, code: str) -> None:
        self.field = field
        self.code = code
        super().__init__(f"{field}: {code}")

    def record(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code}


class ObjectPairs(list[tuple[str, object]]):
    pass


def read_json(path: Path) -> tuple[object, str]:
    """Проверяет размер, UTF-8, повторные ключи и конечность чисел до Pydantic."""
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise InputError("$", "file_size_limit")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=ObjectPairs)
    except ValueError, RecursionError:
        raise InputError("$", "invalid_utf8_json") from None

    def convert(item: object, path: str) -> object:
        if isinstance(item, ObjectPairs):
            result: dict[str, object] = {}
            for key, child in item:
                location = path + "." + key[:128]
                if key in result:
                    raise InputError(location, "duplicate_json_key")
                result[key] = convert(child, location)
            return result
        if isinstance(item, list):
            return [convert(child, f"{path}[{i}]") for i, child in enumerate(item)]
        if isinstance(item, float) and not math.isfinite(item):
            raise InputError(path, "non_finite_number")
        return item

    try:
        converted = convert(value, "$")
    except RecursionError:
        raise InputError("$", "json_depth_limit") from None
    return converted, hashlib.sha256(raw).hexdigest()


def model_input[T: ContractModel](model: type[T], value: object) -> T:
    """Возвращает безопасную ошибку первого поля, не печатая его значение."""
    try:
        return model.model_validate(value)
    except ValidationError as error:
        first = error.errors(
            include_input=False, include_context=False, include_url=False
        )[0]
        path = "$" + "".join(
            f"[{x}]" if isinstance(x, int) else "." + str(x) for x in first["loc"]
        )
        code = str(first["type"])
        message = str(first["msg"]).removeprefix("Value error, ")
        if code == "value_error":
            code = message.split(":")[0]
            if message.startswith("inconsistent_verified_technology:"):
                path += ".technologies." + message.split(":", 1)[1]
            elif code == "unconfirmed_has_evidence":
                path += ".skills"
            elif code == "reversed_salary_range":
                path += ".salary_to"
        raise InputError(path, code) from None


def validate_dataset(dataset: Dataset) -> None:
    """Проверяет ID, сопоставимость методики и даты относительно as_of."""
    for collection, key in (
        (dataset.candidates, "candidate_id"),
        (dataset.needs, "need_id"),
    ):
        seen: set[str] = set()
        label = "candidates" if key == "candidate_id" else "needs"
        for i, row in enumerate(collection):
            identifier = str(getattr(row, key))
            if identifier in seen:
                raise InputError(f"$.{label}[{i}].{key}", "duplicate_id")
            seen.add(identifier)
    method: str | None = None
    for i, candidate in enumerate(dataset.candidates):
        if method is None:
            method = candidate.assessment_scope.method_version
        elif method != candidate.assessment_scope.method_version:
            raise InputError(
                f"$.candidates[{i}].assessment_scope.method_version",
                "incomparable_method_versions",
            )
        for skill, evidence in candidate.skills.items():
            if evidence.verified_at > dataset.as_of:
                raise InputError(
                    f"$.candidates[{i}].skills.{skill}.verified_at",
                    "future_confirmation",
                )
        if (
            candidate.conditions.confirmed_at
            and candidate.conditions.confirmed_at > dataset.as_of
        ):
            raise InputError(
                f"$.candidates[{i}].conditions.confirmed_at", "future_confirmation"
            )


def load_dataset(path: Path) -> tuple[Dataset, str]:
    """Загружает весь набор или отвергает его целиком."""
    raw, digest = read_json(path)
    dataset = model_input(Dataset, raw)
    validate_dataset(dataset)
    return dataset, digest


def load_labels(path: Path, dataset: Dataset) -> tuple[Labels, str]:
    """Загружает разметку для этапа метрик; matching её не получает."""
    raw, digest = read_json(path)
    labels = model_input(Labels, raw)
    if labels.dataset_id != dataset.dataset_id:
        raise InputError("$.dataset_id", "dataset_id_mismatch")
    needs = {n.need_id for n in dataset.needs}
    candidates = {c.candidate_id for c in dataset.candidates}
    seen: set[tuple[str, str]] = set()
    for i, pair in enumerate(labels.pairs):
        if pair.need_id not in needs:
            raise InputError(f"$.pairs[{i}].need_id", "unknown_reference")
        if pair.candidate_id not in candidates:
            raise InputError(f"$.pairs[{i}].candidate_id", "unknown_reference")
        key = (pair.need_id, pair.candidate_id)
        if key in seen:
            raise InputError(f"$.pairs[{i}]", "duplicate_pair")
        seen.add(key)
    return labels, digest


def candidates_from_fixture(dataset: Dataset) -> list[Candidate]:
    """Помечает внешние баллы fixture; не создаёт профилей или assessment-записей."""
    return [
        Candidate(
            candidate_id=c.candidate_id,
            specialization=c.specialization,
            grade=c.grade,
            category_status="confirmed"
            if c.category_status == "fixture_confirmed"
            else "unconfirmed",
            origin="jury_fixture",
            assessment_scope=c.assessment_scope,
            skills={k: Evidence(**v.model_dump()) for k, v in c.skills.items()},
            technologies=c.technologies,
            fsp_verified=c.fsp_verified,
            fsp_origin="jury_fixture" if c.fsp_verified else "none",
            conditions=c.conditions,
            visibility=c.visibility,
        )
        for c in dataset.candidates
    ]


def example_dataset() -> dict[str, Any]:
    """Создаёт расширенный пример SQL/HTTP, неизвестных условий и исключений."""

    def candidate(identifier: str, sql: int, http: int) -> dict[str, object]:
        return {
            "candidate_id": identifier,
            "specialization": "backend",
            "grade": "middle",
            "category_status": "fixture_confirmed",
            "assessment_scope": {
                "language": "python",
                "method_version": "jury-example-v1",
                "format": "jury-skill-100-v1",
            },
            "skills": {
                skill: {
                    "score": score,
                    "verified_at": "2026-10-01T09:00:00Z",
                    "mode": "independent",
                }
                for skill, score in [("sql_data", sql), ("http_api", http)]
            },
            "technologies": {
                "python": "self_reported",
                "sql": "verified",
                "http_api": "verified",
            },
            "fsp_verified": False,
            "conditions": {
                "salary_from": 150000,
                "salary_to": 200000,
                "work_formats": ["remote"],
                "location": None,
                "available_from": "2026-10-15",
                "confirmed_at": "2026-10-01T09:00:00Z",
            },
            "visibility": {"consent_to_match": True, "blocked_employer_ids": []},
        }

    rows = [
        candidate("sql-strong", 95, 60),
        candidate("http-strong", 60, 95),
        candidate("unknown-salary", 75, 75),
        candidate("unconfirmed", 0, 0),
        candidate("private", 90, 90),
    ]
    rows[2]["conditions"] = {
        "salary_from": None,
        "salary_to": None,
        "work_formats": ["remote"],
        "location": None,
        "available_from": "2026-10-15",
        "confirmed_at": "2026-10-01T09:00:00Z",
    }
    rows[3]["category_status"] = "unconfirmed"
    rows[3]["skills"] = {}
    rows[3]["technologies"] = {"python": "self_reported"}
    rows[4]["visibility"] = {"consent_to_match": False, "blocked_employer_ids": []}

    def need(identifier: str, priorities: dict[str, int]) -> dict[str, object]:
        return {
            "need_id": identifier,
            "employer_id": "employer-demo",
            "title": identifier,
            "specialization": "backend",
            "accepted_grades": ["middle"],
            "required_stack": [
                {"technology": "python", "verification_required": False}
            ],
            "preferred_stack": ["sql", "http_api"],
            "skill_priorities": priorities,
            "required_verified_skills": ["sql_data", "http_api"],
            "work_formats": ["remote"],
            "location": None,
            "salary_from": 160000,
            "salary_to": 220000,
            "desired_start_date": "2026-10-20",
            "start_date_required": False,
        }

    return {
        "schema_version": "matching-fixture-v1",
        "dataset_id": "jury-example",
        "as_of": "2026-10-07T09:00:00Z",
        "candidates": rows,
        "needs": [
            need("sql-priority", {"sql_data": 2, "http_api": 1}),
            need("http-priority", {"sql_data": 1, "http_api": 2}),
        ],
    }


def example_files() -> dict[str, object]:
    """Готовит схемы, словарь, dataset и явно синтетическую разметку."""
    dataset = model_input(Dataset, example_dataset())
    labels = {
        "schema_version": "matching-labels-v1",
        "dataset_id": dataset.dataset_id,
        "pairs": [
            {
                "need_id": n.need_id,
                "candidate_id": c.candidate_id,
                "relevance": (
                    3
                    if c.candidate_id.startswith(n.need_id.split("-")[0])
                    else 2
                    if c.candidate_id in ["sql-strong", "http-strong", "unknown-salary"]
                    else 0
                ),
                "eligibility": "excluded"
                if c.candidate_id in ["private", "unconfirmed"]
                else "needs_clarification"
                if c.candidate_id == "unknown-salary"
                else "eligible",
            }
            for n in dataset.needs
            for c in dataset.candidates
        ],
    }
    return {
        "dataset.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **Dataset.model_json_schema(),
        },
        "labels.schema.json": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **Labels.model_json_schema(),
        },
        "dictionary.json": dictionary(),
        "dataset.json": dataset.model_dump(mode="json"),
        "labels.json": labels,
    }
