import asyncio
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.candidate_profile.access import SharedContacts
from app.candidate_profile.schemas import ContactsView, SafeCard
from app.core.errors import ApiError

FONT = "DejaVuSans"
SKILL_NAMES = {
    "language_algorithms": "Python и алгоритмы",
    "sql_data": "SQL и данные",
    "http_api": "HTTP и API",
    "debug_reliability": "Отладка и надёжность",
    "security_validation": "Безопасность и валидация",
}
pdfmetrics.registerFont(
    TTFont(FONT, str(Path(__file__).parents[1] / "assets" / "DejaVuSans.ttf"))
)


def generate_pdf(
    card: SafeCard, contacts: ContactsView | SharedContacts | None = None
) -> bytes:
    """Создаёт PDF только из уже разрешённых DTO с встроенной кириллицей."""
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, title="Профиль кандидата", author="Aggratech")
    style = ParagraphStyle(
        "profile", fontName=FONT, fontSize=11, leading=16, spaceAfter=8
    )
    lines = [
        "Профиль кандидата",
        card.display_name,
        "Описание",
        card.summary,
        "Опыт",
        card.experience,
        "Зарплата: "
        + (
            f"{card.salary_min}–{card.salary_max} ₽/месяц gross"
            if card.salary_min is not None
            else "не указана"
        ),
        "Доступен с: "
        + (str(card.available_from) if card.available_from else "не указано"),
        "Форматы работы: "
        + ", ".join(
            {"remote": "удалённо", "hybrid": "гибрид", "onsite": "в офисе"}.get(
                value, value
            )
            for value in card.work_preferences.formats
        ),
        "Город: " + (card.work_preferences.location or "не указан"),
        "Заявленные технологии: " + (", ".join(card.technology_names) or "не указаны"),
        (
            "Технологии заявлены самостоятельно."
            if card.assessment and card.assessment.verified
            else "Технологии заявлены самостоятельно; уровень пока не подтверждён."
        ),
    ]
    if card.assessment:
        assessment = card.assessment
        lines += [
            f"Уровень: {assessment.grade.title()}"
            if assessment.verified
            else "Уровень пока не подтверждён",
            "Проверенные навыки Backend",
            "Дата проверки: "
            + (
                assessment.assessed_at.strftime("%d.%m.%Y")
                if assessment.assessed_at
                else "проверка ещё не завершена"
            ),
        ]
        for item in assessment.skills:
            status = (
                "требования выполнены" if item.status == "met" else "нужна доработка"
            )
            if item.score is None:
                status = "недостаточно данных"
            lines.append(
                f"{SKILL_NAMES.get(item.skill, 'Навык')}: {status}; "
                f"результат: {item.score if item.score is not None else 'нет данных'}"
            )
    if contacts:
        lines += [
            "Контакты владельца",
            str(contacts.email) if contacts.email else "",
            contacts.phone or "",
            *[f"{key}: {value}" for key, value in (contacts.messengers or {}).items()],
        ]
    story = [
        Paragraph(escape(line).replace("\n", "<br/>"), style) for line in lines if line
    ]
    story.append(Spacer(1, 10))
    document.build(story)
    return buffer.getvalue()


async def render_pdf(
    card: SafeCard,
    contacts: ContactsView | SharedContacts | None = None,
    *,
    timeout_seconds: float = 10,
) -> bytes:
    """Ограничивает ожидание PDF; введённый текст уже ограничен схемой профиля."""
    try:
        async with asyncio.timeout(timeout_seconds):
            return await asyncio.to_thread(generate_pdf, card, contacts)
    except TimeoutError:
        raise ApiError(
            504, "pdf_generation_timeout", "PDF не готов. Повторите позже."
        ) from None
