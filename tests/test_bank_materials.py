import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.assessment.bank_quality import (
    BankMaterials,
    check_bank,
    structured_score,
    validate_materials,
)
from app.assessment.runner import ExecutionRequest, ExecutionResult, RunnerUnavailable


def test_blueprints_have_exact_required_coverage_and_disjoint_families() -> None:
    blueprint = json.loads(Path("bank/blueprints.json").read_text())
    for form in ("X", "Y"):
        families = [f for f in blueprint["families"] if f["form"] == form]
        assert len(families) == 6
        assert sum(f["phase"] == "A" for f in families) == 4
        assert sum(f["phase"] == "B" for f in families) == 2
        for skill, count in (
            ("sql_data", 3),
            ("http_api", 3),
            ("language_algorithms", 2),
            ("debug_reliability", 2),
            ("security_validation", 2),
        ):
            assert sum(skill in f["skills"] for f in families) == count
            if count == 3:
                assert any(f["phase"] == "B" and skill in f["skills"] for f in families)
    assert len({f["id"] for f in blueprint["families"]}) == 12


def test_first_two_families_are_complete_materials_without_claimed_admission() -> None:
    materials = BankMaterials.model_validate_json(
        Path("bank/private/stage1.json").read_bytes()
    )
    validate_materials(materials)
    assert all(version.review_status == "pending" for version in materials.versions)


def test_structured_rubric_distinguishes_partial_and_incorrect_answers() -> None:
    expected: JsonValue = [{"team": "a", "sum": 0, "count": 0}]
    assert (
        structured_score({"groups": expected, "count_kind": "all_rows"}, expected) == 2
    )
    assert (
        structured_score({"groups": expected, "count_kind": "non_null"}, expected) == 3
    )
    assert structured_score({"groups": []}, expected) == 0


def test_junior_materials_cover_empty_page_without_middle_requirements() -> None:
    materials = BankMaterials.model_validate_json(
        Path("bank/private/stage1.json").read_bytes()
    )
    junior = {v.family: v for v in materials.versions if v.grade == "junior"}
    text = json.dumps(junior["X1"].model_dump(), ensure_ascii=False).lower()
    assert "ревизи" not in text and "middle" not in text
    case = next(c for c in junior["X4"].cases if c.id == "empty_intermediate")
    assert isinstance(case.input, dict) and isinstance(case.expected, dict)
    assert case.expected["calls"] == ["a", "b", "c"]
    pages = case.input["pages"]
    assert isinstance(pages, dict) and isinstance(pages["b"], dict)
    assert pages["b"]["items"] == [] and pages["b"]["has_more"] is True


async def test_unavailable_runner_creates_incomplete_report_not_success() -> None:
    async def unavailable(request: ExecutionRequest) -> ExecutionResult:
        raise RunnerUnavailable("test_infrastructure_failure")

    report = await check_bank(Path("bank/private/stage1.json"), unavailable)
    assert report["technical_status"] == "incomplete"
    assert report["admission_status"] == "not_admitted"
    assert report["technical_errors"]
    assert report["checks"] == 24  # Только объективные структурированные примеры.


def test_missing_parameters_block_material_validation() -> None:
    materials = BankMaterials.model_validate_json(
        Path("bank/private/stage1.json").read_bytes()
    )
    materials.versions[0].cases.pop()
    with pytest.raises(ValueError, match="three_parameter_sets"):
        validate_materials(materials)
