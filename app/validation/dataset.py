"""Фиксированный синтетический эксперимент; не имитация человеческой разметки."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random

from app.matching.catalog import SKILLS
from app.matching.fixtures import validate_dataset
from app.matching.schemas import Dataset, FixtureCandidate, LabelPair, Labels, Need
from app.tools.matching_check import prepare_output, write_json

VERSION = "stage7-synthetic-v1"
SEED = 20261009
AS_OF = datetime(2026, 10, 9, 12, tzinfo=UTC)
THEMES = ("data", "api", "reliability", "security")


def make_data() -> tuple[Dataset, dict[str, object]]:
    """Фиксирует 120 профилей и непересекающиеся семейства разделения 40/80."""
    rng = Random(SEED)
    candidates: list[FixtureCandidate] = []
    candidate_metadata: list[dict[str, object]] = []
    for grade in ("junior", "middle"):
        index = 0
        for level, development_count in (("below", 4), ("boundary", 3), ("above", 3)):
            for fsp in (False, True):
                for replicate in range(10):
                    index += 1
                    split = (
                        "development" if replicate < development_count else "control"
                    )
                    identifier = f"{split[0]}-{grade[0]}-{index:03}"
                    confirmed = index % 17 != 0
                    # Баллы не выводятся из номинального уровня или fixture-грейда.
                    skills = (
                        {
                            skill: {
                                "score": rng.randint(30, 98),
                                "verified_at": AS_OF
                                - timedelta(days=rng.choice((10, 85, 120, 240))),
                                "mode": "independent",
                            }
                            for skill in SKILLS
                            if index % 13 != 0 or skill == "language_algorithms"
                        }
                        if confirmed
                        else {}
                    )
                    technologies: dict[str, str] = {
                        "python": "verified"
                        if "language_algorithms" in skills
                        else "self_reported"
                    }
                    for technology, skill in (
                        ("sql", "sql_data"),
                        ("http_api", "http_api"),
                    ):
                        if rng.random() < 0.8:
                            technologies[technology] = (
                                "verified"
                                if skill in skills and rng.random() < 0.7
                                else "self_reported"
                            )
                    if index % 3 == 0:
                        technologies["postgresql"] = "self_reported"
                    lower = (
                        rng.choice((70000, 100000, 130000))
                        if grade == "junior"
                        else rng.choice((130000, 170000, 210000))
                    )
                    candidate = FixtureCandidate.model_validate(
                        {
                            "candidate_id": identifier,
                            "specialization": "backend",
                            "grade": grade,
                            "category_status": "fixture_confirmed"
                            if confirmed
                            else "unconfirmed",
                            "assessment_scope": {
                                "language": "python",
                                "method_version": VERSION,
                                "format": "jury-skill-100-v1",
                            },
                            "skills": skills,
                            "technologies": technologies,
                            "fsp_verified": fsp,
                            "conditions": {
                                "salary_from": None if index % 11 == 0 else lower,
                                "salary_to": None if index % 11 == 0 else lower + 50000,
                                "work_formats": None
                                if index % 19 == 0
                                else rng.choice(
                                    (["remote"], ["remote", "hybrid"], ["office"])
                                ),
                                "location": rng.choice(("Москва", "Казань", None)),
                                "available_from": None
                                if index % 14 == 0
                                else (
                                    AS_OF + timedelta(days=rng.choice((0, 5, 15, 45)))
                                ).date(),
                                "confirmed_at": None
                                if index % 16 == 0
                                else AS_OF - timedelta(days=rng.choice((5, 95, 200))),
                            },
                            "visibility": {
                                "consent_to_match": index % 23 != 0,
                                "blocked_employer_ids": ["employer-03"]
                                if index % 29 == 0
                                else [],
                            },
                        }
                    )
                    candidates.append(candidate)
                    candidate_metadata.append(
                        {
                            "candidate_id": identifier,
                            "split": split,
                            "profile_family": identifier,
                            "nominal_preparedness": level,
                            "fsp_stratum": fsp,
                            "task_background": rng.sample(THEMES, 3),
                        }
                    )
    needs: list[Need] = []
    need_metadata: list[dict[str, object]] = []
    # Родственные junior/middle варианты остаются в одной части.
    definitions = (
        (
            "development",
            "legacy-normalizer",
            "data",
            {"language_algorithms": 2, "sql_data": 1},
            ["sql"],
            False,
        ),
        (
            "development",
            "paginated-client",
            "api",
            {"http_api": 2, "language_algorithms": 1},
            ["http_api"],
            False,
        ),
        (
            "control",
            "ledger-reconciliation",
            "data",
            {"sql_data": 2, "debug_reliability": 1},
            ["sql", "postgresql"],
            False,
        ),
        (
            "control",
            "webhook-contract",
            "api",
            {"http_api": 2, "security_validation": 1},
            ["http_api"],
            False,
        ),
        (
            "control",
            "queue-recovery",
            "reliability",
            {"debug_reliability": 2, "language_algorithms": 1},
            ["python", "postgresql"],
            True,
        ),
        (
            "control",
            "access-control",
            "security",
            {"security_validation": 2, "http_api": 1},
            ["http_api", "sql"],
            False,
        ),
    )
    for grade in ("junior", "middle"):
        for number, (
            split,
            family,
            theme,
            priorities,
            preferred,
            required_date,
        ) in enumerate(definitions):
            identifier = f"{split[0]}-{grade[0]}-{family}"
            need = Need.model_validate(
                {
                    "need_id": identifier,
                    "employer_id": f"employer-{number + 1:02}",
                    "title": f"Тестовая потребность: {family} / {grade}",
                    "specialization": "backend",
                    "accepted_grades": [grade],
                    "required_stack": [
                        {"technology": "python", "verification_required": False}
                    ],
                    "preferred_stack": [x for x in preferred if x != "python"],
                    "skill_priorities": priorities,
                    "required_verified_skills": [],
                    "work_formats": ["remote"]
                    if number % 2 == 0
                    else ["remote", "hybrid"],
                    "location": None if number % 2 == 0 else "Москва",
                    "salary_from": 90000 if grade == "junior" else 160000,
                    "salary_to": 150000 if grade == "junior" else 230000,
                    "desired_start_date": (AS_OF + timedelta(days=7)).date(),
                    "start_date_required": required_date,
                    "role": family,
                    "team_description": "Синтетическая команда",
                    "task_description": (
                        f"Искусственный сценарий: {family}; тема {theme}."
                    ),
                    "urgency": "normal",
                }
            )
            need = need.model_copy(
                update={
                    "salary_from": need.salary_from + number * 5000,
                    "salary_to": need.salary_to + number * 5000,
                    "urgency": "urgent"
                    if required_date
                    else "flexible"
                    if number % 3 == 2
                    else "normal",
                }
            )
            needs.append(need)
            need_metadata.append(
                {
                    "need_id": identifier,
                    "split": split,
                    "need_family": family,
                    "task_theme": theme,
                }
            )
    dataset = Dataset(
        schema_version="matching-fixture-v1",
        dataset_id=VERSION,
        as_of=AS_OF,
        candidates=candidates,
        needs=needs,
    )
    validate_dataset(dataset)
    passport: dict[str, object] = {
        "version": VERSION,
        "seed": SEED,
        "as_of": AS_OF.isoformat(),
        "source": "synthetic_generated",
        "human_labeling": "deferred_to_stage9",
        "weights_tuned": False,
        "nominal_preparedness_not_score_or_truth": True,
        "employers": [
            {"employer_id": f"employer-{i:02}", "source": "synthetic"}
            for i in range(1, 7)
        ],
        "candidate_metadata": candidate_metadata,
        "need_metadata": need_metadata,
    }
    return dataset, passport


def eligibility(need: Need, candidate: FixtureCandidate) -> str:
    """Технический oracle условий написан отдельно от фильтра; не экспертный эталон."""
    c = candidate.conditions
    forbidden = (
        candidate.grade not in need.accepted_grades
        or candidate.category_status != "fixture_confirmed"
        or not candidate.visibility.consent_to_match
        or need.employer_id in candidate.visibility.blocked_employer_ids
    )
    forbidden |= any(
        t.technology not in candidate.technologies
        or (
            t.verification_required
            and candidate.technologies[t.technology] != "verified"
        )
        for t in need.required_stack
    )
    forbidden |= any(s not in candidate.skills for s in need.required_verified_skills)
    unknown = c.salary_from is None or not c.work_formats
    if c.salary_from is not None:
        forbidden |= c.salary_from > need.salary_to or (
            c.salary_to is not None and c.salary_to < need.salary_from
        )
    intersection = set(c.work_formats or ()) & set(need.work_formats)
    if c.work_formats:
        forbidden |= not intersection
        if intersection and "remote" not in intersection:
            unknown |= c.location is None
            forbidden |= c.location is not None and c.location != need.location
    if need.desired_start_date:
        unknown |= c.available_from is None
        forbidden |= bool(
            need.start_date_required
            and c.available_from
            and c.available_from > need.desired_start_date
        )
    return "excluded" if forbidden else "needs_clarification" if unknown else "eligible"


def synthetic_labels(dataset: Dataset, passport: dict[str, object]) -> Labels:
    """Заранее заданная task-fit игрушечная релевантность не зависит от Score."""
    metadata = passport["candidate_metadata"]
    queries = passport["need_metadata"]
    assert isinstance(metadata, list) and isinstance(queries, list)
    backgrounds = {
        m["candidate_id"]: m["task_background"] for m in metadata if isinstance(m, dict)
    }
    themes = {m["need_id"]: m["task_theme"] for m in queries if isinstance(m, dict)}
    pairs = []
    for need in dataset.needs:
        for candidate in dataset.candidates:
            background = backgrounds[candidate.candidate_id]
            theme = themes[need.need_id]
            relevance = (
                3
                if background[0] == theme
                else 2
                if background[1] == theme
                else 1
                if background[2] == theme
                else 0
            )
            pairs.append(
                LabelPair.model_validate(
                    {
                        "need_id": need.need_id,
                        "candidate_id": candidate.candidate_id,
                        "relevance": relevance,
                        "eligibility": eligibility(need, candidate),
                    }
                )
            )
    return Labels(
        schema_version="matching-labels-v1", dataset_id=dataset.dataset_id, pairs=pairs
    )


def write_data(destination: Path) -> None:
    """Создаёт паспорт, общий набор и отдельные разработочный/контрольный входы."""
    prepare_output(destination)
    dataset, passport = make_data()
    root = Path(__file__).resolve().parents[2]
    bank_report = json.loads((root / "bank/private/technical_report.json").read_bytes())
    passport["assessment_baseline"] = {
        k: bank_report[k]
        for k in (
            "bank_version",
            "bank_hash",
            "grader_version",
            "grader_hash",
            "admission_status",
        )
    }
    passport["validation_rules"] = (
        "docs/03 matching + docs/04 validation; human review deferred stage9"
    )
    passport["success_criteria"] = {
        "metric_tolerance": 1e-12,
        "deterministic_artifacts_equal": True,
        "privacy_violations": 0,
        "eligibility_errors": 0,
    }
    passport["schema_sha256"] = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name in ("dataset.schema.json", "labels.schema.json")
        if (path := root / "fixtures/jury/matching" / name).is_file()
    }
    write_json(destination / "dataset.json", dataset.model_dump(mode="json"))
    write_json(destination / "passport.json", passport)
    for split in ("development", "control"):
        candidates = [
            c for c in dataset.candidates if c.candidate_id.startswith(split[0] + "-")
        ]
        needs = [n for n in dataset.needs if n.need_id.startswith(split[0] + "-")]
        part = dataset.model_copy(
            update={
                "dataset_id": f"{VERSION}-{split}",
                "candidates": candidates,
                "needs": needs,
            }
        )
        write_json(destination / f"{split}.dataset.json", part.model_dump(mode="json"))
        write_json(
            destination / f"{split}.labels.synthetic.json",
            synthetic_labels(part, passport).model_dump(mode="json"),
        )
        write_json(
            destination / f"{split}.labels.human.template.json",
            Labels(
                schema_version="matching-labels-v1",
                dataset_id=part.dataset_id,
                pairs=[],
            ).model_dump(mode="json"),
        )
