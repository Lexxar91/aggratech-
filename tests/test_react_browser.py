"""React-сценарий на PostgreSQL fixture, без реальных подтверждений и людей."""

import asyncio
import os
import socket
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from playwright.async_api import Browser, Page, expect
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.test_auth_profiles import KEY, PASSWORD, login, register
from tests.test_auth_profiles import auth_app as auth_app
from tests.test_auth_profiles import client as client
from tests.test_matching_api import synthetic_credit, verified
from tests.test_stage2_browser import browser as browser
from tests.test_stage2_browser import launch_api, stop, wait_api

pytestmark = pytest.mark.integration


async def ui_login(
    page: Page, origin: str, email: str, password: str = PASSWORD
) -> None:
    await page.goto(origin + "/#login")
    await page.get_by_label("Email", exact=True).fill(email)
    await page.locator('[name="password"]').fill(password)
    await page.get_by_role("button", name="Войти", exact=True).click()
    await expect(page.get_by_role("heading", level=1)).to_have_text(
        "Кабинет кандидата" if "candidate" in email else "Кабинет работодателя"
    )


async def test_react_invitation_application_privacy_and_mobile(
    browser: Browser,
    client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Обе роли работают через React; согласия и PDF проверяются на сервере."""
    candidate_email = "react-candidate@example.com"
    employer_email = "react-employer@example.com"
    candidate_password = f" {PASSWORD} "
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "email": candidate_email,
            "password": candidate_password,
            "role": "candidate",
        },
    )
    assert registration.status_code == 201
    uid = UUID(registration.json()["id"])
    candidate_id = await synthetic_credit(sessions, uid)
    await verified(sessions, uid)
    await login(client, candidate_email, candidate_password)
    await client.patch(
        "/api/v1/candidate/contacts",
        json={"email": "react-private@example.com", "phone": "+79991112233"},
    )
    await client.patch(
        "/api/v1/candidate/privacy",
        json={"visible_to_employers": True, "show_name": False},
    )
    comparison_uid = await register(client, "react-comparison@example.com")
    comparison_id = await synthetic_credit(sessions, comparison_uid)
    await verified(sessions, comparison_uid)
    employer = await register(client, employer_email, "employer")
    await verified(sessions, employer)
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
    cc = await browser.new_context(accept_downloads=True)
    ec = await browser.new_context(accept_downloads=True)
    errors: list[str] = []
    try:
        await wait_api(origin, process)
        candidate = await cc.new_page()
        employer_page = await ec.new_page()
        for page in (candidate, employer_page):
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.add_init_script(
                "document.addEventListener('DOMContentLoaded',()=>{"
                "const banner=document.createElement('aside');"
                "banner.textContent='ИЗОЛИРОВАННЫЙ ТЕСТ: synthetic qualification; '"
                "+'не реальное подтверждение; банк not_admitted';"
                "document.body.prepend(banner);});"
            )
        await ui_login(candidate, origin, candidate_email, candidate_password)
        await ui_login(employer_page, origin, employer_email)
        await employer_page.locator('[name="company_name"]').fill(
            "Тестовая компания React"
        )
        await employer_page.locator('[name="representative_contact"]').fill(
            "hr@example.com"
        )
        await employer_page.get_by_role("button", name="Сохранить компанию").click()
        await expect(employer_page.locator("#feedback")).to_have_text(
            "Компания сохранена."
        )
        await employer_page.get_by_role(
            "link", name="Потребности и подбор", exact=True
        ).click()
        await expect(employer_page.get_by_role("button", name="Шаблон:")).to_have_count(
            3
        )
        await employer_page.locator('[name="title"]').fill("Тестовая потребность React")
        await employer_page.locator('[name="task_description"]').fill("Python и SQL")
        await employer_page.locator('[name="salary_from"]').fill("170000")
        await employer_page.locator('[name="salary_to"]').fill("190000")
        await employer_page.locator('[name="additional_wishes"]').fill(
            "Удалённая работа"
        )
        await employer_page.get_by_role(
            "button", name="Сохранить потребность", exact=True
        ).click()
        await employer_page.wait_for_url("**/#needs/*")
        await employer_page.get_by_role(
            "button", name="Создать подборку", exact=True
        ).click()
        await employer_page.wait_for_url("**/#recommendations/*")
        await employer_page.locator(f'[name="compare_{candidate_id}"]').check()
        await employer_page.locator(f'[name="compare_{comparison_id}"]').check()
        await employer_page.get_by_role(
            "button", name="Сравнить две выбранные карточки"
        ).click()
        await expect(employer_page.get_by_role("table")).to_be_visible()
        card = employer_page.locator(
            f'section.panel:has(input[name="compare_{candidate_id}"])'
        )
        await expect(employer_page.locator("main")).not_to_contain_text(
            "react-private@example.com"
        )
        async with employer_page.expect_download() as event:
            await card.get_by_role("button", name="PDF", exact=True).click()
        pdf = await event.value
        path = await pdf.path()
        assert path
        text = "\n".join(p.extract_text() for p in PdfReader(path).pages)
        assert "Тестовая Анна" not in text and "react-private@example.com" not in text
        await card.get_by_role("link", name="Пригласить", exact=True).click()
        await employer_page.get_by_role(
            "button", name="Отправить приглашение", exact=True
        ).click()
        await employer_page.wait_for_url("**/#invitations/*")
        invitation_id = employer_page.url.rsplit("/", 1)[-1]
        await candidate.goto(origin + "/#invitations/" + invitation_id)
        await candidate.locator('[name="share_email"]').check()
        await candidate.locator('[name="contact_consent"]').check()
        await candidate.get_by_role(
            "button", name="Принять приглашение", exact=True
        ).click()
        await expect(
            candidate.get_by_role("button", name="Закрыть контакты этой компании")
        ).to_be_visible()
        await employer_page.reload()
        await expect(employer_page.locator("main")).to_contain_text(
            "react-private@example.com"
        )
        await expect(employer_page.locator("main")).not_to_contain_text("+79991112233")
        await candidate.get_by_role(
            "button", name="Закрыть контакты этой компании"
        ).click()
        await expect(
            candidate.get_by_role("button", name="Закрыть контакты этой компании")
        ).to_have_count(0)
        await employer_page.reload()
        await expect(employer_page.locator("main")).to_contain_text(
            "Контакты недоступны"
        )
        await expect(employer_page.locator("main")).not_to_contain_text(
            "react-private@example.com"
        )
        await employer_page.get_by_role("link", name="Мои вакансии", exact=True).click()
        await employer_page.get_by_role(
            "link", name="Создать вакансию", exact=True
        ).click()
        for name, content in {
            "title": "React тестовая вакансия",
            "description": "Разработка API",
            "salary_from": "170000",
            "salary_to": "190000",
            "conditions": "Гибкий график",
            "representative_contact": "hr@example.com",
        }.items():
            await employer_page.locator(f'[name="{name}"]').fill(content)
        await employer_page.get_by_role("button", name="Опубликовать вакансию").click()
        await employer_page.wait_for_url("**/#vacancy/*")
        vacancy_id = employer_page.url.rsplit("/", 1)[-1]
        await candidate.goto(origin + "/#vacancy/" + vacancy_id)
        await candidate.locator('[name="share_email"]').check()
        await candidate.locator('[name="application_consent"]').check()
        await candidate.get_by_role("button", name="Подать отклик", exact=True).click()
        await candidate.wait_for_url("**/#application/*")
        application_id = candidate.url.rsplit("/", 1)[-1]
        await employer_page.goto(origin + "/#application/" + application_id)
        await expect(employer_page.locator("main")).to_contain_text(
            "react-private@example.com"
        )
        await employer_page.get_by_role("button", name="Принять отклик").click()
        await expect(employer_page.get_by_role("heading", level=1)).to_have_text(
            "Отклик: Принят"
        )
        async with employer_page.expect_download() as event:
            await employer_page.get_by_role("button", name="PDF кандидата").click()
        pdf_path = await (await event.value).path()
        assert pdf_path
        extracted = "\n".join(p.extract_text() for p in PdfReader(pdf_path).pages)
        assert "react-private@example.com" in extracted
        assert "+79991112233" not in extracted and "Тестовая Анна" not in extracted
        assert any("а" <= char <= "я" for char in extracted)
        await candidate.reload()
        await candidate.get_by_role("button", name="Отозвать отклик").click()
        await expect(candidate.get_by_role("heading", level=1)).to_have_text(
            "Отклик: Отозван"
        )
        await employer_page.reload()
        await expect(employer_page.locator("main")).to_contain_text(
            "Контакты недоступны"
        )
        await expect(employer_page.locator("main")).not_to_contain_text(
            "react-private@example.com"
        )
        await candidate.goto(origin + "/#profile")
        await expect(candidate.locator('[name="show_name"]')).not_to_be_checked()
        ids = await candidate.locator("[id]").evaluate_all(
            "nodes => nodes.map(n=>n.id)"
        )
        assert len(ids) == len(set(ids)), "Labels require unique IDs"
        for page in (candidate, employer_page):
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.keyboard.press("Tab")
            assert await page.evaluate("document.activeElement.tagName !== 'BODY'")
            await page.screenshot(
                path=str(
                    tmp_path
                    / (
                        "candidate-mobile.png"
                        if page == candidate
                        else "employer-mobile.png"
                    )
                ),
                full_page=True,
            )
        assert not errors, errors
    finally:
        await cc.close()
        await ec.close()
        await asyncio.to_thread(stop, process)
