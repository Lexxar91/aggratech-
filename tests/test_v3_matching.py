"""Совместимость v3 с общей формулой; fixture не является квалификацией."""

from app.assessment.v3_models import V3_METHODOLOGY
from app.matching.fixtures import candidates_from_fixture, example_dataset, model_input
from app.matching.schemas import Dataset
from app.matching.service import PRODUCT_METHODS, compute


def test_product_matching_preserves_v3_evidence_and_rejects_unknown_method() -> None:
    data = model_input(Dataset, example_dataset())
    candidate = candidates_from_fixture(data)[0]
    accepted = candidate.model_copy(
        update={
            "assessment_scope": candidate.assessment_scope.model_copy(
                update={"method_version": V3_METHODOLOGY}
            )
        }
    )
    unknown = accepted.model_copy(
        update={
            "assessment_scope": accepted.assessment_scope.model_copy(
                update={"method_version": "unsupported-method"}
            )
        }
    )
    ranking = compute(data.needs[0], [accepted], data.as_of, PRODUCT_METHODS)
    rejected = compute(data.needs[0], [unknown], data.as_of, PRODUCT_METHODS)
    assert ranking.recommendations[0].components.T > 0
    assert not rejected.recommendations or rejected.recommendations[0].components.T == 0
