"""Общие DTO и явный контракт файлов жюри; импорт не создаёт квалификаций."""

import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StrictBool,
    StrictInt,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.matching.catalog import (
    TECHNOLOGY_PATTERN,
    VERIFIED_TECHNOLOGIES,
    GradeCode,
    SkillCode,
    WorkFormat,
    technology,
)


def numeric(value: object) -> object:
    """Исключает bool, числовые строки, нечисла и бесконечности на JSON-границе."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float, Decimal))
        or (isinstance(value, float) and not math.isfinite(value))
        or (isinstance(value, Decimal) and not value.is_finite())
    ):
        raise ValueError("finite_number_required")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(numeric, json_schema_input_type=int | float),
    Field(
        ge=0,
        le=9999999999,
        decimal_places=2,
        json_schema_extra={"minimum": 0, "maximum": 9999999999, "multipleOf": 0.01},
    ),
    PlainSerializer(float, return_type=float),
]
Score = Annotated[
    float,
    BeforeValidator(numeric, json_schema_input_type=int | float),
    Field(ge=0, le=100, json_schema_extra={"minimum": 0, "maximum": 100}),
]
TechCode = Annotated[str, Field(pattern=TECHNOLOGY_PATTERN)]
Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def date_input(cls, value: object, info: ValidationInfo) -> object:
        annotation = str(cls.model_fields[info.field_name or ""].annotation)
        if "datetime" in annotation or "datetime.date" in annotation:
            if value is not None and not isinstance(value, (str, date)):
                raise ValueError("iso_date_required")
            if isinstance(value, str):
                pattern = (
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
                    if "datetime.datetime" in annotation
                    else r"\d{4}-\d{2}-\d{2}"
                )
                if not re.fullmatch(pattern, value):
                    raise ValueError("iso_date_required")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def utc_dates(cls, value: object) -> object:
        """Требует UTC для временных отметок и не допускает наивных datetime."""
        if isinstance(value, datetime) and (
            value.tzinfo is None or value.utcoffset() != timedelta(0)
        ):
            raise ValueError("utc_timestamp_required")
        return value


class AssessmentScope(ContractModel):
    language: Literal["python"]
    method_version: str = Field(min_length=1, max_length=128)
    format: Literal["jury-skill-100-v1", "assessment-skill-100-v1"]


class Evidence(ContractModel):
    score: Score
    verified_at: datetime
    mode: Literal["independent"]
    families: int = Field(default=0, ge=0)


class FixtureEvidence(ContractModel):
    score: Score
    verified_at: datetime
    mode: Literal["independent"]


class Conditions(ContractModel):
    salary_from: Money | None
    salary_to: Money | None
    work_formats: list[WorkFormat] | None = Field(max_length=3)
    location: str | None = Field(max_length=120)
    available_from: date | None
    confirmed_at: datetime | None

    @model_validator(mode="after")
    def valid_range(self) -> Conditions:
        """Допускает только неизвестный диапазон, минимум или согласованные границы."""
        if self.salary_from is None and self.salary_to is not None:
            raise ValueError("salary_from_required")
        if (
            self.salary_from is not None
            and self.salary_to is not None
            and self.salary_to < self.salary_from
        ):
            raise ValueError("reversed_salary_range")
        if self.work_formats is not None and len(set(self.work_formats)) != len(
            self.work_formats
        ):
            raise ValueError("duplicate_work_format")
        return self


class Visibility(ContractModel):
    consent_to_match: StrictBool
    blocked_employer_ids: list[Identifier] = Field(max_length=1000)


class RequiredTechnology(ContractModel):
    technology: TechCode
    verification_required: StrictBool

    @field_validator("technology")
    @classmethod
    def normalize(cls, value: str) -> str:
        return technology(value)


class Need(ContractModel):
    need_id: Identifier
    employer_id: Identifier
    title: str = Field(min_length=1, max_length=160)
    specialization: Literal["backend"]
    accepted_grades: list[GradeCode] = Field(min_length=1, max_length=2)
    required_stack: list[RequiredTechnology] = Field(max_length=30)
    preferred_stack: list[TechCode] = Field(max_length=30)
    skill_priorities: dict[SkillCode, Literal[1, 2]]
    required_verified_skills: list[SkillCode] = Field(max_length=5)
    work_formats: list[WorkFormat] = Field(min_length=1, max_length=3)
    location: str | None = Field(max_length=120)
    salary_from: Money
    salary_to: Money
    desired_start_date: date | None
    start_date_required: StrictBool
    role: str = Field(default="", max_length=120)
    team_description: str = Field(default="", max_length=4000)
    task_description: str = Field(default="", max_length=4000)
    additional_requirements: dict[
        Literal["required_experience_years"], Annotated[StrictInt, Field(ge=0, le=50)]
    ] = Field(default_factory=dict)
    additional_wishes: str = Field(default="", max_length=2000)
    urgency: Literal["urgent", "normal", "flexible"] = "normal"
    vacancy_id: str | None = None
    version: StrictInt = Field(default=1, ge=1)
    template_code: str | None = None
    template_version: str | None = None
    salary_currency: Literal["RUB"] = "RUB"
    salary_basis: Literal["gross"] = "gross"

    @field_validator("preferred_stack")
    @classmethod
    def normalize_stack(cls, value: list[str]) -> list[str]:
        return [technology(x) for x in value]

    @field_validator("skill_priorities", mode="before")
    @classmethod
    def strict_priorities(cls, value: object) -> object:
        if isinstance(value, dict) and any(type(x) is not int for x in value.values()):
            raise ValueError("integer_priority_required")
        return value

    @model_validator(mode="after")
    def valid_need(self) -> Need:
        """Проверяет обязательные условия без угадывания бюджета и даты."""
        if self.salary_from <= 0 or self.salary_to < self.salary_from:
            raise ValueError("invalid_salary_range")
        if (
            self.start_date_required or self.urgency == "urgent"
        ) and self.desired_start_date is None:
            raise ValueError("desired_start_date_required")
        if (
            any(x in self.work_formats for x in ("office", "hybrid"))
            and not self.location
        ):
            raise ValueError("location_required")
        for values in (
            self.accepted_grades,
            self.work_formats,
            self.preferred_stack,
            self.required_verified_skills,
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate_requirement")
        required = [x.technology for x in self.required_stack]
        if len(required) != len(set(required)) or set(required) & set(
            self.preferred_stack
        ):
            raise ValueError("duplicate_technology_requirement")
        if bool(self.template_code) != bool(self.template_version):
            raise ValueError("template_origin_incomplete")
        return self


class Candidate(ContractModel):
    candidate_id: Identifier
    specialization: Literal["backend"]
    grade: GradeCode
    category_status: Literal["confirmed", "unconfirmed"]
    origin: Literal["credit_assessment", "jury_fixture"]
    assessment_scope: AssessmentScope
    skills: dict[SkillCode, Evidence]
    technologies: dict[TechCode, Literal["verified", "self_reported"]] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    fsp_verified: StrictBool
    fsp_origin: Literal["none", "jury_fixture", "fsp_mock", "registry"] = "none"
    conditions: Conditions
    visibility: Visibility
    evidence_snapshot: dict[str, str] = Field(default_factory=dict)
    experience_years: int | None = Field(default=None, ge=0, le=50)

    @model_validator(mode="after")
    def fsp_provenance(self) -> Candidate:
        if self.fsp_verified and self.fsp_origin not in ("registry", "jury_fixture"):
            raise ValueError("unverified_fsp_source")
        return self

    @field_validator("technologies")
    @classmethod
    def normalized_technologies(
        cls, value: dict[str, Literal["verified", "self_reported"]]
    ) -> dict[str, Literal["verified", "self_reported"]]:
        result: dict[str, Literal["verified", "self_reported"]] = {}
        for key, status in value.items():
            code = technology(key)
            if code in result:
                raise ValueError("duplicate_technology_alias")
            result[code] = status
        return result


class FixtureScope(AssessmentScope):
    format: Literal["jury-skill-100-v1"]


class FixtureCandidate(ContractModel):
    candidate_id: Identifier
    specialization: Literal["backend"]
    grade: GradeCode
    category_status: Literal["fixture_confirmed", "unconfirmed"]
    assessment_scope: FixtureScope
    skills: dict[SkillCode, FixtureEvidence]
    technologies: dict[TechCode, Literal["verified", "self_reported"]] = Field(
        json_schema_extra={"additionalProperties": False}
    )
    fsp_verified: StrictBool
    conditions: Conditions
    visibility: Visibility

    @field_validator("technologies")
    @classmethod
    def normalize_technologies(
        cls, value: dict[str, Literal["verified", "self_reported"]]
    ) -> dict[str, Literal["verified", "self_reported"]]:
        return Candidate.normalized_technologies(value)

    @model_validator(mode="after")
    def consistent_evidence(self) -> FixtureCandidate:
        """Согласует импортированные статусы, не достраивая баллы из грейда."""
        if self.category_status == "unconfirmed" and self.skills:
            raise ValueError("unconfirmed_has_evidence")
        for code, status in self.technologies.items():
            if status == "verified" and (
                self.category_status != "fixture_confirmed"
                or code not in VERIFIED_TECHNOLOGIES
                or VERIFIED_TECHNOLOGIES[code] not in self.skills
            ):
                raise ValueError("inconsistent_verified_technology:" + code)
        return self


class Dataset(ContractModel):
    schema_version: Literal["matching-fixture-v1"]
    dataset_id: Identifier
    as_of: datetime
    candidates: list[FixtureCandidate] = Field(max_length=1000)
    needs: list[Need] = Field(max_length=100)


class LabelPair(ContractModel):
    need_id: Identifier
    candidate_id: Identifier
    relevance: Annotated[StrictInt, Field(ge=0, le=3)]
    eligibility: Literal["eligible", "needs_clarification", "excluded"]


class Labels(ContractModel):
    schema_version: Literal["matching-labels-v1"]
    dataset_id: Identifier
    pairs: list[LabelPair] = Field(max_length=100000)


class Components(ContractModel):
    T: float
    K: float
    A: float
    F: float
    U: float
    P: float


class Recommendation(ContractModel):
    evidence_snapshot: dict[str, str] = Field(default_factory=dict)
    candidate_id: str
    grade: str
    group: Literal["eligible", "needs_clarification", "excluded"]
    score: float
    components: Components
    reasons: list[str]
    explanations: list[str]
    missing_conditions: list[str]
    skills: dict[SkillCode, Evidence]
    technologies: dict[str, Literal["verified", "self_reported", "absent"]]
    assessment_scope: AssessmentScope
    origin: str
    fsp_origin: str


class Ranking(ContractModel):
    need_id: str
    need_version: int
    algorithm: Literal["B0", "B1", "B2"]
    as_of: datetime
    recommendations: list[Recommendation]
