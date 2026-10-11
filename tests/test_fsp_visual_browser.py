"""Visual acceptance on an existing populated stand; no human calibration."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.async_api import Browser, Page, expect

from tests.test_stage2_browser import browser as browser
from tests.test_v3_browser import register_ui
from tests.test_v3_browser import review_origin as review_origin

pytestmark = pytest.mark.runner

SIZES = ((1440, 1000, "desktop"), (768, 1024, "tablet"), (390, 844, "phone"))


async def capture(page: Page, name: str) -> None:
    if not any(part in name for part in ("comparison", "python-task", "sql-task")):
        await page.evaluate("window.scrollTo(0,0)")
    await expect(page.locator("main h1")).to_be_visible()
    await expect(page.locator("main")).not_to_contain_text("Загружаем данные")
    await page.evaluate(
        "Promise.all([document.fonts.load('14px \"JetBrains Mono\"'), "
        "document.fonts.load('24px \"TDA Text\"')])"
    )
    assert await page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    ), f"horizontal page overflow: {name}"
    assert await page.evaluate("document.fonts.check('14px \"JetBrains Mono\"')")
    assert await page.evaluate("document.fonts.check('24px \"TDA Text\"')")
    assert await page.locator(".brand-logo").evaluate(
        "image => image.complete && image.naturalWidth > 0"
    )
    await page.screenshot(path=f"/review-artifacts/screenshots/{name}.png")


async def login(page: Page, origin: str, role: str) -> None:
    await page.goto(origin + "/#login")
    await page.locator('[name="email"]').fill(f"{role}01@aggratech.example.com")
    await page.locator('[name="password"]').fill("StartProduct2026!")
    await page.get_by_role("button", name="Войти", exact=True).click()
    await expect(page.locator("main h1")).to_contain_text("Кабинет")


async def test_fsp_all_screens_responsive_and_draft(
    browser: Browser, review_origin: str
) -> None:
    """Real data, all pages, local fonts, keyboard and preserved code drafts."""
    origin = review_origin
    expect.set_options(timeout=30000)
    await asyncio.to_thread(
        Path("/review-artifacts/screenshots").mkdir, parents=True, exist_ok=True
    )
    errors: list[str] = []
    shots: list[str] = []
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        for width, height, size in SIZES:
            await page.set_viewport_size({"width": width, "height": height})
            for route in ("login", "register", "reset-request"):
                await page.goto(origin + "/#" + route)
                await capture(page, f"{size}-{route}")
                shots.append(f"{size}-{route}")
            for role, routes in (
                (
                    "candidate",
                    (
                        "profile",
                        "assessment",
                        "vacancies",
                        "applications",
                        "invitations",
                        "fsp",
                    ),
                ),
                (
                    "employer",
                    ("profile", "needs", "vacancies", "invitations", "vacancy-edit"),
                ),
            ):
                await login(page, origin, role)
                for route in routes:
                    await page.goto(origin + "/#" + route)
                    await capture(page, f"{size}-{role}-{route}")
                    shots.append(f"{size}-{role}-{route}")
                    if route == "assessment":
                        await page.locator("a[href^='#assessment/']").first.click()
                        await capture(page, f"{size}-result")
                    if route == "vacancies":
                        await page.locator("main a[href^='#vacancy/']").first.click()
                        await capture(page, f"{size}-{role}-vacancy")
                    if route == "applications" and role == "candidate":
                        await page.locator(
                            "main a[href^='#application/']"
                        ).first.click()
                        await capture(page, f"{size}-application")
                    if route == "invitations":
                        await page.locator(
                            "main a[href^='#invitations/']"
                        ).first.click()
                        await capture(page, f"{size}-{role}-invitation")
                    if route == "needs":
                        await page.locator("main a[href^='#needs/']").first.click()
                        await page.get_by_role(
                            "button", name="Создать подборку", exact=True
                        ).click()
                        await page.wait_for_url("**/#recommendations/*")
                        choices = page.locator('input[name^="compare_"]')
                        await expect(choices).not_to_have_count(0)
                        await capture(page, f"{size}-matching")
                        await choices.nth(0).check()
                        await choices.nth(1).check()
                        await page.get_by_role(
                            "button", name="Сравнить две выбранные карточки", exact=True
                        ).click()
                        comparison = page.get_by_role(
                            "heading", name="Сравнение", exact=True
                        )
                        await expect(comparison).to_be_visible()
                        await comparison.scroll_into_view_if_needed()
                        await capture(page, f"{size}-comparison")
                await page.get_by_role("button", name="Выйти", exact=True).click()
                await expect(
                    page.get_by_role("heading", name="Вход", exact=True)
                ).to_be_visible()
        await page.set_viewport_size({"width": 1440, "height": 1000})
        await page.goto(origin + "/#login")
        await page.locator(".brand").focus()
        await page.keyboard.press("Shift+Tab")
        await expect(page.locator(".skip-link")).to_be_focused()
        assert await page.locator(".skip-link").evaluate(
            "el => getComputedStyle(el).outlineStyle !== 'none'"
        )
        await page.keyboard.press("Enter")
        await expect(page.locator("main")).to_be_focused()
        await page.get_by_role("button", name="Войти", exact=True).click()
        assert await page.locator('[name="email"]').evaluate(
            "el => !el.checkValidity()"
        )
        await capture(page, "invalid-login")
        await page.locator('[name="email"]').fill("nonexistent-fsp@example.com")
        await page.locator('[name="password"]').fill("invalid-password-12345")
        await page.get_by_role("button", name="Войти", exact=True).click()
        await expect(page.locator("#feedback")).to_have_class("feedback error")
        await capture(page, "login-error")
        await register_ui(
            page, origin, f"fsp-visual-{uuid4().hex[:12]}@example.com", "candidate"
        )
        await page.goto(origin + "/#assessment")
        await page.locator('[name="instructions_accepted"]').check()
        await page.get_by_role(
            "button", name="Начать проверку навыков", exact=True
        ).click()
        await page.wait_for_url("**/#assessment/*")
        first = page.locator(".task-disclosure").first
        await expect(first.locator('[name="source"]')).to_be_visible()
        draft = "# Мой черновик: проверка сохранения текста\n"
        await first.locator('[name="source"]').fill(draft)
        await first.locator(".task-summary").click()
        await expect(first.locator('[name="source"]')).not_to_be_visible()
        await first.locator(".task-summary").focus()
        await page.keyboard.press("Enter")
        await expect(first.locator('[name="source"]')).to_have_value(draft)
        await first.get_by_role("button", name="Сохранить черновик").click()
        await expect(page.locator("#feedback")).to_contain_text("Черновик сохранён")
        await page.reload()
        await expect(first.locator('[name="source"]')).to_have_value(draft)
        tasks = page.locator(".task-disclosure")
        await expect(tasks).to_have_count(5)
        assert await page.locator(".task-disclosure[open]").count() == 1
        for width, height, size in SIZES:
            await page.set_viewport_size({"width": width, "height": height})
            await page.evaluate("window.scrollTo(0,0)")
            await capture(page, f"{size}-task-progress")
            await first.locator(".task-summary").scroll_into_view_if_needed()
            await capture(page, f"{size}-python-task")
            sql = (
                page.locator(".task-disclosure")
                .filter(has_text="SQL · Первая часть")
                .first
            )
            await sql.locator(".task-summary").click()
            await sql.locator(".task-summary").scroll_into_view_if_needed()
            await capture(page, f"{size}-sql-task")
            await sql.locator(".task-summary").click()
        assert not errors, errors
        await asyncio.to_thread(
            Path("/review-artifacts/visual-results.json").write_text,
            json.dumps(
                {
                    "status": "passed",
                    "viewports": SIZES,
                    "screens": shots,
                    "console_errors": errors,
                    "draft_restored": True,
                    "human_pilot": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    finally:
        await context.close()
