"""Регрессии технического аудита; все credit/review fixtures только в test-БД."""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment import router, service
from app.assessment.bank_checker import QualityReport, ReviewRecord, grader_hash
from app.assessment.bank_models import FullBank, FullBankVersion
from app.assessment.models import AssessmentCycle, AssessmentPublication
from app.assessment.runtime_bank import admitted_bank, evaluator_hash
from app.candidate_profile.pdf import generate_pdf
from app.candidate_profile.service import card, own_profile
from app.core.config import Settings
from app.core.errors import ApiError
from app.matching.service import published_cycle
from app.notifications.queue import utc_now
from app.worker import process_one
from tests.test_auth_profiles import auth_app as _auth_app
from tests.test_auth_profiles import client as _client
from tests.test_stage3_bank import successful_report as _successful_report
from tests.test_stage4_cycles import candidate as _candidate
from tests.test_stage4_cycles import create, finish_fixture
from tests.test_stage4_grading import prepared_answer

auth_app = _auth_app
client = _client
candidate = _candidate
successful_report = _successful_report


def test_python314_assessment_imports_and_exception_syntax() -> None:
    assert sys.version_info[:2] == (3, 14)
    compile("try:\n pass\nexcept ValueError, OSError:\n pass", "audit", "exec")
    # Импорты выше загружают настоящий grading -> candidate_tests, без подмены.
    assert callable(process_one)


