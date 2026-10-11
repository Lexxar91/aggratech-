"""Зачётный UI-путь на отдельном Compose: реальные ответы и runner, не пилот людей."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

import pytest
from playwright.async_api import Browser, Page, Route, expect
from pypdf import PdfReader

from app.assessment.v3_models import V3Bank
from tests.test_stage2_browser import browser as browser
from tests.test_stage2_browser import mail_link

pytestmark = pytest.mark.runner


class ReviewProxy(BaseHTTPRequestHandler):
    """Проксирует loopback браузера только к API собственного Compose-проекта."""

    def forward(self) -> None:
        """Сохраняет Cookie/Origin, не разделяя соединения или сессии ролей."""
        omitted = {
            "host",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in omitted
        }
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        # Новое соединение переживает restart API; эталоны прокси не получает.
        connection = HTTPConnection("api", 8000, timeout=120)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in omitted | {"content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except BrokenPipeError, ConnectionResetError:
                # Chromium отменяет запросы предыдущей страницы при навигации.
                pass
        finally:
            connection.close()

    do_GET = forward
    do_POST = forward
    do_PUT = forward
    do_PATCH = forward
    do_DELETE = forward

    def log_message(self, format: str, *args: object) -> None:
        """Не пишет HTTP-заголовки и данные технических аккаунтов в лог."""


@pytest.fixture
async def review_origin() -> AsyncIterator[str]:
    """Даёт Chromium localhost для Secure-cookie без ослабления auth."""
    origin = os.environ.get("V3_REVIEW_ORIGIN")
    if not origin:
        pytest.skip("requires dedicated admitted v3 Compose project")
    assert origin == "http://localhost:8000"
    proxy = ThreadingHTTPServer(("127.0.0.1", 8000), ReviewProxy)
    thread = Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    try:
        yield origin
    finally:
        await asyncio.to_thread(proxy.shutdown)
        proxy.server_close()
        await asyncio.to_thread(thread.join, 5)


async def register_ui(page: Page, origin: str, email: str, role: str) -> None:
    await page.goto(origin + "/#register")
    await page.locator('[name="email"]').fill(email)
    await page.locator('[name="password"]').fill("v3-browser-password-12345")
    await page.locator('[name="role"]').select_option(role)
    await page.get_by_role("button", name="Зарегистрироваться").click()
    await expect(
        page.get_by_role(
            "heading",
            name=f"Кабинет {'кандидата' if role == 'candidate' else 'работодателя'}",
            exact=True,
        )
    ).to_be_visible()
    link = await mail_link(email, "verify")
    await page.goto(origin + "/" + link.split("/", 3)[3])
    await page.get_by_role("button", name="Подтвердить email").click()
    await expect(page.locator("#feedback")).to_contain_text("Email подтверждён")


async def prepare_profile(page: Page, origin: str, label: str) -> str:
    await page.goto(origin + "/#profile")
    await page.locator('[name="display_name"]').fill(label)
    await page.locator('[name="summary"]').fill(
        "Техническая приёмка v3: Python и SQL, не статистика людей"
    )
    await page.locator('[name="salary_min"]').fill("160000")
    await page.locator('[name="salary_max"]').fill("200000")
    await page.locator('[name="available_from"]').fill(
        datetime.now(UTC).date().isoformat()
    )
    await page.locator('[name="format_remote"]').check()
    await page.locator('[name="confirm_preferences"]').check()
    await page.locator('[name="consent"]').check()
    async with page.expect_response(
        lambda response: (
            response.url == origin + "/api/v1/candidate/profile"
            and response.request.method == "PATCH"
            and response.status == 200
        )
    ) as saved:
        await page.get_by_role("button", name="Сохранить профиль", exact=True).click()
    candidate_id = str((await (await saved.value).json())["id"])
    await expect(page.locator("#feedback")).to_contain_text("Профиль сохранён")
    await page.locator('[name="contact_email"]').fill("v3-private@example.com")
    await page.locator('[name="phone"]').fill("+79995556677")
    await page.get_by_role("button", name="Сохранить контакты").click()
    await expect(page.locator("#feedback")).to_contain_text("Контакты сохранены")
    await page.locator('[name="visible_to_employers"]').check()
    await page.locator('[name="show_name"]').uncheck()
    await page.get_by_role("button", name="Сохранить приватность").click()
    await expect(page.locator("#feedback")).to_contain_text("Приватность сохранена")
    return candidate_id


async def pdf_text(
    page: Page, button_name: str, *, card_selector: str | None = None
) -> str:
    target = page.locator(card_selector) if card_selector else page
    async with page.expect_download() as event:
        await target.get_by_role("button", name=button_name, exact=True).click()
    download = await event.value
    path = await download.path()
    assert path and not await download.failure()
    reader = PdfReader(path)
    assert reader.pages
    return "\n".join(p.extract_text() for p in reader.pages)


async def finish_credit(
    page: Page,
    origin: str,
    bank: V3Bank,
    grade: str,
    form: str,
    *,
    restart: bool,
    fail_security: bool = False,
) -> str:
    await page.goto(origin + "/#assessment")
    await page.locator('[name="industry"]').fill("Техническая приёмка")
    await page.locator('[name="grade"]').select_option(grade)
    await expect(page.locator('[name="form"], [name="mode"]')).to_have_count(0)
    await page.locator('[name="instructions_accepted"]').check()
    async with page.expect_response(
        lambda response: (
            response.url.endswith("/assessment/cycles")
            and response.request.method == "POST"
        )
    ) as created:
        await page.get_by_role(
            "button", name="Начать проверку навыков", exact=True
        ).click()
    created_data = await (await created.value).json()
    assert created_data["mode"] == "credit"
    form = created_data["form"]
    await page.wait_for_url("**/#assessment/*")
    cycle_id = page.url.rsplit("/", 1)[-1]
    cards = [c for c in bank.cards if c.grade == grade and c.form == form]
    assert len(cards) == 7
    for phase in ("A", "B"):
        if phase == "B":
            await expect(
                page.get_by_role(
                    "button", name="Начать дополнительные задания (15 минут)"
                )
            ).to_be_visible(timeout=600000)
            await page.get_by_role(
                "button", name="Начать дополнительные задания (15 минут)"
            ).click()
        for index, card in enumerate(c for c in cards if c.session == phase):
            solution = next(s for s in card.solutions if s.kind == "reference")
            if fail_security and card.family_id == f"{form}2":
                solution = next(s for s in card.solutions if s.kind == "mistake")
            task = page.locator(f'[id="task-{card.task_id}"]')
            disclosure = task.locator("xpath=..")
            if await disclosure.get_attribute("open") is None:
                await disclosure.locator(".task-summary").click()
            await task.locator('[name="source"]').fill(solution.base)
            if restart and phase == "A" and index == 0:
                await task.locator('[name="source"]').fill(
                    "# retained draft\n" + solution.base
                )
                await task.get_by_role("button", name="Сохранить черновик").click()
                await expect(page.locator("#feedback")).to_contain_text(
                    "Черновик сохранён"
                )
                await page.reload()
                await expect(task.locator('[name="source"]')).to_have_value(
                    "# retained draft\n" + solution.base
                )
                marker = Path("/review-artifacts/restart-requested")
                await asyncio.to_thread(marker.write_text, cycle_id)
                for _ in range(180):
                    try:
                        receipt = await asyncio.to_thread(
                            Path("/review-artifacts/restart-complete").read_text
                        )
                    except FileNotFoundError:
                        receipt = ""
                    if receipt.splitlines()[:1] == [cycle_id]:
                        break
                    await asyncio.sleep(1)
                else:
                    pytest.fail("Compose API/worker restart was not performed")
                await page.reload()
                await expect(task.locator('[name="source"]')).to_have_value(
                    "# retained draft\n" + solution.base
                )
            await task.locator('[name="source"]').fill(solution.base)
            async with page.expect_response(
                lambda response: (
                    "/fix" in response.url and response.request.method == "POST"
                )
            ) as fixed:
                await task.get_by_role(
                    "button", name="Отправить решение и перейти ко второй части"
                ).click()
            fixed_response = await fixed.value
            submitted = fixed_response.request.post_data_json
            assert isinstance(submitted, dict)
            assert submitted["answer"]["source"] == solution.base
            assert fixed_response.status == 200
            await expect(
                task.get_by_role(
                    "button",
                    name="Отправить решение второй части",
                    exact=True,
                    include_hidden=True,
                )
            ).to_be_attached()
            if await disclosure.get_attribute("open") is None:
                await disclosure.locator(".task-summary").click()
            await expect(
                task.get_by_role(
                    "button", name="Отправить решение второй части", exact=True
                )
            ).to_be_visible()
            await task.locator('[name="source"]').fill(solution.transfer)
            await task.get_by_role(
                "button", name="Отправить решение второй части", exact=True
            ).click()
            await expect(task).to_contain_text("Ответ зафиксирован")
        await page.get_by_role(
            "button",
            name="Завершить основные задания" if phase == "A" else "Завершить проверку",
            exact=True,
        ).click()
    if fail_security:
        await expect(page.locator("main")).to_contain_text(
            f"Уровень {grade.title()} пока не подтверждён", timeout=600000
        )
        await expect(page.locator("main")).to_contain_text("не выполнено")
        await expect(page.locator("main")).to_contain_text("Следующий шаг")
        await expect(page.locator("main")).not_to_contain_text(
            "Демонстрационный / неподтверждённый результат"
        )
        await expect(
            page.get_by_role("button", name="Опубликовать результат", exact=True)
        ).to_have_count(0)
        return cycle_id
    await expect(
        page.get_by_role("button", name="Опубликовать результат", exact=True)
    ).to_be_visible(timeout=600000)
    # Читаем ответ действия React до навигации, а не старый GET из polling.
    async with page.expect_response(
        lambda response: (
            response.url == origin + f"/api/v1/assessment/cycles/{cycle_id}/publish"
            and response.request.method == "POST"
            and response.status == 200
        )
    ) as completed:
        await page.get_by_role(
            "button", name="Опубликовать результат", exact=True
        ).click()
    response = await completed.value
    result = await response.json()
    assert result["verified"] is True and result["outcome"] == "confirmed"
    assert result["methodology"] == bank.methodology and result["total"] == 100
    assert result["requirements"] and all(
        r["passed"] is True for r in result["requirements"]
    )
    assert result["assessed_at"] and "Python" in result["scope"]
    assert "reference" not in json.dumps(result)
    await expect(page.locator("#feedback")).to_contain_text("Выбор результата сохранён")
    await expect(page.locator("main")).not_to_contain_text(bank.methodology)
    await expect(page.locator("main")).to_contain_text(f"Ваш уровень — {grade.title()}")
    await expect(page.locator("main")).to_contain_text("Дата:")
    await expect(
        page.get_by_text("Что выполнено и что нужно доработать", exact=True)
    ).to_be_visible()
    await page.goto(origin + "/#assessment")
    await expect(page.locator("main")).to_contain_text("Требования выполнены")
    await page.goto(origin + "/#profile")
    text = await pdf_text(page, "Скачать мой PDF")
    assert "Техническая приёмка" in text
    assert "v3-private@example.com" in text
    return cycle_id


async def test_v3_credit_ui_matching_consent_pdf_and_restart(
    browser: Browser, review_origin: str
) -> None:
    origin = review_origin
    # Полная проверка допуска на ограниченном API занимает больше стандартных 5 s.
    expect.set_options(timeout=30000)
    bank = V3Bank.model_validate_json(
        await asyncio.to_thread(Path("bank/private/v3.json").read_bytes)
    )
    contexts = [await browser.new_context(accept_downloads=True) for _ in range(3)]
    errors: list[str] = []
    artifact = Path("/review-artifacts")
    # Receipt создаёт хост; sticky-каталог не разрешает checks удалить чужой файл.
    # Старый receipt безопасен: finish_credit сопоставляет его с текущим cycle_id.
    for name in ("restart-requested", "result.json"):
        await asyncio.to_thread((artifact / name).unlink, missing_ok=True)
    try:
        pages = [await c.new_page() for c in contexts]
        junior, middle, employer = pages
        for page in pages:
            page.on("pageerror", lambda error: errors.append(str(error)))
        token = uuid4().hex[:12]
        await register_ui(junior, origin, f"v3-j-{token}@example.com", "candidate")
        candidate_id = await prepare_profile(junior, origin, "Тестовая Анна v3")
        junior_cycle = await finish_credit(
            junior, origin, bank, "junior", "X", restart=True
        )
        await register_ui(middle, origin, f"v3-m-{token}@example.com", "candidate")
        await prepare_profile(middle, origin, "Тестовый Михаил v3")
        middle_cycle = await finish_credit(
            middle, origin, bank, "middle", "Y", restart=False
        )
        await register_ui(employer, origin, f"v3-e-{token}@example.com", "employer")
        await employer.goto(origin + "/#profile")
        await employer.locator('[name="company_name"]').fill("Техническая компания v3")
        await employer.locator('[name="representative_contact"]').fill("hr@example.com")
        await employer.get_by_role("button", name="Сохранить компанию").click()
        await expect(employer.locator("#feedback")).to_contain_text(
            "Компания сохранена"
        )
        await employer.get_by_role(
            "link", name="Потребности и подбор", exact=True
        ).click()
        await employer.locator('[name="title"]').fill("Зачётный Python/SQL v3")
        await employer.locator('[name="task_description"]').fill("Python и SQL")
        await employer.locator('[name="grade_junior"]').check()
        await employer.locator('[name="grade_middle"]').check()
        await employer.locator('[name="skill_required_http_api"]').check()
        await employer.locator('[name="salary_from"]').fill("170000")
        await employer.locator('[name="salary_to"]').fill("190000")
        await employer.get_by_role(
            "button", name="Сохранить потребность", exact=True
        ).click()
        await employer.wait_for_url("**/#needs/*")
        await employer.get_by_role(
            "button", name="Создать подборку", exact=True
        ).click()
        await employer.wait_for_url("**/#recommendations/*")
        selector = f'section.panel:has(input[name="compare_{candidate_id}"])'
        ranking_url = employer.url
        await expect(employer.locator(selector)).to_be_visible()
        await expect(employer.locator("main")).not_to_contain_text(
            "v3-private@example.com"
        )
        before = await pdf_text(employer, "PDF", card_selector=selector)
        assert "Тестовая Анна" not in before and "v3-private@example.com" not in before
        await (
            employer.locator(selector)
            .get_by_role("link", name="Пригласить", exact=True)
            .click()
        )
        await expect(employer.locator('[name="salary_from"]')).to_have_value("170000")
        await expect(employer.locator('[name="salary_to"]')).to_have_value("190000")
        # Это обязательное поле предложения; у потребности wishes необязательны.
        await employer.locator('[name="conditions"]').fill(
            "Удалённая работа; техническая приёмка v3"
        )
        async with employer.expect_response(
            lambda response: (
                response.url == origin + "/api/v1/employer/invitations"
                and response.request.method == "POST"
            )
        ) as sent:
            await employer.get_by_role(
                "button", name="Отправить приглашение", exact=True
            ).click()
        assert (await sent.value).status == 200
        await employer.wait_for_url("**/#invitations/*")
        invitation_id = employer.url.rsplit("/", 1)[-1]
        await junior.goto(origin + "/#invitations/" + invitation_id)
        await expect(junior.locator("main")).to_contain_text("170")
        await junior.locator('[name="share_email"]').check()
        await junior.locator('[name="contact_consent"]').check()
        await junior.get_by_role(
            "button", name="Принять приглашение", exact=True
        ).click()
        await expect(
            junior.get_by_role("button", name="Закрыть контакты этой компании")
        ).to_be_visible()
        await employer.reload()
        await expect(employer.locator("main")).to_contain_text("v3-private@example.com")
        await expect(employer.locator("main")).not_to_contain_text("+79995556677")
        await employer.goto(ranking_url)
        permitted = await pdf_text(employer, "PDF", card_selector=selector)
        assert "v3-private@example.com" in permitted
        assert "+79995556677" not in permitted and "Тестовая Анна" not in permitted
        await employer.goto(origin + "/#invitations/" + invitation_id)
        await junior.get_by_role(
            "button", name="Закрыть контакты этой компании"
        ).click()
        await expect(
            junior.get_by_role("button", name="Закрыть контакты этой компании")
        ).to_have_count(0)
        await employer.reload()
        await expect(employer.locator("main")).not_to_contain_text(
            "v3-private@example.com"
        )
        await employer.goto(ranking_url)
        after = await pdf_text(employer, "PDF", card_selector=selector)
        assert "v3-private@example.com" not in after and "+79995556677" not in after
        assert "Тестовая Анна" not in after
        await employer.get_by_role("link", name="Мои вакансии", exact=True).click()
        await employer.get_by_role("link", name="Создать вакансию", exact=True).click()
        for name, content in {
            "title": "Разработчик API",
            "description": "Поддержка Python API",
            "salary_from": "170000",
            "salary_to": "190000",
            "conditions": "Полный день и удалённая работа",
            "representative_contact": "hr@example.com",
        }.items():
            await employer.locator(f'[name="{name}"]').fill(content)
        await employer.get_by_role("button", name="Опубликовать вакансию").click()
        await employer.wait_for_url("**/#vacancy/*")
        vacancy_id = employer.url.rsplit("/", 1)[-1]
        await junior.goto(origin + "/#vacancy/" + vacancy_id)
        await junior.locator('[name="share_email"]').check()
        await junior.locator('[name="application_consent"]').check()
        await junior.get_by_role("button", name="Подать отклик", exact=True).click()
        await junior.wait_for_url("**/#application/*")
        application_url = junior.url
        await employer.goto(application_url)
        await expect(employer.locator("main")).to_contain_text("v3-private@example.com")
        await employer.get_by_role("button", name="Принять отклик").click()
        await expect(employer.get_by_role("heading", level=1)).to_have_text(
            "Отклик: Принят"
        )
        application_pdf = await pdf_text(employer, "PDF кандидата")
        assert (
            "v3-private@example.com" in application_pdf
            and "+79995556677" not in application_pdf
        )
        assert (
            "семейств" not in application_pdf
            and bank.methodology not in application_pdf
        )
        await junior.reload()
        await junior.get_by_role("button", name="Отозвать отклик").click()
        await expect(junior.get_by_role("heading", level=1)).to_have_text(
            "Отклик: Отозван"
        )
        await employer.reload()
        await expect(employer.locator("main")).not_to_contain_text(
            "v3-private@example.com"
        )
        await employer.goto(ranking_url)
        withdrawn_pdf = await pdf_text(employer, "PDF", card_selector=selector)
        assert "v3-private@example.com" not in withdrawn_pdf
        assert "+79995556677" not in withdrawn_pdf
        for page in (junior, employer):
            await page.set_viewport_size({"width": 390, "height": 844})
            assert await page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            )
            await page.keyboard.press("Tab")
            assert await page.evaluate("document.activeElement.tagName !== 'BODY'")
            text = await page.locator("body").inner_text()
            assert all(
                term not in text
                for term in (
                    "Хакатонное демо",
                    "fixture",
                    "live_credit",
                    "семейств",
                    "not_admitted",
                    bank.methodology,
                )
            )
        await junior.goto(origin + "/#profile")
        await junior.locator('[name="visible_to_employers"]').uncheck()
        await junior.get_by_role("button", name="Сохранить приватность").click()
        await expect(junior.locator("#feedback")).to_contain_text(
            "Приватность сохранена"
        )
        await employer.reload()
        await expect(
            employer.locator(f'[name="compare_{candidate_id}"]')
        ).to_have_count(0)
        assert not errors
        (artifact / "result.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "origin": "automated_technical_acceptance",
                    "grades": ["junior", "middle"],
                    "cycles": [junior_cycle, middle_cycle],
                    "draft_restart": True,
                    "matching": "actual_credit_v3",
                    "consent_pdf_privacy": True,
                    "vacancy_application_withdrawal": True,
                    "current_editor_submission": True,
                    "mobile_keyboard": True,
                    "human_pilot": False,
                },
                indent=2,
            )
        )
    finally:
        for context in contexts:
            await context.close()


async def test_starter_cabinets_and_real_refusal(
    browser: Browser, review_origin: str
) -> None:
    """Проверяет заполненную БД через UI и реальный отказ без подмены оценок."""
    origin = review_origin
    expect.set_options(timeout=30000)
    context = await browser.new_context(accept_downloads=True)
    try:
        page = await context.new_page()
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
            ("employer", ("profile", "needs", "invitations", "vacancies")),
        ):
            await page.goto(origin + "/#login")
            await page.locator('[name="email"]').fill(f"{role}01@aggratech.example.com")
            await page.locator('[name="password"]').fill("StartProduct2026!")
            await page.get_by_role("button", name="Войти", exact=True).click()
            await expect(page.get_by_role("heading", level=1)).to_contain_text(
                "Кабинет"
            )
            for route in routes:
                await page.goto(origin + "/#" + route)
                await expect(page.locator("main h1")).to_be_visible()
                await expect(page.locator("main")).not_to_contain_text(
                    "Загружаем данные"
                )
                text = await page.locator("body").inner_text()
                assert all(
                    term not in text
                    for term in (
                        "Хакатонное демо",
                        "fixture",
                        "admission_status",
                        "not_admitted",
                        "семейств",
                        "ревизи",
                        "demo",
                        "credit",
                        "Методика:",
                        "production",
                        "assessment",
                    )
                ), (role, route)
                if role == "candidate" and route == "profile":
                    await expect(page.locator("main")).to_contain_text(
                        "Ваш уровень — Junior"
                    )
                    text = await pdf_text(page, "Скачать мой PDF")
                    assert "Анна Смирнова" in text and "Junior" in text
                if role == "employer" and route == "needs":
                    await expect(
                        page.locator("main a[href^='#needs/']")
                    ).not_to_have_count(0)
                    await page.locator("main a[href^='#needs/']").first.click()
                    await page.get_by_role(
                        "button", name="Создать подборку", exact=True
                    ).click()
                    await page.wait_for_url("**/#recommendations/*")
                    await expect(
                        page.locator('input[name^="compare_"]')
                    ).not_to_have_count(0)
                    await page.locator('input[name^="compare_"]').nth(0).check()
                    await page.locator('input[name^="compare_"]').nth(1).check()
                    await page.get_by_role(
                        "button", name="Сравнить две выбранные карточки", exact=True
                    ).click()
                    await expect(
                        page.get_by_role("heading", name="Сравнение", exact=True)
                    ).to_be_visible()
                    await expect(page.locator("main")).not_to_contain_text(
                        "+79990000001"
                    )
            await page.get_by_role("button", name="Выйти", exact=True).click()
            await expect(
                page.get_by_role("heading", name="Вход", exact=True)
            ).to_be_visible()
        await register_ui(
            page, origin, f"refusal-{uuid4().hex[:12]}@example.com", "candidate"
        )
        await prepare_profile(page, origin, "Проверка причин отказа")
        bank = V3Bank.model_validate_json(
            await asyncio.to_thread(Path("bank/private/v3.json").read_bytes)
        )
        cycle = await finish_credit(
            page, origin, bank, "junior", "X", restart=False, fail_security=True
        )
        (Path("/review-artifacts") / "starter-ui.json").write_text(
            json.dumps(
                {
                    "status": "passed",
                    "starter_cabinets": True,
                    "actual_refusal_cycle": cycle,
                    "human_pilot": False,
                }
            )
        )
    finally:
        await context.close()


async def test_ui_refreshes_after_technical_recovery(
    browser: Browser, review_origin: str
) -> None:
    """Моделирует только переход экрана; итог берёт из реального стартового цикла."""
    origin = review_origin
    context = await browser.new_context()
    try:
        page = await context.new_page()
        await page.goto(origin + "/#login")
        await page.locator('[name="email"]').fill("candidate01@aggratech.example.com")
        await page.locator('[name="password"]').fill("StartProduct2026!")
        await page.get_by_role("button", name="Войти", exact=True).click()
        await expect(page.get_by_role("heading", level=1)).to_contain_text("Кабинет")
        async with page.expect_response(
            lambda r: r.url == origin + "/api/v1/assessment/cycles"
        ) as history:
            await page.goto(origin + "/#assessment")
        cycle_id = (await (await history.value).json())[0]["id"]
        first = True

        async def transition(route: Route) -> None:
            nonlocal first
            response = await route.fetch()
            assert response.status == 200
            data = await response.json()
            if first:
                first = False
                data["state"] = "technical_error"
                data["technical_issue"] = True
                data["result"]["verified"] = False
                data["result"]["outcome"] = "insufficient"
            await route.fulfill(response=response, json=data)

        await page.route(origin + f"/api/v1/assessment/cycles/{cycle_id}", transition)
        await page.goto(origin + f"/#assessment/{cycle_id}")
        await expect(page.locator("main")).to_contain_text(
            "Проверка временно прервана из-за сбоя"
        )
        await expect(page.locator("main")).to_contain_text(
            "Ваш уровень — Junior", timeout=15000
        )
    finally:
        await context.close()
