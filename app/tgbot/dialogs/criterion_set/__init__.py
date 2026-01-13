"""Criterion set dialog module."""

from aiogram_dialog import Dialog

from . import windows


def criterion_set_dialogs():
    """Get all criterion set dialogs."""
    return [
        Dialog(
            windows.select_organization_window(),
            windows.select_set_window(),
            windows.upload_excel_window(),
            windows.edit_menu_window(),
            windows.name_input_window(),
            windows.description_input_window(),
            windows.select_criteria_window(),
            windows.set_default_window(),
            windows.confirm_window(),
        ),
    ]

