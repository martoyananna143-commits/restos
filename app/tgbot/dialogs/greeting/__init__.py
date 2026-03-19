"""Greeting dialog module."""

from aiogram_dialog import Dialog

from . import windows


def greeting_dialogs():
    """Get all greeting dialogs."""
    return [
        Dialog(
            # Main menu
            windows.greeting_window(),
            # Admin panel branch
            windows.admin_panel_window(),
            windows.organizations_menu_window(),
            windows.employees_menu_window(),
            windows.criteria_and_sets_menu_window(),
            windows.evaluations_admin_menu_window(),
            # My menu branch
            windows.my_menu_window(),
            windows.my_evaluations_window(),
            # Invitations
            windows.invite_admin_window(),
            windows.select_invite_role_window(),
            windows.invite_to_org_window(),
            # Switch organization (superuser)
            windows.switch_organization_window(),
        ),
    ]
