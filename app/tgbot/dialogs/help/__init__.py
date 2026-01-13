"""Help dialog for Restos bot."""

from aiogram_dialog import Dialog

from app.tgbot.dialogs.help.states import HelpDialog
from app.tgbot.dialogs.help.windows import (
    final_step_window,
    help_main_window,
    step_1_welcome_window,
    step_2_organization_window,
    step_3_employees_window,
    step_4_criteria_window,
    step_5_sets_window,
    step_6_evaluation_window,
    step_7_analytics_window,
    step_8_advanced_window,
)


def help_dialog():
    """Create help dialog with tutorial.

    Returns:
        Dialog: The configured help dialog.
    """
    return Dialog(
        help_main_window(),
        step_1_welcome_window(),
        step_2_organization_window(),
        step_3_employees_window(),
        step_4_criteria_window(),
        step_5_sets_window(),
        step_6_evaluation_window(),
        step_7_analytics_window(),
        step_8_advanced_window(),
        final_step_window(),
    )
