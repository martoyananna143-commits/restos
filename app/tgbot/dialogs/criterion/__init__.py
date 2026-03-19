"""Criterion dialog module."""

from aiogram_dialog import Dialog

from . import windows


def criterion_dialogs():
    """Get all criterion dialogs."""
    return [
        Dialog(
            windows.select_organization_window(),
            windows.select_criterion_window(),
            windows.edit_menu_window(),
            windows.select_value_type_window(),
            windows.select_is_required_window(),
            windows.name_input_window(),
            windows.code_input_window(),
            windows.description_input_window(),
            windows.confirm_window(),
            windows.add_more_window(),
        ),
    ]
