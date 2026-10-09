import asyncio
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.candidate_profile.schemas import ContactsView, SafeCard
from app.core.errors import ApiError

FONT = "DejaVuSans"
pdfmetrics.registerFont(
    TTFont(FONT, str(Path(__file__).parents[1] / "assets" / "DejaVuSans.ttf"))
)


def generate_pdf(card: SafeCard, contacts: ContactsView | None = None) -> bytes:
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
        "Форматы работы: " + ", ".join(card.work_preferences.formats),
        "Город: " + (card.work_preferences.location or "не указан"),
        "Заявленные технологии: " + (", ".join(card.technology_names) or "не указаны"),
        (
            "Технологии заявлены самостоятельно."
            if card.assessment and card.assessment.verified
            else "Технологии заявлены самостоятельно; категория пока не подтверждена."
        ),
    ]
    if card.assessment:
        assessment = card.assessment
        lines += [
            assessment.label,
            f"Уровень: {assessment.grade}; версия: {assessment.methodology}",
            assessment.scope,
            f"Дата: {assessment.assessed_at}",
        ]
        lines += [
            f"{item.skill}: {item.status}; различных семейств: {item.families}; "
            f"результат: {item.score}"
            for item in assessment.skills
        ]
    if contacts:
        lines += [
            "Контакты владельца",
            str(contacts.email),
            contacts.phone,
            *[f"{key}: {value}" for key, value in contacts.messengers.items()],
        ]
    story = [
        Paragraph(escape(line).replace("\n", "<br/>"), style) for line in lines if line
    ]
    story.append(Spacer(1, 10))
    document.build(story)
    return buffer.getvalue()


async def render_pdf(
    card: SafeCard, contacts: ContactsView | None = None, *, timeout_seconds: float = 10
) -> bytes:
    """Ограничивает ожидание PDF; введённый текст уже ограничен схемой профиля."""
    try:
        async with asyncio.timeout(timeout_seconds):
            return await asyncio.to_thread(generate_pdf, card, contacts)
    except TimeoutError:
        raise ApiError(
            504, "pdf_generation_timeout", "PDF не готов. Повторите позже."
        ) from None
