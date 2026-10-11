"""Контроль вычислений на синтетике; не человеческий пилот и не допуск банка."""

import json
import re
from collections import Counter
from math import log2
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.matching.engine import rank
from app.matching.fixtures import candidates_from_fixture, load_dataset, load_labels
from app.matching.metrics import measure
from app.matching.schemas import Dataset, LabelPair, Labels, Ranking
from app.tools.validation_report import run, verify_calculations
from app.validation.calculations import control_aggregates, control_metrics
from app.validation.dataset import make_data, synthetic_labels, write_data
from app.validation.experiments import COMPONENTS, ablate
from app.validation.summary import Attempt, HumanRegistry, summarize


def rankings(data: Dataset) -> list[Ranking]:
    candidates = candidates_from_fixture(data)
    methods = frozenset(c.assessment_scope.method_version for c in candidates)
    return [
        rank(n, candidates, as_of=data.as_of, comparable_methods=methods, algorithm=a)
        for a in ("B0", "B1", "B2")
        for n in data.needs
    ]


def test_stratification_and_disjoint_split(tmp_path: Path) -> None:
    data, passport = make_data()
    assert len(data.candidates) == 120 and len(data.needs) == 12
    assert len({n.employer_id for n in data.needs}) == 6
    assert Counter(c.grade for c in data.candidates) == {"junior": 60, "middle": 60}
    rows = passport["candidate_metadata"]
    assert isinstance(rows, list)
    cells = Counter(
        (r["nominal_preparedness"], r["fsp_stratum"], r["candidate_id"][2])
        for r in rows
    )
    assert len(cells) == 12 and set(cells.values()) == {10}
    destination = tmp_path / "input"
    write_data(destination)
    dev, _ = load_dataset(destination / "development.dataset.json")
    control, _ = load_dataset(destination / "control.dataset.json")
    assert (len(dev.candidates), len(dev.needs)) == (40, 4)
    assert (len(control.candidates), len(control.needs)) == (80, 8)
    assert Counter(c.grade for c in dev.candidates) == {"junior": 20, "middle": 20}
    assert Counter(c.grade for c in control.candidates) == {"junior": 40, "middle": 40}
    assert not {c.candidate_id for c in dev.candidates} & {
        c.candidate_id for c in control.candidates
    }
    assert not {n.role for n in dev.needs} & {n.role for n in control.needs}
    assert sum(c.fsp_verified for c in control.candidates) == 40
    for split in ("development", "control"):
        part, _ = load_dataset(destination / f"{split}.dataset.json")
        labels, _ = load_labels(destination / f"{split}.labels.synthetic.json", part)
        assert len(labels.pairs) == len(part.needs) * len(part.candidates)
        assert set(p.relevance for p in labels.pairs) == {0, 1, 2, 3}


def test_frozen_inputs_regenerate_exactly(tmp_path: Path) -> None:
    write_data(tmp_path / "a")
    write_data(tmp_path / "b")
    for path in (tmp_path / "a").iterdir():
        assert path.read_bytes() == (tmp_path / "b" / path.name).read_bytes()
        assert (
            path.read_bytes()
            == (Path("fixtures/validation/stage7") / path.name).read_bytes()
        )


def test_labels_do_not_use_score() -> None:
    data, passport = make_data()
    original = synthetic_labels(data, passport)
    altered = data.model_copy(
        update={
            "candidates": [
                c.model_copy(
                    update={
                        "skills": {
                            k: v.model_copy(update={"score": 100 - v.score})
                            for k, v in c.skills.items()
                        }
                    }
                )
                for c in data.candidates
            ]
        }
    )
    assert synthetic_labels(altered, passport) == original


def test_independent_calculations_full_control() -> None:
    data, _ = load_dataset(Path("fixtures/validation/stage7/control.dataset.json"))
    labels, _ = load_labels(
        Path("fixtures/validation/stage7/control.labels.synthetic.json"), data
    )
    ranks = rankings(data)
    metrics = measure(data, ranks, labels)
    assert verify_calculations(data, ranks, labels, metrics) > 500
    rows = metrics["records"]
    assert isinstance(rows, list) and len(rows) == 48
    assert all(
        not r["eligibility_errors"] and not r["privacy_violations"] for r in rows
    )


