import asyncio
import os
import re
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from playwright.async_api import Browser, Page, async_playwright, expect
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


async def wait_api(origin: str, process: subprocess.Popen[bytes]) -> None:
    async with httpx.AsyncClient() as client:
        last_status: int | None = None
        for _ in range(300):
            if process.poll() is not None:
                pytest.fail(f"Browser API exited during startup: {process.returncode}")
            try:
                last_status = (
                    await client.get(origin + "/health/ready", timeout=1)
                ).status_code
                if last_status == 200:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.1)
    pytest.fail(
        f"Browser API readiness timed out; status={last_status}, "
        f"process={process.poll()}"
    )


async def mail_link(email: str, action: str) -> str:
    async with httpx.AsyncClient(base_url="http://mailpit:8025") as client:
        for _ in range(150):
            listing = (await client.get("/api/v1/messages")).json()
            for item in listing["messages"]:
                if not any(recipient["Address"] == email for recipient in item["To"]):
                    continue
                body = (await client.get(f"/api/v1/message/{item['ID']}")).json()[
                    "Text"
                ]
                match = re.search(rf"http://127\.0\.0\.1:\d+/#({action})/[^\s]+", body)
                if match:
                    return match.group(0)
            await asyncio.sleep(0.1)
    pytest.fail("Actual SMTP message was not delivered")


def launch_api(
    environment: dict[str, str], port: int, output: Path
) -> subprocess.Popen[bytes]:
    with output.open("ab") as stream:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            env=environment,
            stdout=stream,
            stderr=stream,
        )


