"""Регрессия PDF-кнопки на искусственной квалификации только в aggratech_test."""

import asyncio
import os
import socket
from pathlib import Path

import httpx
import pytest
from playwright.async_api import Browser, expect
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_auth_profiles import KEY, PASSWORD, login, register
from tests.test_auth_profiles import auth_app as auth_app
from tests.test_auth_profiles import client as client
from tests.test_matching_api import need_body, synthetic_credit, verified
from tests.test_stage2_browser import browser as browser
from tests.test_stage2_browser import launch_api, stop, wait_api

pytestmark = pytest.mark.integration


async def test_matching_pdf_button_uses_protected_route_and_current_privacy(
    browser: Browser,
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Настоящая кнопка скачивает разрешённый PDF; скрытая карточка исчезает."""
    user_id = await register(client)
    candidate_id = await synthetic_credit(sessions, user_id)
    candidate_token = await login(client)
    assert (
        await client.patch(
            "/api/v1/candidate/contacts", json={"email": "private-pdf@example.com"}
        )
    ).status_code == 200
    assert (
        await client.patch(
            "/api/v1/candidate/privacy",
            json={"visible_to_employers": True, "show_name": False},
        )
    ).status_code == 200
    employer_id = await register(client, "employer@example.com", "employer")
    await verified(sessions, employer_id)
    await login(client, "employer@example.com")
    need = await client.post("/api/v1/employer/needs", json=need_body())
    assert need.status_code == 200
    response = await client.post(
        f"/api/v1/employer/needs/{need.json()['need_id']}/recommendations", json={}
    )
    assert response.status_code == 200
    snapshot = response.json()
    assert len(snapshot["entries"]) == 1
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        "APP_DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "APP_PUBLIC_ORIGIN": origin,
        "APP_ALLOWED_ORIGINS": "[]",
        "APP_JWT_SECRET": KEY,
    }
    process = await asyncio.to_thread(
        launch_api, environment, port, tmp_path / "api.log"
    )
    context = await browser.new_context(accept_downloads=True)
    try:
        await wait_api(origin, process)
        page = await context.new_page()
        await page.add_init_script(
            "document.addEventListener('DOMContentLoaded', () => {"
            "const banner=document.createElement('aside');"
            "banner.textContent='TEST ONLY: synthetic qualification, not human review';"
            "document.body.prepend(banner);});"
        )
        await page.goto(origin + "/#login")
        await page.locator("#email").fill("employer@example.com")
        await page.locator("#password").fill(PASSWORD)
        await page.get_by_role("button", name="Войти", exact=True).click()
        await page.wait_for_url("**/#profile")
        await page.goto(origin + "/#recommendations/" + snapshot["id"])
        button = page.get_by_role("button", name="PDF", exact=True)
        await expect(button).to_be_visible()
        async with page.expect_response(
            lambda result: result.url.endswith(
                f"/candidates/{candidate_id}/profile.pdf"
            )
        ) as pdf_response:
            async with page.expect_download() as download:
                await button.click()
        assert (await pdf_response.value).status == 200
        path = await (await download.value).path()
        assert path
        content = "".join(p.extract_text() for p in PdfReader(path).pages)
        assert "Кандидат" in content
        assert "Тестовая Анна" not in content
        assert "private-pdf@example.com" not in content
        client.headers["Authorization"] = f"Bearer {candidate_token}"
        assert (
            await client.patch(
                "/api/v1/candidate/privacy", json={"visible_to_employers": False}
            )
        ).status_code == 200
        await page.reload()
        await expect(
            page.get_by_text("Карточка недоступна.", exact=True)
        ).to_be_visible()
        await expect(page.get_by_role("button", name="PDF", exact=True)).to_have_count(
            0
        )
    finally:
        await context.close()
        await asyncio.to_thread(stop, process)