def test_known_short_list_and_full_ideal_pool() -> None:
    data, passport = make_data()
    # Один выдаваемый и ещё один релевантный в полном oracle, независимо от выдачи.
    candidates = [c for c in data.candidates if c.grade == "junior"][:2]
    data = data.model_copy(update={"candidates": candidates, "needs": [data.needs[0]]})
    ranking = rankings(data)[0]
    rows = [r.model_copy(update={"group": "eligible"}) for r in ranking.recommendations]
    ranking = ranking.model_copy(update={"recommendations": rows[:1]})
    labels = Labels(
        schema_version="matching-labels-v1",
        dataset_id=data.dataset_id,
        pairs=[
            LabelPair(
                need_id=data.needs[0].need_id,
                candidate_id=rows[0].candidate_id,
                relevance=2,
                eligibility="eligible",
            ),
            LabelPair(
                need_id=data.needs[0].need_id,
                candidate_id=rows[1].candidate_id,
                relevance=3,
                eligibility="eligible",
            ),
        ],
    )
    result = control_metrics(data, [ranking], labels)[0]
    assert result["precision_at_10"] == 0.1  # Не 1/короткая выдача.
    assert result["recall_at_20"] == 0.5
    assert result["ndcg_at_10"] == pytest.approx(3 / (7 + 3 / log2(3)))
    assert result["relevant_in_oracle"] == 2
    assert synthetic_labels(data, passport).pairs  # Fixture-source остаётся явным.


@pytest.mark.parametrize("empty", [True, False])
def test_missing_and_empty_oracles(empty: bool) -> None:
    data, passport = make_data()
    ranks = rankings(data)
    labels = synthetic_labels(data, passport)
    labels = labels.model_copy(update={"pairs": [] if empty else labels.pairs[1:]})
    assert verify_calculations(data, ranks, labels, measure(data, ranks, labels)) > 500
    need_id = data.needs[0].need_id
    assert all(
        r["precision_at_10"] is None
        for r in control_metrics(data, ranks, labels)
        if r["need_id"] == need_id
    )


def test_average_gives_equal_weight_to_needs() -> None:
    rows = [
        {
            "algorithm": "B2",
            "group": "eligible",
            "need_id": "one",
            "precision_at_10": 0.2,
        },
        {
            "algorithm": "B2",
            "group": "eligible",
            "need_id": "one",
            "precision_at_10": 0.4,
        },
        {
            "algorithm": "B2",
            "group": "eligible",
            "need_id": "two",
            "precision_at_10": 0.9,
        },
    ]
    assert control_aggregates(rows, "precision_at_10")[
        ("B2", "eligible")
    ] == pytest.approx(0.6)


@pytest.mark.parametrize("component", COMPONENTS)
def test_component_experiments_keep_groups_and_weights(component: str) -> None:
    data, _ = make_data()
    before = next(r for r in rankings(data) if r.algorithm == "B2")
    assert component in COMPONENTS
    # Параметр pytest поступает как str; выбор из типизированного списка явный.
    selected = next(c for c in COMPONENTS if c == component)
    after = ablate(before, selected)
    originals = {r.candidate_id: r for r in before.recommendations}
    for r in after.recommendations:
        assert r.group == originals[r.candidate_id].group
        if r.group == "excluded":
            assert r == originals[r.candidate_id]
        else:
            c = r.components
            assert c.T == originals[r.candidate_id].components.T
            assert c.K == originals[r.candidate_id].components.K
            assert r.score == pytest.approx(
                round(
                    max(
                        0,
                        min(
                            100, 55 * c.T + 25 * c.K + 8 * c.A + 7 * c.F + 5 * c.U - c.P
                        ),
                    ),
                    6,
                )
            )
    assert before == next(r for r in rankings(data) if r.algorithm == "B2")


def test_fsp_matched_pair_changes_only_F() -> None:
    data, _ = make_data()
    candidates = candidates_from_fixture(data)
    need = data.needs[0]
    methods = frozenset(c.assessment_scope.method_version for c in candidates)
    baseline = rank(need, candidates, as_of=data.as_of, comparable_methods=methods)
    chosen = next(
        r for r in baseline.recommendations if r.group == "eligible" and r.score < 90
    )
    candidate = next(c for c in candidates if c.candidate_id == chosen.candidate_id)
    without = rank(
        need,
        [candidate.model_copy(update={"fsp_verified": False})],
        as_of=data.as_of,
        comparable_methods=methods,
    ).recommendations[0]
    with_fsp = rank(
        need,
        [candidate.model_copy(update={"fsp_verified": True})],
        as_of=data.as_of,
        comparable_methods=methods,
    ).recommendations[0]
    assert with_fsp.score - without.score == pytest.approx(7, abs=1e-6)
    assert with_fsp.components.model_dump(
        exclude={"F"}
    ) == without.components.model_dump(exclude={"F"})
    assert without.components.F == 0
    assert any("нет подтверждённой истории" in text for text in without.explanations)


def test_explanations_trace_actual_evidence_without_private_data() -> None:
    data, _ = make_data()
    for ranking in rankings(data):
        for row in ranking.recommendations:
            if row.group == "excluded":
                assert not row.explanations
                continue
            assert row.origin == "jury_fixture"
            assert any("fixture" in text for text in row.explanations)
            if row.group == "needs_clarification":
                assert row.missing_conditions
            for text in row.explanations:
                assert "@" not in text and "bank/private" not in text


