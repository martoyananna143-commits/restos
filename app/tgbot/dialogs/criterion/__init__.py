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
            windows.select_evaluation_type_window(),
            windows.evaluation_type_name_input_window(),
            windows.evaluation_type_code_input_window(),
            windows.evaluation_type_description_input_window(),
            windows.evaluation_type_confirm_window(),
            windows.select_value_type_window(),
            windows.name_input_window(),
            windows.code_input_window(),
            windows.description_input_window(),
            windows.confirm_window(),
            windows.add_more_window(),
            windows.edit_evaluation_type_window(),
        ),
    ]
