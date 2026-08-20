"""Bounded in-memory PDF rendering for immutable assessment results."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from threading import Lock
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


MAX_PDF_ITEMS = 1_000
MAX_PDF_TEXT_CHARS = 1_000_000
MAX_PDF_BYTES = 12 * 1024 * 1024
_FONT_LOCK = Lock()
_FONTS_READY = False
PDF_FONT_REGULAR = "RestosPdfRegular"
PDF_FONT_BOLD = "RestosPdfBold"
RUSSIAN_MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
TASK_STATUS_LABELS = {
    "draft": "Черновик",
    "assigned": "Назначена",
    "in_progress": "В работе",
    "completed": "Завершена",
    "cancelled": "Отменена",
    "revoked": "Отозвана",
    "overdue": "Просрочена",
}


class AssessmentResultPdfInvalid(Exception):
    pass


class AssessmentResultPdfService:
    """Render the same typed projection used by the result screen."""

    def __init__(self, font_directory: Path | None = None):
        self._font_directory = font_directory or (
            Path("/usr/share/fonts/truetype/dejavu")
        )

    def generate(self, projection: dict[str, Any], generated_at: datetime) -> bytes:
        self._validate_projection(projection, generated_at)
        self._ensure_fonts()
        target = BytesIO()
        document = SimpleDocTemplate(
            target,
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title="RestOS - результат замера",
            author="RestOS",
            subject="Immutable assessment result",
        )
        styles = self._styles()
        story = self._story(projection, generated_at, styles)

        def footer(canvas, doc) -> None:
            canvas.saveState()
            canvas.setFont(PDF_FONT_REGULAR, 8)
            canvas.setFillColor(colors.HexColor("#526052"))
            canvas.drawString(16 * mm, 9 * mm, "RestOS")
            canvas.drawRightString(
                A4[0] - 16 * mm,
                9 * mm,
                f"Страница {doc.page} · {generated_at:%d.%m.%Y}",
            )
            canvas.restoreState()

        document.build(story, onFirstPage=footer, onLaterPages=footer)
        value = target.getvalue()
        if not value.startswith(b"%PDF-") or len(value) > MAX_PDF_BYTES:
            raise AssessmentResultPdfInvalid("generated PDF is invalid or too large")
        return value

    def _ensure_fonts(self) -> None:
        global _FONTS_READY
        if _FONTS_READY:
            return
        with _FONT_LOCK:
            if _FONTS_READY:
                return
            regular = self._font_directory / "DejaVuSans.ttf"
            bold = self._font_directory / "DejaVuSans-Bold.ttf"
            if not regular.is_file() or not bold.is_file():
                raise AssessmentResultPdfInvalid("packaged PDF fonts are unavailable")
            pdfmetrics.registerFont(TTFont(PDF_FONT_REGULAR, str(regular)))
            pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD, str(bold)))
            _FONTS_READY = True

    @staticmethod
    def _validate_projection(
        projection: dict[str, Any], generated_at: datetime
    ) -> None:
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise AssessmentResultPdfInvalid("generated_at must be timezone-aware")
        if projection.get("status") != "completed":
            raise AssessmentResultPdfInvalid("only completed results can be rendered")
        try:
            local_submitted_at = datetime.fromisoformat(
                str(projection["local_submitted_at"])
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AssessmentResultPdfInvalid(
                "local submitted timestamp is invalid"
            ) from error
        if local_submitted_at.tzinfo is None or local_submitted_at.utcoffset() is None:
            raise AssessmentResultPdfInvalid(
                "local submitted timestamp must be timezone-aware"
            )
        sections = projection.get("sections")
        if not isinstance(sections, list):
            raise AssessmentResultPdfInvalid("result sections are invalid")
        item_count = sum(
            len(section.get("items", []))
            for section in sections
            if isinstance(section, dict)
        )
        if item_count > MAX_PDF_ITEMS:
            raise AssessmentResultPdfInvalid("result contains too many items")
        try:
            text_size = len(str(projection))
        except Exception as error:
            raise AssessmentResultPdfInvalid("result projection is invalid") from error
        if text_size > MAX_PDF_TEXT_CHARS:
            raise AssessmentResultPdfInvalid("result text is too large")

    @staticmethod
    def _styles() -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "RestosTitle",
                parent=base["Heading1"],
                fontName=PDF_FONT_BOLD,
                fontSize=22,
                leading=27,
                textColor=colors.HexColor("#203620"),
                alignment=TA_LEFT,
                spaceAfter=8,
            ),
            "subtitle": ParagraphStyle(
                "RestosSubtitle",
                parent=base["Normal"],
                fontName=PDF_FONT_REGULAR,
                fontSize=10,
                leading=14,
                textColor=colors.HexColor("#526052"),
                spaceAfter=4,
            ),
            "heading": ParagraphStyle(
                "RestosHeading",
                parent=base["Heading2"],
                fontName=PDF_FONT_BOLD,
                fontSize=14,
                leading=18,
                textColor=colors.HexColor("#203620"),
                spaceBefore=8,
                spaceAfter=6,
                keepWithNext=1,
            ),
            "body": ParagraphStyle(
                "RestosBody",
                parent=base["BodyText"],
                fontName=PDF_FONT_REGULAR,
                fontSize=9,
                leading=13,
                textColor=colors.HexColor("#202620"),
            ),
            "body_bold": ParagraphStyle(
                "RestosBodyBold",
                parent=base["BodyText"],
                fontName=PDF_FONT_BOLD,
                fontSize=9,
                leading=13,
                textColor=colors.HexColor("#202620"),
            ),
            "score": ParagraphStyle(
                "RestosScore",
                parent=base["Heading1"],
                fontName=PDF_FONT_BOLD,
                fontSize=28,
                leading=32,
                alignment=TA_CENTER,
                textColor=colors.HexColor("#2F5E2B"),
            ),
        }

    def _story(
        self,
        projection: dict[str, Any],
        generated_at: datetime,
        styles: dict[str, ParagraphStyle],
    ) -> list[Any]:
        story: list[Any] = [
            Paragraph("RestOS", styles["subtitle"]),
            Paragraph(escape(str(projection["template_name"])), styles["title"]),
            Paragraph("Завершённый замер", styles["subtitle"]),
            Spacer(1, 4 * mm),
        ]
        info_rows = [
            [
                "Дата и время",
                self._russian_datetime(
                    datetime.fromisoformat(str(projection["local_submitted_at"]))
                ),
            ],
            ["Ресторан", self._safe(projection.get("venue_name") or "Не указан")],
            [
                "Объект оценки",
                self._safe(projection.get("subject_name") or "Не указан"),
            ],
            ["Версия методики", str(projection.get("template_version", "-"))],
        ]
        story.append(self._info_table(info_rows, styles))
        story.append(Spacer(1, 5 * mm))
        if projection.get("score_display"):
            story.append(
                Paragraph(self._safe(projection["score_display"]), styles["score"])
            )
            story.append(Paragraph("Итоговый показатель", styles["subtitle"]))
            story.append(Spacer(1, 3 * mm))
        else:
            story.append(
                Paragraph(
                    "Результат зафиксирован по полноте заполнения.",
                    styles["body"],
                )
            )

        for index, section in enumerate(projection.get("sections", []), 1):
            title = f"{index}. {self._safe(section.get('title'))}"
            display = section.get("score_display")
            if display:
                title = f"{title} - {self._safe(display)}"
            rows = [
                [
                    Paragraph(title, styles["heading"]),
                    "",
                    "",
                ],
                [
                    Paragraph("Вопрос", styles["body_bold"]),
                    Paragraph("Ответ", styles["body_bold"]),
                    Paragraph("Комментарий", styles["body_bold"]),
                ]
            ]
            for item in section.get("items", []):
                rows.append(
                    [
                        Paragraph(self._safe(item.get("prompt")), styles["body"]),
                        Paragraph(self._answer_text(item.get("value")), styles["body"]),
                        Paragraph(
                            self._safe(item.get("comment") or "-"), styles["body"]
                        ),
                    ]
                )
            if len(rows) == 2:
                story.append(Paragraph(title, styles["heading"]))
                story.append(
                    Paragraph("Ответы в разделе не зафиксированы.", styles["body"])
                )
            else:
                table = LongTable(
                    rows,
                    colWidths=[82 * mm, 38 * mm, 48 * mm],
                    repeatRows=2,
                    splitByRow=1,
                    splitInRow=1,
                    hAlign="LEFT",
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("SPAN", (0, 0), (-1, 0)),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D7E4D1")),
                            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#E7EFE3")),
                            (
                                "GRID",
                                (0, 0),
                                (-1, -1),
                                0.35,
                                colors.HexColor("#BCC8B7"),
                            ),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 5),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ]
                    )
                )
                story.append(table)
            if index < len(projection.get("sections", [])):
                story.append(Spacer(1, 3 * mm))

        tasks = projection.get("related_tasks", [])
        if tasks:
            story.append(Paragraph("Связанные задачи", styles["heading"]))
            for task in tasks:
                story.append(
                    Paragraph(
                        f"• {self._safe(task.get('title'))} - {self._task_status(task.get('status'))}",
                        styles["body"],
                    )
                )
        story.extend(
            [
                Spacer(1, 5 * mm),
                Paragraph(
                    f"Документ сформирован: {self._russian_datetime(generated_at)}",
                    styles["subtitle"],
                ),
            ]
        )
        return story

    @staticmethod
    def _info_table(rows: list[list[str]], styles: dict[str, ParagraphStyle]) -> Table:
        values = [
            [
                Paragraph(escape(label), styles["body_bold"]),
                Paragraph(value, styles["body"]),
            ]
            for label, value in rows
        ]
        table = Table(values, colWidths=[42 * mm, 126 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F6F7F2")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D4DCCF")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    @classmethod
    def _answer_text(cls, value: Any) -> str:
        if isinstance(value, list):
            return cls._safe(", ".join(str(item) for item in value) or "-")
        return cls._safe(value if value is not None else "-")

    @staticmethod
    def _safe(value: Any) -> str:
        return escape(str(value))

    @staticmethod
    def _russian_datetime(value: datetime) -> str:
        return (
            f"{value.day} {RUSSIAN_MONTHS[value.month - 1]} {value.year}, "
            f"{value:%H:%M}"
        )

    @classmethod
    def _task_status(cls, value: Any) -> str:
        return cls._safe(TASK_STATUS_LABELS.get(str(value), "Статус недоступен"))
