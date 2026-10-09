import asyncio
import json
import os
import socket
import subprocess
import sys
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from playwright.async_api import Browser, expect
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.assessment import service
from app.assessment.models import AssessmentCycle
from tests.test_stage2_browser import (
    browser as _browser,
)
from tests.test_stage2_browser import (
    launch_api,
    sign_up,
    stop,
    wait_api,
)
from tests.test_stage4_grading import prepared_answer

browser = _browser

pytestmark = [pytest.mark.integration, pytest.mark.runner]


async def test_browser_live_demo_a_b_restart_publish_pdf(
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
        "APP_JWT_SECRET": "stage4-browser-demo-signing-key-123456789012345",
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
    context = await browser.new_context(accept_downloads=True)
    try:
        await wait_api(origin, api)
        page = await context.new_page()
        await sign_up(page, origin, f"stage4-{uuid4().hex}@example.com", "candidate")
        await page.get_by_role("link", name="Проверка навыков и история").click()
        await page.locator('[name="instructions_accepted"]').check()
        await page.get_by_role("button", name="Начать демо-цикл", exact=True).click()
        await expect(page.locator('form[id^="task-"]')).to_have_count(4)
        cid = UUID(page.url.rsplit("/", 1)[-1])
        async with sessions() as db:
            cycle = await db.get(AssessmentCycle, cid)
            assert cycle
            tasks = [
                (r.family, r.parameter_index, service.material(cycle, r.family))
                for r in await service.answers(db, cid)
            ]
            assert cycle.admission["origin"] == "live_demo"
        restarted = False
        for phase, families in [("A", "1234"), ("B", "56")]:
            for family, index, version in tasks:
                if family[-1] not in families:
                    continue
                for step in ("base", "transfer"):
                    answer = prepared_answer(version, step, index)
                    form = page.locator(f"#task-{family}")
                    await expect(form.get_by_role("heading")).to_have_text(
                        f"{family} · {step}"
                    )
                    if version.solutions:
                        await form.locator('[name="source"]').fill(answer.source)
                        await form.locator('[name="diagnosis"]').fill(answer.diagnosis)
                        await form.locator('[name="verification"]').fill(
                            ", ".join(answer.verification)
                        )
                    if await form.locator('[name="structured"]').count():
                        await form.locator('[name="structured"]').fill(
                            json.dumps(answer.structured)
                        )
                    if await form.locator('[name="tests"]').count():
                        await form.locator('[name="tests"]').fill(
                            json.dumps(answer.tests)
                        )
                    if not restarted:
                        await form.get_by_role(
                            "button", name="Сохранить черновик"
                        ).click()
                        await expect(page.locator("#feedback")).to_have_text(
                            "Черновик сохранён."
                        )
                        await asyncio.to_thread(stop, api)
                        api = await asyncio.to_thread(
                            launch_api, environment, port, tmp_path / "api.log"
                        )
                        await wait_api(origin, api)
                        await page.reload()
                        await expect(form.locator('[name="source"]')).to_have_value(
                            answer.source
                        )
                        restarted = True
                    await form.get_by_role(
                        "button",
                        name="Зафиксировать базу и открыть перенос"
                        if step == "base"
                        else "Зафиксировать перенос",
                        exact=True,
                    ).click()
                    await expect(form.get_by_role("heading")).to_have_text(
                        f"{family} · {'transfer' if step == 'base' else 'done'}"
                    )
            await page.get_by_role(
                "button", name=f"Сдать {phase} с сохранёнными черновиками", exact=True
            ).click()
            if phase == "A":
                await page.get_by_role(
                    "button", name="Начать B (15 минут)", exact=True
                ).click()
                await expect(page.locator('form[id^="task-"]')).to_have_count(2)
        for _ in range(180):
            if await page.get_by_role(
                "button", name="Опубликовать демо-результат в своём профиле"
            ).count():
                break
            assert worker.poll() is None, (tmp_path / "worker.log").read_text()[-8000:]
            await page.get_by_role(
                "button", name="Обновить состояние", exact=True
            ).click()
            await asyncio.sleep(1)
        await expect(
            page.get_by_role(
                "button", name="Опубликовать демо-результат в своём профиле"
            )
        ).to_be_visible()
        async with sessions() as db:
            cycle = await db.get(AssessmentCycle, cid)
            assert cycle
            assert cycle.state == "completed" and cycle.outcome == "confirmed"
            assert await service.published_result(db, cycle.user_id, owner=True) is None
            assert (
                await service.published_result(db, cycle.user_id, owner=False) is None
            )
        await page.get_by_role(
            "button", name="Опубликовать демо-результат в своём профиле"
        ).click()
        await expect(page.locator("#feedback")).to_have_text(
            "Выбор результата сохранён."
        )
        await page.screenshot(path=str(tmp_path / "completed.png"), full_page=True)
        await page.get_by_role("link", name="К профилю", exact=True).click()
        async with page.expect_download() as captured:
            await page.get_by_role("button", name="Скачать мой PDF").click()
        download = await captured.value
        output = tmp_path / "demo-profile.pdf"
        await download.save_as(output)
        extracted = "".join(
            p.extract_text() for p in PdfReader(BytesIO(output.read_bytes())).pages
        )
        extracted = " ".join(extracted.split())
        assert (
            "Демонстрационный результат" in extracted
            and "не верифицированная" in extracted
        )
        async with sessions() as db:
            cycle = await db.get(AssessmentCycle, cid)
            assert cycle
            result = await service.published_result(db, cycle.user_id, owner=True)
            assert result and not result.verified
            assert (
                await service.published_result(db, cycle.user_id, owner=False) is None
            )
            counts = [r.grading_status for r in await service.answers(db, cid)]
            assert counts == ["completed"] * 6
            (tmp_path / "demo-result.json").write_text(
                json.dumps(
                    {
                        "cycle_id": str(cid),
                        "form": cycle.form,
                        "origin": cycle.admission["origin"],
                        "runner_grades": counts,
                        "api_restarted": restarted,
                        "result": result.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        await page.get_by_role("link", name="Проверка навыков и история").click()
        await expect(
            page.get_by_role("link", name="junior · demo · completed", exact=False)
        ).to_be_visible()
    finally:
        await context.close()
        await asyncio.to_thread(stop, worker)
        await asyncio.to_thread(stop, api)
