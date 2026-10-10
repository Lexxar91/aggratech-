"""Собирает публичные PDF из Markdown, не читая закрытые материалы банка."""

import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent
FONT = "ReleaseDejaVu"


def markup(text: str) -> str:
    """Оставляет читаемые пути ссылок, экранируя текст перед PDF-разметкой."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    return escape(text.replace("**", "").replace("`", ""))


def footer(canvas: Canvas, document: SimpleDocTemplate) -> None:
    """Отделяет техническую поставку v3 от статистической калибровки на людях."""
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawString(
        36, 20, "Aggratech v3 · 11.10.2026 · точность на людях не измерена"
    )
    canvas.drawRightString(document.pagesize[0] - 36, 20, str(document.page))
    canvas.restoreState()


def paragraphs(source: str, *, slides: bool = False) -> list[Flowable]:
    """Преобразует заголовки, списки, код и таблицы без выполнения Markdown-кода."""
    size = 16 if slides else 9
    body = ParagraphStyle(
        "body", fontName=FONT, fontSize=size, leading=size * 1.45, spaceAfter=6
    )
    heading = ParagraphStyle(
        "heading",
        parent=body,
        fontSize=24 if slides else 15,
        leading=32 if slides else 21,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=12,
        spaceAfter=12,
    )
    code = ParagraphStyle("code", parent=body, fontSize=8, leading=12)
    cells = ParagraphStyle("cells", parent=body, fontSize=7, leading=10)
    story: list[Flowable] = []
    table_rows: list[list[str]] = []
    in_code = False

    def flush_table() -> None:
        if not table_rows:
            return
        width = A4[0] - 72
        columns = len(table_rows[0])
        table = Table(
            [[Paragraph(markup(cell), cells) for cell in row] for row in table_rows],
            colWidths=[width / columns] * columns,
            repeatRows=1,
        )
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.extend([table, Spacer(1, 10)])
        table_rows.clear()

    for line in source.splitlines():
        if line.startswith("|"):
            row = [part.strip() for part in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]+", cell) for cell in row):
                table_rows.append(row)
            continue
        flush_table()
        if line.startswith("```"):
            in_code = not in_code
        elif line.strip() == "---":
            story.append(PageBreak())
        elif line.startswith("#"):
            story.append(Paragraph(markup(line.lstrip("# ")), heading))
        elif line.strip():
            text = "• " + line[2:] if line.startswith("- ") else line
            story.append(Paragraph(markup(text), code if in_code else body))
    flush_table()
    return story


def main() -> None:
    """Экспортирует документацию и восемь слайдов с встроенной кириллицей."""
    pdfmetrics.registerFont(
        TTFont(FONT, str(ROOT.parents[1] / "app/assets/DejaVuSans.ttf"))
    )
    output = ROOT / "export"
    output.mkdir(exist_ok=True)
    story: list[Flowable] = []
    for filename in (
        "README.md",
        "requirements_matrix.md",
        "validation_report.md",
        "human_checks.md",
        "demo_script.md",
        "../09_bank_v3_integration.md",
    ):
        if story:
            story.append(PageBreak())
        story.extend(paragraphs((ROOT / filename).read_text()))
    SimpleDocTemplate(
        str(output / "documentation.pdf"),
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
        title="Aggratech: документация RC",
        author="Aggratech",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    SimpleDocTemplate(
        str(output / "presentation.pdf"),
        pagesize=landscape(A4),
        leftMargin=40,
        rightMargin=40,
        topMargin=32,
        bottomMargin=36,
        title="Aggratech: презентация RC",
        author="Aggratech",
    ).build(
        paragraphs((ROOT / "slides.md").read_text(), slides=True),
        onFirstPage=footer,
        onLaterPages=footer,
    )


if __name__ == "__main__":
    main()
