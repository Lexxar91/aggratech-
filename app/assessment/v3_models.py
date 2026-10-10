"""Неизменяемые материалы v3; закрытые проверки не входят в публичные DTO."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.assessment.bank_models import Skill

V3_METHODOLOGY: Literal["backend-assessment-v3-packages-1"] = (
    "backend-assessment-v3-packages-1"
)
V3_SEEDS = [1729, 2718, 31415]


class V3Material(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class V3Solution(V3Material):
    """Исполняемые ответы сохраняются только в закрытом банке."""

    id: str
    kind: Literal["reference", "alternative", "mistake", "partial", "unadapted"]
    base: str
    transfer: str
    description: str
    seed: int | None = None


class V3Requirement(V3Material):
    """Связь наблюдаемого действия с навыком без дублирования общего балла."""

    id: str
    action: str
    skill: Skill
    evidence: str


class V3Card(V3Material):
    """Одна языковая карточка; family_id объединяет связанные PY/SQL."""

    task_id: str = Field(pattern=r"^[XY][1-6](?:-(?:PY|SQL))?-[JM]$")
    family_id: str = Field(pattern=r"^[XY][1-6]$")
    grade: Literal["junior", "middle"]
    form: Literal["X", "Y"]
    session: Literal["A", "B"]
    language: Literal["python", "sql"]
    title: str
    condition: str
    transfer: str
    common_contract: str
    source_start_line: int
    source_end_line: int
    source_hash: str
    rule_version: str = "published-v3.0"
    oracle_version: str = "v3-oracle-1"
    test_pack_version: str = "v3-packages-1"
    seeds: list[int] = Field(min_length=3)
    packs: dict[str, str]
    requirements: list[V3Requirement]
    solutions: list[V3Solution]
    developer_notes: str
    cases: list[V3Case] = Field(default_factory=list)
    parameter_manifests: list[dict[str, JsonValue]] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_identity(self) -> V3Card:
        """Не допускает подмены языка, семейства и пакетов при импорте."""
        if (
            self.task_id.split("-")[0] != self.family_id
            or self.family_id[0] != self.form
            or self.grade != ("junior" if self.task_id.endswith("-J") else "middle")
            or set(self.packs) != set("ABCD")
            or self.session != ("A" if self.family_id[1] in "1234" else "B")
        ):
            raise ValueError("v3_card_identity_mismatch")
        return self


class V3Bank(V3Material):
    """Полная поставка 28 карточек с трассировкой к принятому документу."""

    bank_version: Literal["3.0"] = "3.0"
    scope: Literal["executable-v3"] = "executable-v3"
    methodology: Literal["backend-assessment-v3-packages-1"] = V3_METHODOLOGY
    source_path: str
    source_hash: str
    cards: list[V3Card] = Field(min_length=28, max_length=28)

    @model_validator(mode="after")
    def complete_matrix(self) -> V3Bank:
        """Проверяет 14/14, 7 карточек формы и шесть независимых семейств."""
        if len({c.task_id for c in self.cards}) != 28:
            raise ValueError("v3_duplicate_task")
        for grade in ("junior", "middle"):
            for form in ("X", "Y"):
                group = [c for c in self.cards if c.grade == grade and c.form == form]
                if (
                    len(group) != 7
                    or {c.family_id for c in group}
                    != {f"{form}{i}" for i in range(1, 7)}
                    or sum(c.language == "sql" for c in group) != 3
                    or sum(c.session == "A" for c in group) != 5
                    or any(c.source_hash != self.source_hash for c in group)
                ):
                    raise ValueError("v3_incomplete_matrix")
        return self


class V3Assertion(V3Material):
    """Эталон отдельного наблюдения остаётся вне контейнера кандидата."""

    path: list[str]
    expected: JsonValue
    requirement_id: str
    skill: Skill
    critical: str | None = None
    comparison: Literal[
        "exact",
        "unordered",
        "minimum",
        "maximum",
        "count",
        "contains",
        "excludes",
        "one_of",
    ] = "exact"


class V3Case(V3Material):
    """Сценарий содержит входы отдельно от закрытых ожиданий оценщика."""

    id: str
    pack: Literal["A", "B", "C", "D"]
    phase: Literal["base", "transfer"]
    seed: int
    scenario: dict[str, JsonValue]
    assertions: list[V3Assertion] = Field(min_length=1)


class V3TaskGrade(V3Material):
    """Состояние отсутствия доказательств не кодируется числовым нулём."""

    status: Literal[
        "completed",
        "not_submitted",
        "incomplete",
        "environment_error",
        "invalid_item",
        "review_required",
    ]
    task_score: int | None = Field(default=None, ge=0, le=4)
    scores: dict[str, int] = Field(default_factory=dict)
    packs: dict[str, bool] = Field(default_factory=dict)
    checks: list[dict[str, JsonValue]] = Field(default_factory=list)
    critical_violations: list[str] = Field(default_factory=list)
    requirement_results: dict[str, bool] = Field(default_factory=dict)