def stop(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture
async def browser() -> AsyncIterator[Browser]:
    async with async_playwright() as playwright:
        instance = await playwright.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        try:
            yield instance
        finally:
            await instance.close()


async def sign_up(page: Page, origin: str, email: str, role: str) -> None:
    await page.goto(origin + "/#register")
    await page.locator('[name="email"]').fill(email)
    await page.locator('[name="password"]').fill("browser-password-12345")
    await page.locator('[name="role"]').select_option(role)
    await page.get_by_role("button", name="Зарегистрироваться").click()
    await expect(
        page.get_by_role(
            "heading",
            name="Кабинет кандидата" if role == "candidate" else "Кабинет работодателя",
        )
    ).to_be_visible()
    await page.goto(await mail_link(email, "verify"))
    await page.get_by_role("button", name="Подтвердить email", exact=True).click()
    await expect(page.locator("#feedback")).to_have_text("Email подтверждён.")


async def test_browser_registration_profile_mail_pdf_restart(
    browser: Browser, sessions: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    async with sessions.begin() as db:
        await db.execute(text("TRUNCATE users, auth_rate_buckets CASCADE"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        "APP_DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "APP_PUBLIC_ORIGIN": origin,
        "APP_ALLOWED_ORIGINS": "[]",
        "APP_JWT_SECRET": "browser-test-signing-key-12345678901234567890",
        "APP_WORKER_POLL_SECONDS": "0.1",
    }
    api = await asyncio.to_thread(launch_api, environment, port, tmp_path / "api.log")

    def launch_worker() -> subprocess.Popen[bytes]:
        with (tmp_path / "worker.log").open("wb") as stream:
            return subprocess.Popen(
                [sys.executable, "-m", "app.worker"],
                env=environment,
                stdout=stream,
                stderr=stream,
            )

    worker = await asyncio.to_thread(launch_worker)
    candidate_context = await browser.new_context(accept_downloads=True)
    employer_context = await browser.new_context()
    try:
        await wait_api(origin, api)
        candidate = await candidate_context.new_page()
        employer = await employer_context.new_page()
        candidate_email = f"browser-candidate-{uuid4().hex}@example.com"
        employer_email = f"browser-employer-{uuid4().hex}@example.com"
        await sign_up(employer, origin, employer_email, "employer")
        await employer.locator('[name="company_name"]').fill("Проверочная компания")
        await employer.locator('[name="representative_contact"]').fill(
            "Закрытый представитель"
        )
        await employer.get_by_role("button", name="Сохранить компанию").click()
        await expect(employer.locator("#feedback")).to_have_text("Компания сохранена.")
        await sign_up(candidate, origin, candidate_email, "candidate")
        await candidate.locator('[name="display_name"]').fill("Анна Проверочная")
        await candidate.locator('[name="summary"]').fill("Разработка API на Python")
        await candidate.locator('[name="experience"]').fill("Ручной ввод опыта")
        await candidate.locator('[name="salary_min"]').fill("100000")
        await candidate.locator('[name="salary_max"]').fill("150000")
        await candidate.locator('[name="location"]').fill("Москва")
        await candidate.locator('[name="format_remote"]').check()
        await candidate.locator('[name="confirm_preferences"]').check()
        await candidate.locator('[name="consent"]').check()
        await candidate.get_by_role(
            "button", name="Сохранить профиль", exact=True
        ).click()
        await expect(candidate.locator("#feedback")).to_have_text("Профиль сохранён.")
        await candidate.locator('[name="phone"]').fill("+79990001122")
        await candidate.locator('[name="telegram"]').fill("anna-private")
        await candidate.get_by_role("button", name="Сохранить контакты").click()
        await expect(candidate.locator("#feedback")).to_have_text("Контакты сохранены.")
        await candidate.locator('[name="visible_to_employers"]').check()
        await candidate.get_by_role("button", name="Сохранить приватность").click()
        await expect(candidate.locator("#feedback")).to_have_text(
            "Приватность сохранена."
        )
        await candidate.get_by_role("button", name="Заблокировать", exact=True).click()
        await expect(
            candidate.get_by_role("button", name="Разблокировать", exact=True)
        ).to_be_visible()
        async with candidate.expect_download() as captured:
            await candidate.get_by_role("button", name="Скачать мой PDF").click()
        download = await captured.value
        output = tmp_path / "profile.pdf"
        await download.save_as(output)
        pdf_text = "".join(
            page.extract_text()
            for page in PdfReader(BytesIO(output.read_bytes())).pages
        )
        assert (
            "Анна Проверочная" in pdf_text
            and "+79990001122" in pdf_text
            and "Москва" in pdf_text
        )
        # Новый процесс API: профиль и серверная сессия восстанавливаются из PostgreSQL.
        await asyncio.to_thread(stop, api)
        api = await asyncio.to_thread(
            launch_api, environment, port, tmp_path / "api.log"
        )
        await wait_api(origin, api)
        await candidate.reload()
        await expect(candidate.locator('[name="display_name"]')).to_have_value(
            "Анна Проверочная"
        )
        await expect(candidate.locator('[name="phone"]')).to_have_value("+79990001122")
        await expect(candidate.locator('[name="visible_to_employers"]')).to_be_checked()
        await expect(
            candidate.get_by_role("button", name="Разблокировать", exact=True)
        ).to_be_visible()
        await employer.reload()
        await expect(employer.locator('[name="company_name"]')).to_have_value(
            "Проверочная компания"
        )
        await candidate.get_by_role("button", name="Выйти", exact=True).click()
        await expect(
            candidate.get_by_role("heading", name="Вход", exact=True)
        ).to_be_visible()
        await candidate.goto(origin + "/#reset-request")
        await candidate.locator('[name="reset_email"]').fill(candidate_email)
        await candidate.get_by_role("button", name="Отправить ссылку").click()
        await expect(candidate.locator("#feedback")).to_have_text(
            "Если адрес зарегистрирован, письмо будет отправлено."
        )
        await candidate.goto(await mail_link(candidate_email, "reset"))
        await candidate.locator('[name="new_password"]').fill(
            "browser-new-password-12345"
        )
        await candidate.get_by_role("button", name="Изменить пароль").click()
        await expect(
            candidate.get_by_role("heading", name="Вход", exact=True)
        ).to_be_visible()
        await candidate.locator('[name="email"]').fill(candidate_email)
        await candidate.locator('[name="password"]').fill("browser-new-password-12345")
        await candidate.get_by_role("button", name="Войти", exact=True).click()
        await expect(candidate.locator('[name="display_name"]')).to_have_value(
            "Анна Проверочная"
        )
    finally:
        await candidate_context.close()
        await employer_context.close()
        await asyncio.to_thread(stop, api)
        await asyncio.to_thread(stop, worker)
