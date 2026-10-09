import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from app.assessment.bank_checker import (
    GRADER_VERSION,
    BankQualityChecker,
    CheckRow,
    QualityReport,
    ReviewRecord,
    VersionReport,
    digest,
    grader_hash,
    public_summary,
    require_admission,
    validate_full_bank,
    validate_mappings,
)
from app.assessment.bank_models import FullBankVersion, load_bank
from app.assessment.candidate_tests import (
    CandidateTestEvaluator,
    TestEvaluation,
    apply_test_rubric,
)
from app.assessment.runner import (
    PYTHON_IMAGE,
    ExecutionRequest,
    ExecutionResult,
    RunnerUnavailable,
)
from app.assessment.structured_evaluator import equivalent, evaluate_structured
from app.tools.bank_quality import prepare_output, save_report

BANK = Path("bank/private/full.json")
BLUEPRINT = Path("bank/blueprints.json")
MAPPINGS = Path("bank/vacancy_mappings.json")
VERSIONS = load_bank(BANK).versions
TEST_VERSIONS = [v for v in VERSIONS if v.test_policy]


def test_full_coverage_actions_parameters_and_three_vacancies() -> None:
    bank = load_bank(BANK)
    validate_full_bank(bank, json.loads(BLUEPRINT.read_bytes()))
    validate_mappings(json.loads(MAPPINGS.read_bytes()), bank)
    assert len(bank.versions) == 24
    assert len(TEST_VERSIONS) == 4
    assert all(v.review_status == "pending" for v in bank.versions)
    for form in "XY":
        for grade in ("junior", "middle"):
            chosen = [
                v
                for v in bank.versions
                if v.family.startswith(form) and v.grade == grade
            ]
            for skill, count in (
                ("sql_data", 3),
                ("http_api", 3),
                ("language_algorithms", 2),
                ("debug_reliability", 2),
                ("security_validation", 2),
            ):
                assert sum(skill in v.skills for v in chosen) == count


@pytest.mark.parametrize("version", VERSIONS, ids=lambda v: f"{v.family}-{v.grade}")
def test_all_structured_references_alternatives_partial_errors_and_transfer(
    version: FullBankVersion,
) -> None:
    for task in version.structured_cases:
        for example in task.examples:
            assert evaluate_structured(task, example.answer) == example.expected_scores
        assert all(score == 0 for score in evaluate_structured(task, {}).values())


def test_sql_accepts_equivalent_plans_and_row_order_but_not_duplicates_or_bool() -> (
    None
):
    assert equivalent([{"id": 1}, {"id": 2}], [{"id": 2}, {"id": 1}], True)
    assert not equivalent([1, 1], [1], True)
    assert not equivalent(True, 1)
    task = next(v for v in VERSIONS if v.family == "X1").structured_cases[0]
    reference = task.examples[0].answer
    alternate = dict(reference, count_kind="count_amount")
    assert evaluate_structured(task, alternate) == {"sql_data": 4}
    assert evaluate_structured(task, {"sql": "SELECT perfectly correct SQL"}) == {
        "sql_data": 0
    }
    assert evaluate_structured(task, dict(alternate, groups=[])) == {"sql_data": 0}


@pytest.mark.parametrize(
    "change",
    [
        "missing_version",
        "duplicate_version",
        "missing_action",
        "missing_rubric",
        "duplicate_parameters",
        "missing_alternative",
        "no_transfer_witness",
        "wrong_form",
        "missing_B",
        "unknown_mapping",
    ],
)
def test_broken_materials_and_coverage_rejected(change: str) -> None:
    bank = load_bank(BANK)
    blueprint = json.loads(BLUEPRINT.read_bytes())
    mappings = json.loads(MAPPINGS.read_bytes())
    python = next(v for v in bank.versions if v.family == "X4")
    if change == "missing_version":
        bank.versions.pop()
    if change == "duplicate_version":
        bank.versions[-1] = bank.versions[0]
    if change == "missing_action":
        bank.versions[0].actions.clear()
    if change == "missing_rubric":
        bank.versions[0].rubric.clear()
    if change == "duplicate_parameters":
        python.cases[1].input = python.cases[0].input
        python.cases[2].input = python.cases[0].input
    if change == "missing_alternative":
        python.solutions = [s for s in python.solutions if s.kind != "alternative"]
    if change == "no_transfer_witness":
        next(s for s in python.solutions if s.kind == "unadapted").expected_passes = [
            c.id for c in python.cases
        ]
    if change == "wrong_form":
        blueprint["families"][0]["form"] = "Y"
    if change == "missing_B":
        blueprint["families"][4]["phase"] = "A"
    if change == "unknown_mapping":
        mappings["examples"][0]["rows"][0]["families"] = ["X99", "Y2"]
    with pytest.raises(ValueError):
        validate_full_bank(bank, blueprint)
        validate_mappings(mappings, bank)


