"""Greeting dialog module."""

from aiogram_dialog import Dialog

from . import windows


def greeting_dialogs():
    """Get all greeting dialogs."""
    return [
        Dialog(
            windows.greeting_window(),
            windows.organizations_menu_window(),
            windows.employees_menu_window(),
            windows.criteria_and_sets_menu_window(),
            windows.evaluations_menu_window(),
        ),
    ]

