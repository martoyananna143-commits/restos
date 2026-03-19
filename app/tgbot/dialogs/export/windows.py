"""Windows for export dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.kbd import Button, Row
from aiogram_dialog.widgets.text import Format

from app.tgbot.dialogs.export.getters import get_export_data
from app.tgbot.dialogs.export.handlers import (
    on_done,
    on_generate_excel,
    on_generate_pdf,
)
from app.tgbot.dialogs.export.states import ExportDialog


def select_format_window():
    """Create export format selection window."""
    return Window(
        Format("{message_text}"),
        Row(
            Button(
                text=Format("📄 PDF"),
                id="export_pdf",
                on_click=on_generate_pdf,
                when="show_pdf_button",
            ),
            Button(
                text=Format("📊 Excel"),
                id="export_excel",
                on_click=on_generate_excel,
                when="show_excel_button",
            ),
        ),
        Button(
            text=Format("✅ Готово"),
            id="done",
            on_click=on_done,
        ),
        state=ExportDialog.select_format,
        getter=get_export_data,
        parse_mode="HTML",
    )
