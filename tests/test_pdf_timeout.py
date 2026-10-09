import threading
from uuid import uuid4

import pytest

from app.candidate_profile import pdf
from app.candidate_profile.schemas import ContactsView, SafeCard, WorkPreferences
from app.core.errors import ApiError


async def test_blocked_pdf_returns_bounded_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started = threading.Event()

    def blocked(card: SafeCard, contacts: ContactsView | None) -> bytes:
        started.set()
        release.wait(timeout=5)
        return b"unused"

    monkeypatch.setattr(pdf, "generate_pdf", blocked)
    card = SafeCard(
        id=uuid4(),
        display_name="Кандидат",
        summary="",
        experience="",
        salary_min=None,
        salary_max=None,
        salary_basis="gross",
        available_from=None,
        work_preferences=WorkPreferences(),
        technology_ids=[],
        technology_names=[],
    )
    try:
        with pytest.raises(ApiError) as raised:
            await pdf.render_pdf(card, timeout_seconds=0.05)
        assert started.is_set()
        assert raised.value.status_code == 504
        assert raised.value.code == "pdf_generation_timeout"
    finally:
        release.set()
