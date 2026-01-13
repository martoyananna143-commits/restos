"""Analytics dialog module."""

from aiogram_dialog import Dialog

from . import windows


def analytics_dialogs():
    """Get all analytics dialogs."""
    return [
        Dialog(
            windows.select_organization_window(),
            windows.select_analytics_type_window(),
            windows.select_group_by_window(),
            windows.select_criteria_window(),
            windows.select_employees_window(),
            windows.select_date_range_window(),
            windows.display_results_window(),
            windows.ai_assistant_select_data_window(),
            windows.ai_assistant_view_data_window(),
            windows.ai_assistant_chat_window(),
            windows.objects_select_type_window(),
            windows.objects_list_window(),
            windows.object_detail_window(),
        ),
    ]

