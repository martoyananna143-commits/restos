"""Organization dialog module."""

from aiogram_dialog import Dialog

from . import windows


def organization_dialogs():
    """Get all organization dialogs."""
    return [
        Dialog(
            windows.check_organization_window(),
            windows.select_organization_to_edit_window(),
            windows.edit_menu_window(),
            windows.manage_employees_window(),
            windows.invite_employee_window(),
            windows.name_input_window(),
            windows.code_input_window(),
            windows.address_input_window(),
            windows.phone_input_window(),
            windows.confirm_window(),
        ),
    ]