def attempt(**updates: object) -> Attempt:
    value: dict[str, object] = {
        "cycle_token": "cycle-human",
        "subject_token": "person-human",
        "mode": "credit",
        "origin": "live_credit",
        "review_status": "passed",
        "family": "X4",
        "item_version": "v1",
        "evaluator_version": "e1",
        "grade": "junior",
        "form": "X",
        "created_at": "2026-10-09T12:00:00Z",
        "shown": True,
        "finalized": True,
        "grading_status": "completed",
        "scores": {"debug_reliability": 3},
        "base_correct": True,
        "transfer_correct": False,
        "tests_valid": True,
        "mandatory_tests_met": None,
    }
    value.update(updates)
    return Attempt.model_validate(value)


def test_summary_reconciles_attempts_and_excludes_non_humans() -> None:
    records = [
        attempt(),
        attempt(
            cycle_token="technical-real",
            grading_status="technical_error",
            base_correct=False,
            technical_intervention=True,
            technical_reason="assessment_infrastructure_unavailable",
        ),
        attempt(cycle_token="demo", mode="demo"),
        attempt(cycle_token="fixture", fixture_notice=True),
        attempt(cycle_token="seed", origin="seed"),
        attempt(cycle_token="unknown"),
    ]
    registry = HumanRegistry(
        independently_verified=True,
        cycle_tokens=["cycle-human", "technical-real", "demo", "fixture", "seed"],
    )
    result = summarize(records, registry)
    assert result["observed_candidates"] == 1
    assert result["source_attempts"] == 6 and result["excluded_attempts"] == 4
    rows = result["rows"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["shown_attempts"] == 2 and row["technically_completed"] == 1
    assert row["requirements_met"] == 1 and row["technical_errors"] == 1
    assert row["cycles_with_technical_intervention"] == 1
    assert row["technical_reasons"] == {"assessment_infrastructure_unavailable": 1}
    assert row["stages"]["base_correct"] == {"checked": 1, "failed": 0, "missing": 0}
    assert row["stages"]["transfer_correct"]["failed"] == 1
    assert row["stages"]["mandatory_tests_met"]["missing"] == 1
    assert "person-human" not in json.dumps(result) and "cycle-human" not in json.dumps(
        result
    )


def test_summary_missing_provenance_unshown_pending_and_duplicates() -> None:
    registry = HumanRegistry(independently_verified=True, cycle_tokens=["cycle-human"])
    assert summarize([attempt()], HumanRegistry())["status"] == "нет данных"
    assert summarize([attempt(shown=False)], registry)["status"] == "нет данных"
    result = summarize([attempt(finalized=False, grading_status="pending")], registry)
    rows = result["rows"]
    assert isinstance(rows, list) and rows[0]["technically_completed"] == 0
    assert rows[0]["stages"]["transfer_correct"] == "нет данных"
    recovered = summarize([attempt(technical_intervention=True)], registry)["rows"]
    assert isinstance(recovered, list)
    assert recovered[0]["technical_errors"] == 0
    assert recovered[0]["cycles_with_technical_intervention"] == 1
    assert recovered[0]["requirements_met"] == 1
    with pytest.raises(ValueError, match="human_provenance_not_verified"):
        summarize([attempt()], HumanRegistry(cycle_tokens=["cycle-human"]))
    with pytest.raises(ValueError, match="duplicate_attempt"):
        summarize([attempt(), attempt()], registry)
    with pytest.raises(ValidationError):
        attempt(email="must-not-be-exported@example.test")
    with pytest.raises(ValidationError):
        attempt(scores={"debug_reliability": 5})


def test_report_repeatability_and_safe_public_artifacts(tmp_path: Path) -> None:
    saved = tmp_path / "private.json"
    saved.write_text(json.dumps([attempt(mode="demo").model_dump(mode="json")]))
    registry = tmp_path / "registry.json"
    registry.write_text(HumanRegistry().model_dump_json())
    for name in ("a", "b"):
        run(Path("fixtures/validation/stage7"), saved, registry, tmp_path / name)
    for path in (tmp_path / "a").rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(tmp_path / "a")
        if path.name == "timings.json":
            continue
        if path.name == "run_manifest.json" and relative.parts[0] in (
            "synthetic",
            "human-unmeasured",
        ):
            before, after = (
                json.loads(path.read_bytes()),
                json.loads((tmp_path / "b" / relative).read_bytes()),
            )
            before.pop("duration_seconds")
            after.pop("duration_seconds")
            assert before == after
        else:
            assert path.read_bytes() == (tmp_path / "b" / relative).read_bytes()
        text = path.read_text()
        assert "person-human" not in text and "cycle-human" not in text
        assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
        assert "bank/private" not in text
        assert "reference_source" not in text and "expected_outputs" not in text
    human = json.loads((tmp_path / "a/human-unmeasured/metrics.json").read_bytes())
    assert all(
        r["status"] == "not_measured" and r["precision_at_10"] is None
        for r in human["records"]
    )
    assert "не измерено" in (tmp_path / "a/report.md").read_text()
    assert (
        json.loads((tmp_path / "a/assessment_summary.json").read_bytes())["status"]
        == "нет данных"
    )