@pytest.mark.parametrize(
    "filename", ["grading.py", "policy.py", "runner.py", "uv.lock"]
)
def test_receipt_and_cycle_bind_all_evaluator_inputs(
    filename: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = evaluator_hash()
    read_bytes = Path.read_bytes

    def changed(path: Path) -> bytes:
        value = read_bytes(path)
        return value + b"\n# changed evaluator\n" if path.name == filename else value

    monkeypatch.setattr(Path, "read_bytes", changed)
    assert evaluator_hash() == grader_hash() != before
    with pytest.raises(ApiError) as failure:
        admitted_bank(Settings(), "demo")
    assert failure.value.code == "bank_not_admitted"


def reviewed_fixture(settings: Settings, report: QualityReport, tmp_path: Path) -> None:
    """Подготавливает исключительно синтетический допуск для изолированного теста."""
    report.admission_status = "admitted"
    settings.assessment_report = tmp_path / "fixture-report.json"
    settings.assessment_report.write_text(report.model_dump_json())
    settings.assessment_reviews = tmp_path / "fixture-review.json"
    review = ReviewRecord(
        reviewer="independent-fixture-reviewer",
        author="codex-stage3-author",
        reviewed_at=datetime.now(UTC),
        bank_hash=report.bank_hash,
        blueprint_hash=report.blueprint_hash,
        mappings_hash=report.mappings_hash,
        decision="approved",
        evidence="SYNTHETIC TEST ONLY; no human review or product admission",
    )
    settings.assessment_reviews.write_text("[" + review.model_dump_json() + "]")


def test_recorded_admitted_flag_does_not_replace_review(
    successful_report: QualityReport, tmp_path: Path
) -> None:
    settings = Settings()
    successful_report.admission_status = "admitted"
    settings.assessment_report = tmp_path / "forged-report.json"
    settings.assessment_report.write_text(successful_report.model_dump_json())
    with pytest.raises(ApiError) as failure:
        admitted_bank(settings, "credit")
    assert failure.value.code == "bank_not_admitted"
    reviewed_fixture(settings, successful_report, tmp_path)
    bank, report = admitted_bank(settings, "credit")
    assert isinstance(bank, FullBank)
    assert len(bank.versions) == 24 and report.admission_status == "admitted"
    settings.assessment_reviews = tmp_path / "missing-review.json"
    with pytest.raises(ApiError):
        admitted_bank(settings, "credit")


@pytest.mark.integration
@pytest.mark.parametrize("first,second", [("junior", "middle"), ("middle", "junior")])
@pytest.mark.parametrize("first_mode", ["demo", "credit"])
async def test_modes_keep_exposure_and_explicit_admission_snapshot(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    auth_app: FastAPI,
    successful_report: QualityReport,
    tmp_path: Path,
    first: str,
    second: str,
    first_mode: str,
) -> None:
    settings: Settings = auth_app.state.settings
    reviewed_fixture(settings, successful_report, tmp_path)
    response = await candidate.post(
        "/api/v1/assessment/cycles", json={"grade": first, "mode": first_mode}
    )
    assert response.status_code == 200, response.text
    initial = response.json()
    await finish_fixture(candidate, sessions, UUID(initial["id"]))
    second_mode = "credit" if first_mode == "demo" else "demo"
    response = await candidate.post(
        "/api/v1/assessment/cycles", json={"grade": second, "mode": second_mode}
    )
    assert response.status_code == 200, response.text
    cid = UUID(response.json()["id"])
    async with sessions() as db:
        one = await db.get(AssessmentCycle, UUID(str(initial["id"])))
        two = await db.get(AssessmentCycle, cid)
        assert one and two and one.form != two.form
        assert one.admission["review_passed"] is (first_mode == "credit")
        assert two.admission["review_passed"] is (second_mode == "credit")
        assert two.admission["admission_status"] == "admitted"
        assert two.admission["bank_hash"] == two.bank_hash
        assert two.admission["grader_hash"] == two.evaluator_hash == evaluator_hash()
        assert two.admission["blueprint_hash"] == successful_report.blueprint_hash
        assert two.admission["mappings_hash"] == successful_report.mappings_hash
    await finish_fixture(candidate, sessions, cid)
    # Нельзя обойти общий лимит двух циклов сменой режима или грейда.
    response = await candidate.post(
        "/api/v1/assessment/cycles", json={"grade": first, "mode": "demo"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "cycle_window_limit"


@pytest.mark.integration
@pytest.mark.parametrize("origin", ["fixture", "live_demo", None])
async def test_untrusted_credit_cannot_publish_or_leak_qualification_to_pdf(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    origin: str | None,
) -> None:
    created = await create(candidate)
    cid = UUID(str(created["id"]))
    await finish_fixture(candidate, sessions, cid)
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cid)
        assert cycle
        cycle.mode = "credit"
        cycle.admission = {"review_passed": True, "origin": origin}
        db.add(
            AssessmentPublication(
                user_id=cycle.user_id,
                mode="credit",
                cycle_id=cid,
                grade=cycle.grade,
                published_at=utc_now(),
            )
        )
        await db.flush()
        assert service.result_view(cycle).verified is False
        assert "Неподтверждённый" in service.result_view(cycle).label
        assert await service.published_result(db, cycle.user_id, owner=False) is None
        assert await service.published_result(db, cycle.user_id, owner=True) is None
        assert await published_cycle(db, cycle.user_id) is None
        profile = await own_profile(db, cycle.user_id)
        projected = await card(db, profile, owner=False)
        assert projected.assessment is None
        pdf = await asyncio.to_thread(generate_pdf, projected)
        text = " ".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
        assert "категория пока не подтверждена" in text
        assert "Грейд подтверждён" not in text
    response = await candidate.post(f"/api/v1/assessment/cycles/{cid}/publish")
    assert response.status_code == 409
    assert response.json()["code"] == "bank_not_admitted"


@pytest.mark.integration
@pytest.mark.runner
@pytest.mark.parametrize(
    "kind,outcome",
    [
        ("empty", "insufficient"),
        ("wrong", "not_confirmed"),
        ("base_only", "not_confirmed"),
        ("adapted", "confirmed"),
    ],
)
async def test_deadlines_submit_saved_drafts_without_changing_missing_or_wrong(
    candidate: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    auth_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    outcome: str,
) -> None:
    # Исторические серверные дедлайны: задания уже доступны настоящему worker.
    now = utc_now() - timedelta(minutes=45)
    monkeypatch.setattr(router, "utc_now", lambda: now)
    created = await create(candidate)
    cid = UUID(str(created["id"]))
    path = f"/api/v1/assessment/cycles/{cid}"
    for phase, deadline in (
        ("A", now + timedelta(minutes=30)),
        ("B", now + timedelta(minutes=45)),
    ):
        async with sessions() as db:
            cycle = await db.get(AssessmentCycle, cid)
            assert cycle
            tasks = [
                (r.family, r.parameter_index, service.material(cycle, r.family))
                for r in await service.answers(db, cid)
                if r.phase == phase
            ]
        if kind != "empty":
            for family, index, version in tasks:
                answer = prepared_answer(version, "base", index)
                revision, step = 0, "base"
                if kind == "wrong":
                    answer.source = "def solve(data):\n    return None"
                    answer.structured = {"unexpected": True}
                    answer.diagnosis = "unknown"
                    answer.tests = []
                elif kind == "adapted":
                    response = await candidate.post(
                        path + f"/answers/{family}/fix",
                        json={
                            "revision": 0,
                            "step": "base",
                            "answer": answer.model_dump(mode="json"),
                        },
                    )
                    assert response.status_code == 200, response.text
                    answer = prepared_answer(version, "transfer", index)
                    revision, step = 1, "transfer"
                response = await candidate.put(
                    path + f"/answers/{family}",
                    json={
                        "revision": revision,
                        "step": step,
                        "answer": answer.model_dump(mode="json"),
                    },
                )
                assert response.status_code == 200, response.text
        now = deadline
        response = await candidate.get(path)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == ("B_ready" if phase == "A" else "grading")
        if phase == "A":
            assert (await candidate.post(path + "/start-b")).status_code == 200
    for _ in range(6):
        assert await process_one(sessions, auth_app.state.settings)
    response = (await candidate.get(path)).json()
    assert response["state"] == "completed"
    assert response["result"]["outcome"] == outcome
    assert response["result"]["verified"] is False
    assert response["technical_issue"] is False
    async with sessions() as db:
        cycle = await db.get(AssessmentCycle, cid)
        assert cycle and cycle.a_submitted_at == cycle.a_deadline
        assert cycle.b_submitted_at == cycle.b_deadline
        for row in await service.answers(db, cid):
            assert row.draft == {} and row.finalized_at is not None
            if kind == "empty":
                assert row.scores == {}
            else:
                assert row.base and (
                    row.base.get("source") or row.base.get("structured")
                )
    if kind == "empty":
        assert response["result"]["total"] is None
        assert all(s["status"] == "not_checked" for s in response["result"]["skills"])


@pytest.mark.integration
async def test_public_tasks_and_validation_errors_never_contain_closed_materials(
    candidate: httpx.AsyncClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    created = await create(candidate)
    cid = UUID(str(created["id"]))
    async with sessions.begin() as db:
        cycle = await db.get(AssessmentCycle, cid)
        assert cycle
        materials = dict(cycle.materials)
        for family, raw in materials.items():
            version = service.material(cycle, family)
            assert isinstance(version, FullBankVersion)
            version.provenance = "PRIVATE_PROVENANCE_CANARY"
            version.rubric = {s: {"0": "PRIVATE_RUBRIC_CANARY"} for s in version.skills}
            for solution in version.solutions:
                solution.source += "\n# PRIVATE_REFERENCE_CANARY\n"
            for case in version.structured_cases:
                for example in case.examples:
                    example.answer["PRIVATE_ANSWER_CANARY"] = True
            assert isinstance(raw, dict)
            materials[family] = version.model_dump(mode="json")
        cycle.materials = materials
    path = f"/api/v1/assessment/cycles/{cid}"
    for endpoint in (path, "/api/v1/assessment/cycles"):
        response = await candidate.get(endpoint)
        assert response.status_code == 200
        assert "PRIVATE_" not in response.text
        assert '"phase":"B"' not in response.text
        for forbidden in ('"accepted"', '"expected_scores"', '"rubric"', '"solutions"'):
            assert forbidden not in response.text
    family = next(iter(materials))
    response = await candidate.put(
        path + f"/answers/{family}",
        json={
            "revision": 0,
            "step": "base",
            "answer": {"source": {"secret": "PRIVATE_INPUT_VALUE_CANARY"}},
        },
    )
    assert response.status_code == 422
    assert "PRIVATE_INPUT_VALUE_CANARY" not in response.text
    assert "PRIVATE_REFERENCE_CANARY" not in response.text
