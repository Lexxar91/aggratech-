"""Публичные DTO assessment, без закрытых материалов и исходников эталонов."""

import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Grade = Literal["junior", "middle"]
Mode = Literal["demo", "credit"]
Outcome = Literal["confirmed", "not_confirmed", "insufficient", "review_required"]


class SurveyInput(BaseModel):
    """Опрос с фиксированными границами поддерживаемого направления."""

    model_config = ConfigDict(extra="forbid")
    industry: str = Field(min_length=1, max_length=120)
    specialization: Literal["backend"] = "backend"
    stack: list[str] = Field(min_length=1, max_length=20)
    experience_years: int = Field(ge=0, le=50)
    tools_policy: Literal["independent"] = "independent"
    instructions_accepted: Literal[True]

    @model_validator(mode="after")
    def bounded_stack(self) -> SurveyInput:
        """Ограничивает самоописание и исключает пустые названия технологий."""
        if any(not x.strip() or len(x) > 80 for x in self.stack):
            raise ValueError("invalid_stack")
        return self


class CycleInput(BaseModel):
    """Грейд выбирает кандидат; по умолчанию используется явный демо-режим."""

    model_config = ConfigDict(extra="forbid")
    grade: Grade
    mode: Mode = "demo"
    form: Literal["X", "Y"] | None = None


class TaskAnswer(BaseModel):
    """Python и структурированный ответ с ограниченными собственными случаями."""

    model_config = ConfigDict(extra="forbid")
    source: str = Field(default="", max_length=32768)
    structured: dict[str, JsonValue] = Field(default_factory=dict)
    diagnosis: str = Field(default="", max_length=80)
    verification: list[str] = Field(default_factory=list, max_length=5)
    tests: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def bounded_json(self) -> TaskAnswer:
        """Не допускает неограниченный JSON, нечисла и бесконечности."""
        if (
            len(self.source.encode()) > 32000
            or len(json.dumps(self.model_dump(), allow_nan=False).encode()) > 60000
        ):
            raise ValueError("answer_too_large")
        return self


class SaveAnswer(BaseModel):
    """Версия черновика предотвращает потерю изменений из другой вкладки."""

    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    step: Literal["base", "transfer"]
    answer: TaskAnswer


class PublicTask(BaseModel):
    number: int = 1
    family: str
    family_id: str | None = None
    task_id: str | None = None
    language: Literal["python", "sql", "structured"] = "structured"
    title: str = ""
    common_contract: str | None = None
    phase: str
    step: str
    revision: int
    condition: str
    diagnosis_prompt: str
    diagnosis_options: list[str]
    verification_options: list[str]
    input: JsonValue
    structured_condition: str | None = None
    structured_input: JsonValue = None
    answer_options: dict[str, list[JsonValue]] = Field(default_factory=dict)
    python_required: bool
    candidate_test_contract: str | None = None
    draft: TaskAnswer
    finalized: bool


class SkillResult(BaseModel):
    skill: str
    status: str
    families: int
    score: float | None


class ResultView(BaseModel):
    outcome: Outcome
    verified: bool = False
    mode: str
    grade: str
    label: str
    total: float | None = None
    skills: list[SkillResult] = Field(default_factory=list)
    methodology: str
    assessed_at: datetime | None = None
    scope: str = "Backend: Python, SQL/data, HTTP/API; самостоятельный режим"
    requirements: list[RequirementResult] = Field(default_factory=list)
    limitations: str | None = None


class RequirementResult(BaseModel):
    """Публичное основание без тестовых параметров, правильных ответов и рубрик."""

    task_id: str
    task_title: str = ""
    task_number: int = 1
    family_id: str
    skill: str
    action: str
    status: str
    passed: bool | None = None


class CycleView(BaseModel):
    id: UUID
    grade: str
    mode: str
    form: str = ""
    state: str
    a_deadline: datetime
    b_start_deadline: datetime | None
    b_deadline: datetime | None
    tasks: list[PublicTask]
    result: ResultView
    technical_issue: bool
    bank_hash: str
    created_at: datetime
    completed_at: datetime | None


class AssessmentAvailability(BaseModel):
    """Безопасная информация о доступных режимах и принятой методике."""

    bank_version: str | None
    methodology: str | None
    credit_available: bool
    demo_available: bool
    cards_per_form: int
    a_tasks: int
    b_tasks: int
    acceptance: str | None
    message: str


class AppealInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=10, max_length=2000)


class AppealView(BaseModel):
    id: UUID
    cycle_id: UUID
    state: str
    created_at: datetime
    resolution: str | None
