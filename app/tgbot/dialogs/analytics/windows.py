"""Windows for analytics dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import (
    Button,
    Cancel,
    Group,
    Row,
    ScrollingGroup,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format

from app.tgbot.dialogs.analytics import getters_objects
from app.tgbot.dialogs.analytics.getters import (
    get_ai_view_data,
    get_analytics_type_data,
    get_criteria_list_data,
    get_employees_list_data,
    get_group_by_data,
)
from app.tgbot.dialogs.analytics.handlers import (
    on_ai_data_next_page,
    on_ai_data_prev_page,
    on_ai_data_start_chat,
    on_ai_message,
    on_cancel_analytics,
    on_clear_ai_history,
    on_delete_evaluation_from_analytics,
    on_export_object_excel,
    on_export_object_pdf,
    on_finish_selection,
    on_objects_next_page,
    on_objects_prev_page,
    on_select_ai_data_type,
    on_select_analytics_type,
    on_select_group_by,
    on_select_object,
    on_select_object_type,
    on_set_date_range_all_time,
    on_set_date_range_month,
    on_set_date_range_quarter,
    on_set_date_range_today,
    on_set_date_range_week,
    on_set_date_range_year,
    on_show_last_ai_response,
    on_start_ai_chat_without_data,
    on_toggle_criterion,
    on_toggle_employee,
)
from app.tgbot.dialogs.analytics.states import AnalyticsDialog
from app.tgbot.dialogs.common.organization import create_organization_select_window


def select_organization_window():
    """Create organization selection window.

    Returns:
        Window: The configured organization selection window.
    """
    return create_organization_select_window(
        state=AnalyticsDialog.select_organization,
        message_text="Выберите организацию для анализа:",
        next_state=AnalyticsDialog.select_analytics_type,
        cancel_handler=on_cancel_analytics,
        use_scrolling=True,
    )


def select_analytics_type_window():
    """Create analytics type selection window.

    Returns:
        Window: The configured analytics type selection window.
    """
    return Window(
        Format("📊 Выберите тип аналитики:"),
        Group(
            Select(
                Format("{item[name]}"),
                item_id_getter=lambda at: at["id"],
                items="analytics_types",
                id="select_analytics_type",
                on_click=on_select_analytics_type,
                when="analytics_types",
            ),
            width=1,
        ),
        Cancel(Const("Назад ⬅️")),
        state=AnalyticsDialog.select_analytics_type,
        getter=get_analytics_type_data,
    )


def select_criteria_window():
    """Create criteria selection window.

    Returns:
        Window: The configured criteria selection window.
    """
    return Window(
        Format("📋 Выберите критерии для анализа:\n\n✅ Выбрано: {selected_count}"),
        ScrollingGroup(
            Select(
                Format("{item[marker]} {item[display_name]}"),
                item_id_getter=lambda c: str(c["id"]),
                items="criteria",
                id="toggle_criterion",
                on_click=on_toggle_criterion,
            ),
            id="scrolling_criteria",
            width=1,
            height=10,
            when="has_criteria",
            hide_on_single_page=True,
        ),
        Row(
            Button(
                text=Const("Завершить выбор ✅"),
                id="finish_selection",
                on_click=on_finish_selection,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_from_criteria",
            state=AnalyticsDialog.select_analytics_type,
        ),
        state=AnalyticsDialog.select_criteria,
        getter=get_criteria_list_data,
    )


def select_employees_window():
    """Create employees selection window.

    Returns:
        Window: The configured employees selection window.
    """
    return Window(
        Format(
            "👥 Выберите сотрудников для анализа:\n\n✅ Выбрано: {selected_count}\n\n(Оставьте пустым для всех сотрудников)"
        ),
        ScrollingGroup(
            Select(
                Format("{item[marker]} {item[display_name]}"),
                item_id_getter=lambda e: str(e["id"]),
                items="employees",
                id="toggle_employee",
                on_click=on_toggle_employee,
            ),
            id="scrolling_employees",
            width=1,
            height=10,
            when="has_employees",
            hide_on_single_page=True,
        ),
        Row(
            Button(
                text=Const("Завершить выбор ✅"),
                id="finish_selection",
                on_click=on_finish_selection,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_criteria",
            state=AnalyticsDialog.select_criteria,
        ),
        state=AnalyticsDialog.select_employees,
        getter=get_employees_list_data,
    )


def select_group_by_window():
    """Create group by selection window.

    Returns:
        Window: The configured group by selection window.
    """
    return Window(
        Format("📊 Выберите способ группировки:"),
        Group(
            Select(
                Format("{item[name]}"),
                item_id_getter=lambda gb: gb["id"],
                items="group_by_options",
                id="select_group_by",
                on_click=on_select_group_by,
                when="group_by_options",
            ),
            width=1,
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_analytics_type",
            state=AnalyticsDialog.select_analytics_type,
        ),
        state=AnalyticsDialog.select_group_by,
        getter=get_group_by_data,
    )


def select_date_range_window():
    """Create date range selection window.

    Returns:
        Window: The configured date range selection window.
    """
    return Window(
        Format("📅 Выберите период для анализа:"),
        Row(
            Button(
                text=Const("Сегодня 📅"),
                id="today",
                on_click=on_set_date_range_today,
            ),
            Button(
                text=Const("Неделя 📆"),
                id="week",
                on_click=on_set_date_range_week,
            ),
        ),
        Row(
            Button(
                text=Const("Месяц 🗓️"),
                id="month",
                on_click=on_set_date_range_month,
            ),
            Button(
                text=Const("Квартал 📊"),
                id="quarter",
                on_click=on_set_date_range_quarter,
            ),
        ),
        Row(
            Button(
                text=Const("Год 📈"),
                id="year",
                on_click=on_set_date_range_year,
            ),
            Button(
                text=Const("Все время ⏰"),
                id="all_time",
                on_click=on_set_date_range_all_time,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_from_date_range",
            state=AnalyticsDialog.select_criteria,
            when=lambda data, widget, manager: data.get("analytics_type")
            in ["criteria_stats", "average_scores"],
        ),
        SwitchTo(
            Const("Назад"),
            id="back_from_date_range_to_employees",
            state=AnalyticsDialog.select_employees,
            when=lambda data, widget, manager: data.get("analytics_type")
            not in ["criteria_stats", "average_scores"],
        ),
        state=AnalyticsDialog.select_date_range,
    )


def display_results_window():
    """Create results display window.

    Returns:
        Window: The configured results display window.
    """
    from app.tgbot.dialogs.analytics.getters import get_results_data

    return Window(
        Format("{results_text}"),
        SwitchTo(
            Const("Назад"),
            id="back_to_date_range",
            state=AnalyticsDialog.select_date_range,
            when=lambda data, widget, manager: data.get("analytics_type")
            in ["criteria_stats", "average_scores"],
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_analytics_type_from_results",
            state=AnalyticsDialog.select_analytics_type,
            when=lambda data, widget, manager: data.get("analytics_type")
            not in ["criteria_stats", "average_scores"],
        ),
        state=AnalyticsDialog.display_results,
        getter=get_results_data,
    )


def ai_assistant_select_data_window():
    """Create AI assistant data type selection window.

    Returns:
        Window: The configured AI assistant data type selection window.
    """
    from app.tgbot.dialogs.analytics.getters import get_ai_data_type_data

    return Window(
        Format("🤖 Выберите тип данных для анализа:"),
        Group(
            Select(
                Format("{item[name]}"),
                item_id_getter=lambda dt: dt["id"],
                items="data_types",
                id="select_ai_data_type",
                on_click=on_select_ai_data_type,
                when="data_types",
            ),
            width=1,
        ),
        Row(
            Button(
                text=Const("💬 Просто чат (без данных)"),
                id="start_ai_chat_without_data",
                on_click=on_start_ai_chat_without_data,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_analytics_type_from_ai",
            state=AnalyticsDialog.select_analytics_type,
        ),
        state=AnalyticsDialog.ai_assistant_select_data,
        getter=get_ai_data_type_data,
    )


def ai_assistant_view_data_window():
    """Create AI data view window with pagination.

    Returns:
        Window: The configured AI data view window.
    """
    return Window(
        Format("{display_text}"),
        Row(
            Button(
                text=Const("◀️ Назад"),
                id="ai_data_prev_page",
                on_click=on_ai_data_prev_page,
                when="has_prev",
            ),
            Button(
                text=Const("Вперед ▶️"),
                id="ai_data_next_page",
                on_click=on_ai_data_next_page,
                when="has_next",
            ),
        ),
        Row(
            Button(
                text=Const("💬 Начать чат с ИИ"),
                id="ai_data_start_chat",
                on_click=on_ai_data_start_chat,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_ai_select_data",
            state=AnalyticsDialog.ai_assistant_select_data,
        ),
        state=AnalyticsDialog.ai_assistant_view_data,
        getter=get_ai_view_data,
    )


def ai_assistant_chat_window():
    """Create AI assistant chat window.

    Returns:
        Window: The configured AI assistant chat window.
    """
    from app.tgbot.dialogs.analytics.getters import get_ai_assistant_data

    return Window(
        Format("{assistant_message}"),
        MessageInput(
            func=on_ai_message,
            content_types=["text"],
        ),
        Button(
            text=Const("📋 Показать последний ответ"),
            id="show_last_ai_response",
            on_click=on_show_last_ai_response,
            when=lambda data, widget, manager: (
                data.get("has_last_response")
                and not data.get("show_last_response", False)
            ),
        ),
        Button(
            text=Const("🗑️ Очистить историю"),
            id="clear_ai_history",
            on_click=on_clear_ai_history,
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_ai_view_data",
            state=AnalyticsDialog.ai_assistant_view_data,
            when=lambda data, widget, manager: data.get("ai_data_loaded", False),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_ai_select_data_from_chat",
            state=AnalyticsDialog.ai_assistant_select_data,
            when=lambda data, widget, manager: not data.get("ai_data_loaded", False),
        ),
        state=AnalyticsDialog.ai_assistant_chat,
        getter=get_ai_assistant_data,
    )


def objects_select_type_window():
    """Create object type selection window.

    Returns:
        Window: The configured object type selection window.
    """
    return Window(
        Format("📦 Выберите тип объекта для просмотра:"),
        Group(
            Select(
                Format("{item[name]}"),
                item_id_getter=lambda dt: dt["id"],
                items="object_types",
                id="select_object_type",
                on_click=on_select_object_type,
                when="object_types",
            ),
            width=1,
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_analytics_type_from_objects",
            state=AnalyticsDialog.select_analytics_type,
        ),
        state=AnalyticsDialog.objects_select_type,
        getter=getters_objects.get_objects_type_data,
    )


def objects_list_window():
    """Create objects list window with pagination.

    Returns:
        Window: The configured objects list window.
    """
    return Window(
        Format("{display_text}"),
        ScrollingGroup(
            Select(
                Format("{item[name]}"),
                item_id_getter=lambda item: str(item["id"]),
                items="objects",
                id="select_object",
                on_click=on_select_object,
            ),
            id="scrolling_objects",
            width=1,
            height=10,
            hide_on_single_page=True,
            when="has_objects",
        ),
        Row(
            Button(
                text=Const("◀️ Назад"),
                id="objects_prev_page",
                on_click=on_objects_prev_page,
                when="has_prev",
            ),
            Button(
                text=Const("Вперед ▶️"),
                id="objects_next_page",
                on_click=on_objects_next_page,
                when="has_next",
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_objects_select_type",
            state=AnalyticsDialog.objects_select_type,
        ),
        state=AnalyticsDialog.objects_list,
        getter=getters_objects.get_objects_list_data,
    )


def object_detail_window():
    """Create object detail window with export options.

    Returns:
        Window: The configured object detail window.
    """
    return Window(
        Format("{detail_text}"),
        Row(
            Button(
                text=Const("📄 Экспорт в PDF"),
                id="export_object_pdf",
                on_click=on_export_object_pdf,
            ),
            Button(
                text=Const("📊 Экспорт в Excel"),
                id="export_object_excel",
                on_click=on_export_object_excel,
            ),
        ),
        Row(
            Button(
                text=Const("🗑️ Удалить замер"),
                id="delete_evaluation_from_analytics",
                on_click=on_delete_evaluation_from_analytics,
                when="is_evaluation",
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_to_objects_list",
            state=AnalyticsDialog.objects_list,
        ),
        state=AnalyticsDialog.object_detail,
        getter=getters_objects.get_object_detail_data,
    )
