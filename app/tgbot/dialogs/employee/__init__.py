"""Employee dialog module."""

from aiogram_dialog import Dialog

from . import windows


def employee_dialogs():
    """Get all employee dialogs."""
    return [
        Dialog(
            windows.select_organization_window(),
            windows.select_organization_for_edit_window(),
            windows.select_employee_to_edit_window(),
            windows.edit_menu_window(),
            windows.full_name_input_window(),
            windows.position_input_window(),
            windows.phone_input_window(),
            windows.select_role_window(),
            windows.confirm_window(),
            windows.add_more_window(),
        ),
    ]

