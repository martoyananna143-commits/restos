"""Export dialog."""

from aiogram_dialog import Dialog

from app.tgbot.dialogs.export.windows import select_format_window


def export_dialog():
    """Create export dialog.

    Returns:
        Dialog: The configured export dialog.
    """
    return Dialog(
        select_format_window(),
    )
