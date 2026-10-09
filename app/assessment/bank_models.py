"""Закрытые материалы полного банка; публичная выдача определяется отдельно."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.assessment.bank_quality import Case, Solution

Skill = Literal[
    "language_algorithms",
    "sql_data",
    "http_api",
    "debug_reliability",
    "security_validation",
]


class MaterialModel(BaseModel):
    """Запрещает неизвестные поля и неявное преобразование типов материалов."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Rule(MaterialModel):
    """Наблюдаемый признак структурированного ответа внутри рубрики навыка."""

    skill: Skill
    field: str
    accepted: list[JsonValue] = Field(min_length=1)
    points: int = Field(ge=1, le=4)
    unordered: bool = False
    requires: str | None = None


class AnswerExample(MaterialModel):
    """Заранее заданный корректный, частичный или ошибочный ответ."""

    kind: Literal["reference", "alternative", "partial", "mistake", "unadapted"]
    answer: dict[str, JsonValue]
    expected_scores: dict[Skill, int]


class StructuredTask(MaterialModel):
    """Данные, признаки и ожидаемые оценки параметрического случая."""

    id: str
    phase: Literal["base", "transfer"]
    condition: str
    input: JsonValue
    answer_options: dict[str, list[JsonValue]] = Field(default_factory=dict)
    rules: list[Rule] = Field(min_length=1)
    examples: list[AnswerExample] = Field(min_length=4)


class TestPolicy(MaterialModel):
    """Классы ошибок и связанный навык, без дополнительных баллов за тесты."""

    skill: Skill = "language_algorithms"
    mandatory: list[str] = Field(min_length=2, max_length=2)
    additional: str
    input_contract: str


class FullBankVersion(MaterialModel):
    """Неизменяемая по хешу поставка семейства и грейда."""

    family: str = Field(pattern=r"^[XY][1-6]$")
    grade: Literal["junior", "middle"]
    version: str = Field(min_length=1)
    skills: list[Skill] = Field(min_length=2, max_length=2)
    condition: str = Field(min_length=1)
    diagnosis: str = Field(min_length=1)
    transfer: str = Field(min_length=1)
    verification: str = Field(min_length=1)
    rubric: dict[str, dict[str, str]]
    actions: dict[str, str]
    provenance: str = Field(min_length=1)
    author: str = Field(min_length=1)
    review_status: Literal["pending", "reviewed"] = "pending"
    cases: list[Case] = Field(default_factory=list)
    solutions: list[Solution] = Field(default_factory=list)
    structured_cases: list[StructuredTask] = Field(default_factory=list)
    candidate_tests: list[dict[str, JsonValue]] = Field(default_factory=list)
    test_policy: TestPolicy | None = None


class FullBank(MaterialModel):
    """Экспериментальный банк двух непересекающихся форм."""

    bank_version: str
    scope: Literal["full"]
    versions: list[FullBankVersion] = Field(min_length=24, max_length=24)


def load_bank(path: Path) -> FullBank:
    """Читает материалы без молчаливой потери повторяющихся JSON-ключей."""

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    return FullBank.model_validate(
        json.loads(path.read_bytes(), object_pairs_hook=unique)
    )