@pytest.mark.parametrize(
    "version", TEST_VERSIONS, ids=lambda v: f"{v.family}-{v.grade}"
)
async def test_candidate_contract_and_infrastructure_separation(
    version: FullBankVersion,
) -> None:
    calls = 0

    async def unavailable(request: ExecutionRequest) -> ExecutionResult:
        nonlocal calls
        calls += 1
        raise RunnerUnavailable("offline")

    evaluator = CandidateTestEvaluator(unavailable)
    invalid_sets: list[list[dict[str, JsonValue]]] = [
        [],
        version.candidate_tests[:1],
        version.candidate_tests * 2,
        [{"input": {}, "expected": {}}] * 2,
        [{"source": "arbitrary code"}] * 2,
    ]
    for invalid in invalid_sets:
        assert (await evaluator.evaluate(version, invalid)).status == "invalid"
    invalid_input = copy.deepcopy(version.candidate_tests)
    value = invalid_input[0]["input"]
    assert isinstance(value, dict)
    value["start" if version.family == "X4" else "max_attempts"] = True
    assert (await evaluator.evaluate(version, invalid_input)).status == "invalid"
    large = copy.deepcopy(version.candidate_tests)
    large[0]["expected"] = {"padding": "x" * 17000}
    assert (await evaluator.evaluate(version, large)).status == "invalid"
    assert calls == 0
    result = await evaluator.evaluate(version, version.candidate_tests)
    assert result.status == "incomplete" and not result.detected_classes
    assert calls == 1


