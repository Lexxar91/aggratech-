"""Версионированные коды matching, общие для CLI и приложения."""

import re
from typing import Literal

SkillCode = Literal[
    "language_algorithms",
    "sql_data",
    "http_api",
    "debug_reliability",
    "security_validation",
]
GradeCode = Literal["junior", "middle"]
WorkFormat = Literal["remote", "hybrid", "office"]
CATALOG_VERSION = "matching-catalog-v1"
ALGORITHM_VERSION = "matching-baseline-v1"
ADAPTER_VERSION = "matching-adapter-v1"
SKILLS: dict[SkillCode, str] = {
    "language_algorithms": "Python и алгоритмы",
    "sql_data": "SQL и данные",
    "http_api": "HTTP/API",
    "debug_reliability": "Отладка и надёжность",
    "security_validation": "Безопасность и валидация",
}
DEFAULT_PRIORITIES: dict[GradeCode, dict[SkillCode, int]] = {
    "junior": dict(zip(SKILLS, [20, 30, 20, 20, 10], strict=True)),
    "middle": dict(zip(SKILLS, [10, 20, 20, 30, 20], strict=True)),
}
TECHNOLOGIES: dict[str, list[str]] = {
    "python": ["python"],
    "sql": ["sql"],
    "postgresql": ["postgresql", "postgres"],
    "fastapi": ["fastapi"],
    "docker": ["docker"],
    "http_api": ["http_api", "http/api"],
}
TECHNOLOGY_PATTERN = (
    r"^\s*(?:"
    + "|".join(
        "".join(
            f"[{c.lower()}{c.upper()}]" if c.isalpha() else re.escape(c) for c in alias
        )
        for aliases in TECHNOLOGIES.values()
        for alias in aliases
    )
    + r")\s*$"
)
VERIFIED_TECHNOLOGIES: dict[str, SkillCode] = {
    "python": "language_algorithms",
    "sql": "sql_data",
    "http_api": "http_api",
}


def technology(value: str) -> str:
    """Нормализует только объявленные алиасы, не выводит навыки из названия
    framework."""
    normalized = value.strip().lower()
    for code, aliases in TECHNOLOGIES.items():
        if normalized in aliases:
            return code
    raise ValueError("unknown_technology")


def dictionary() -> dict[str, object]:
    """Поставляет словарь и допустимые доказательства проверенных технологий."""
    return {
        "version": CATALOG_VERSION,
        "specializations": ["backend"],
        "grades": ["junior", "middle"],
        "languages": ["python"],
        "formats": ["remote", "hybrid", "office"],
        "skills": SKILLS,
        "technologies": TECHNOLOGIES,
        "verified_technology_evidence": VERIFIED_TECHNOLOGIES,
        "score_format": "jury-skill-100-v1",
        ("method_version_rule"): (
            "One explicitly declared comparable method_version "
            "per dataset; fixture is not a real "
            "assessment."
        ),
    }
