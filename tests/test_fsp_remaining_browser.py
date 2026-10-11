"""Focused visual coverage of employer actions and successful real assessment."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.async_api import Browser, expect

from app.assessment.v3_models import V3Bank
from tests.test_fsp_visual_browser import SIZES, capture, login
from tests.test_stage2_browser import browser as browser
from tests.test_v3_browser import finish_credit, prepare_profile, register_ui
from tests.test_v3_browser import review_origin as review_origin

pytestmark = pytest.mark.runner


async def test_fsp_employer_applications_offer_and_comparison(
    browser: Browser, review_origin: str
) -> None:
    origin = review_origin
    expect.set_options(timeout=30000)
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await login(page, origin, "employer")
        for width, height, size in SIZES:
            await page.set_viewport_size({"width": width, "height": height})
            await page.goto(origin + "/#vacancies")
            await page.locator("main a[href^='#vacancy/']").first.click()
            await page.locator("main a[href^='#applications/']").click()
            await capture(page, f"{size}-employer-applications")
            await page.locator("main a[href^='#application/']").first.click()
            await capture(page, f"{size}-employer-application")
            await page.goto(origin + "/#needs")
            await page.locator("main a[href^='#needs/']").first.click()
            await page.get_by_role(
                "button", name="Создать подборку", exact=True
            ).click()
            await page.wait_for_url("**/#recommendations/*")
            choices = page.locator('input[name^="compare_"]')
            await expect(choices).not_to_have_count(0)
            await choices.nth(0).check()
            await choices.nth(1).check()
            await page.get_by_role(
                "button", name="Сравнить две выбранные карточки", exact=True
            ).click()
            heading = page.get_by_role("heading", name="Сравнение", exact=True)
            await expect(heading).to_be_visible()
            label_width = await page.locator(
                ".comparison-table tbody th"
            ).first.evaluate("el => el.getBoundingClientRect().width")
            assert label_width > 80, "comparison labels must remain readable"
            await heading.evaluate("el => el.scrollIntoView({block: 'start'})")
            await capture(page, f"{size}-comparison-table")
            await page.locator("main a[href^='#offer/']").first.click()
            await capture(page, f"{size}-employer-offer")
    finally:
        await context.close()


async def test_fsp_successful_real_level_after_redesign(
    browser: Browser, review_origin: str
) -> None:
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await register_ui(
            page,
            review_origin,
            f"fsp-success-{uuid4().hex[:12]}@example.com",
            "candidate",
        )
        await prepare_profile(page, review_origin, "Техническая приёмка оформления")
        bank = V3Bank.model_validate_json(
            await asyncio.to_thread(Path("bank/private/v3.json").read_bytes)
        )
        await finish_credit(page, review_origin, bank, "junior", "", restart=False)
        await expect(page.locator("main")).to_contain_text("Ваш уровень — Junior")
        for width, height, size in SIZES:
            await page.set_viewport_size({"width": width, "height": height})
            await capture(page, f"{size}-successful-real-result")
    finally:
        await context.close()


async def test_fsp_candidate_profile_fields_and_privacy(
    browser: Browser, review_origin: str
) -> None:
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await login(page, review_origin, "candidate")
        for width, height, size in SIZES:
            await page.set_viewport_size({"width": width, "height": height})
            for label in ("Ручной профиль", "Закрытые контакты", "Приватность"):
                heading = page.get_by_role("heading", name=label, exact=True)
                await heading.evaluate("el => el.scrollIntoView({block: 'start'})")
                assert await page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
                await page.screenshot(
                    path=f"/review-artifacts/screenshots/{size}-profile-{label}.png"
                )
    finally:
        await context.close()