@pytest.mark.parametrize(
    "version", TEST_VERSIONS, ids=lambda v: f"{v.family}-{v.grade}"
)
@pytest.mark.parametrize(
    "status", ["timeout", "candidate_error", "output_limit", "runtime_error"]
)
async def test_execution_failure_never_detects_mutation(
    version: FullBankVersion, status: str
) -> None:
    async def broken(request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult.model_validate(
            {
                "status": status,
                "outputs": [],
                "runtime_image": PYTHON_IMAGE,
                "duration_ms": 1,
            }
        )

    result = await CandidateTestEvaluator(broken).evaluate(
        version, version.candidate_tests
    )
    assert result.status == "incomplete"
    assert result.detected_classes == [] and not result.mandatory_met


@pytest.mark.parametrize(
    "version", TEST_VERSIONS, ids=lambda v: f"{v.family}-{v.grade}"
)
async def test_wrong_expectation_has_no_credit_and_unrelated_skill_is_preserved(
    version: FullBankVersion,
) -> None:
    assert version.test_policy is not None
    correct = {
        s.source for s in version.solutions if s.kind in ("reference", "alternative")
    }
    expected = [c["expected"] for c in version.candidate_tests]

    async def prepared(request: ExecutionRequest) -> ExecutionResult:
        outputs = expected if request.source in correct else [{} for _ in expected]
        return ExecutionResult(
            status="completed",
            outputs=outputs,
            runtime_image=PYTHON_IMAGE,
            duration_ms=1,
        )

    wrong: list[dict[str, JsonValue]] = [
        {"input": c["input"], "expected": {"fabricated": True}}
        for c in version.candidate_tests
    ]
    result = await CandidateTestEvaluator(prepared).evaluate(version, wrong)
    assert not any(result.valid_cases) and not result.detected_classes
    scores: dict[str, int] = {s: 4 for s in version.skills}
    capped = apply_test_rubric(
        scores, version, result, base_correct=True, transfer_correct=True
    )
    assert capped[version.test_policy.skill] == 2
    assert capped["http_api"] == 4
    success = TestEvaluation(
        status="completed",
        valid_cases=[True, True],
        mandatory_met=True,
        additional_met=False,
    )
    assert (
        apply_test_rubric(
            scores, version, success, base_correct=True, transfer_correct=True
        )[version.test_policy.skill]
        == 3
    )
    success.additional_met = True
    assert (
        apply_test_rubric(
            scores, version, success, base_correct=True, transfer_correct=True
        )
        == scores
    )
    assert (
        apply_test_rubric(
            scores, version, success, base_correct=True, transfer_correct=False
        )[version.test_policy.skill]
        == 2
    )
    with pytest.raises(RunnerUnavailable):
        apply_test_rubric(
            scores,
            version,
            TestEvaluation(status="incomplete"),
            base_correct=True,
            transfer_correct=True,
        )


async def test_offline_runner_blocks_admission_with_partial_report() -> None:
    async def unavailable(request: ExecutionRequest) -> ExecutionResult:
        raise RunnerUnavailable("offline")

    report = await BankQualityChecker(unavailable).check(BANK)
    assert report.technical_status == "incomplete"
    assert report.technical_admission == "blocked"
    assert report.admission_status == "not_admitted"
    assert len(report.versions) == 24
    assert report.technical_errors
    assert any(v.status == "passed" and v.family == "X3" for v in report.versions)


@pytest.fixture
def successful_report() -> QualityReport:
    """Синтетический отчёт для тестов допуска, не свидетельство прогона."""
    rows: list[CheckRow] = []
    versions: list[VersionReport] = []
    for v in VERSIONS:
        start = len(rows)

        def add(
            kind: str, case: str, expected: JsonValue, version: FullBankVersion = v
        ) -> None:
            rows.append(
                CheckRow(
                    family=version.family,
                    grade=version.grade,
                    kind=kind,
                    case=case,
                    expected=expected,
                    actual=expected,
                    passed=True,
                )
            )

        for c in v.structured_cases:
            for i, e in enumerate(c.examples):
                add(
                    "structured:" + e.kind,
                    c.id + ":" + str(i),
                    {str(k): val for k, val in e.expected_scores.items()},
                )
        for s in v.solutions:
            for python_case in v.cases:
                add(
                    "python:" + s.kind,
                    s.id + ":" + python_case.id,
                    python_case.id in s.expected_passes,
                )
        if v.test_policy:
            add("candidate_tests", "all_classes", True)
            add("candidate_tests", "wrong_expectation", False)
            add("candidate_tests", "wrong_case_not_valid", False)
            add(
                "candidate_tests",
                "duplicates_no_gain",
                [str(x) for x in v.test_policy.mandatory],
            )
        versions.append(
            VersionReport(
                family=v.family,
                grade=v.grade,
                version=v.version,
                material_hash=digest(v.model_dump(mode="json")),
                status="passed",
                checks=len(rows) - start,
            )
        )
    return QualityReport(
        bank_version=load_bank(BANK).bank_version,
        bank_hash=hashlib.sha256(BANK.read_bytes()).hexdigest(),
        blueprint_hash=hashlib.sha256(BLUEPRINT.read_bytes()).hexdigest(),
        mappings_hash=hashlib.sha256(MAPPINGS.read_bytes()).hexdigest(),
        grader_version=GRADER_VERSION,
        grader_hash=grader_hash(),
        runtime_image=PYTHON_IMAGE,
        technical_status="passed",
        technical_admission="passed",
        checks=len(rows),
        versions=versions,
        results=rows,
        technical_errors=[],
        parameters={"fixture": True},
    )


def test_pending_review_blocks_credit_and_independent_record_must_bind_hashes(
    successful_report: QualityReport,
) -> None:
    require_admission(BANK, successful_report, technical_only=True)
    with pytest.raises(ValueError, match="independent_review_required"):
        require_admission(BANK, successful_report)
    review = ReviewRecord(
        reviewer="independent-test-reviewer",
        author=VERSIONS[0].author,
        reviewed_at=datetime.now(UTC),
        bank_hash=successful_report.bank_hash,
        blueprint_hash=successful_report.blueprint_hash,
        mappings_hash=successful_report.mappings_hash,
        decision="approved",
        evidence="synthetic fixture; not an actual review",
    )
    require_admission(BANK, successful_report, reviews=[review])
    review.reviewer = review.author
    with pytest.raises(ValueError, match="independent_review_required"):
        require_admission(BANK, successful_report, reviews=[review])
    review.reviewer = "independent-test-reviewer"
    review.bank_hash = "old"
    with pytest.raises(ValueError, match="independent_review_required"):
        require_admission(BANK, successful_report, reviews=[review])


@pytest.mark.parametrize(
    "change",
    [
        "failed",
        "incomplete",
        "grader",
        "grader_version",
        "runtime",
        "missing_version",
        "missing_result",
        "changed_expectation",
        "zero_checks",
        "material_hash",
    ],
)
def test_negative_admission_report(
    successful_report: QualityReport, change: str
) -> None:
    report = successful_report.model_copy(deep=True)
    if change == "failed":
        report.technical_status = "failed"
    if change == "incomplete":
        report.technical_errors.append("runner_unavailable")
    if change == "grader":
        report.grader_hash = "old"
    if change == "grader_version":
        report.grader_version = "old"
    if change == "runtime":
        report.runtime_image = "other"
    if change == "missing_version":
        report.versions.pop()
    if change == "missing_result":
        report.results.pop()
        report.checks -= 1
    if change == "changed_expectation":
        report.results[0].actual = None
    if change == "zero_checks":
        report.results.clear()
        report.checks = 0
    if change == "material_hash":
        report.versions[0].material_hash = "changed"
    with pytest.raises(ValueError):
        require_admission(BANK, report, technical_only=True)


@pytest.mark.parametrize(
    "target", ["condition", "rubric", "parameters", "solution", "blueprint", "mapping"]
)
def test_changed_material_bytes_invalidate_report(
    tmp_path: Path, successful_report: QualityReport, target: str
) -> None:
    bank = json.loads(BANK.read_bytes())
    blueprint = json.loads(BLUEPRINT.read_bytes())
    mapping = json.loads(MAPPINGS.read_bytes())
    v = bank["versions"][0]
    if target == "condition":
        v["condition"] += " changed"
    if target == "rubric":
        v["rubric"]["sql_data"]["4"] += " changed"
    if target == "parameters":
        v["cases"][0]["expected"] = ["changed"]
    if target == "solution":
        v["solutions"][0]["source"] += "\n# changed"
    if target == "blueprint":
        blueprint["version"] += "-changed"
    if target == "mapping":
        mapping["version"] += "-changed"
    paths = [
        tmp_path / name for name in ("bank.json", "blueprint.json", "mapping.json")
    ]
    for p, obj in zip(paths, [bank, blueprint, mapping], strict=True):
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    with pytest.raises(ValueError, match="materials_changed"):
        require_admission(
            paths[0],
            successful_report,
            technical_only=True,
            blueprint_path=paths[1],
            mappings_path=paths[2],
        )


def test_public_summary_contains_no_private_pool_or_solutions(
    tmp_path: Path, successful_report: QualityReport
) -> None:
    safe = public_summary(successful_report)
    assert set(safe) == {
        "bank_version",
        "bank_hash",
        "grader_version",
        "grader_hash",
        "technical_status",
        "checks",
        "versions_checked",
        "admission_status",
        "human_difficulty",
    }
    assert "results" not in safe and "X5" not in json.dumps(safe)
    save_report(tmp_path, successful_report.model_dump(mode="json"))
    assert json.loads((tmp_path / "public-summary.json").read_bytes()) == safe
    with pytest.raises(ValueError, match="output_directory_not_empty"):
        prepare_output(tmp_path)


def test_duplicate_json_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bank.json"
    path.write_text('{"bank_version":"one","bank_version":"two"}')
    with pytest.raises(ValueError, match="duplicate_json_key"):
        load_bank(path)
