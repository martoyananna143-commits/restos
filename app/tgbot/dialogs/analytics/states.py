"""States for analytics dialog."""

from aiogram.fsm.state import State, StatesGroup


class AnalyticsDialog(StatesGroup):
    """States for analytics dialog."""

    select_organization = State()  # Выбор организации
    select_analytics_type = State()  # Выбор типа аналитики
    select_criteria = State()  # Выбор критериев для анализа
    select_employees = State()  # Выбор сотрудников для анализа
    select_date_range = State()  # Выбор периода
    select_group_by = State()  # Выбор группировки для среднего балла
    configure_filters = State()  # Настройка фильтров
    display_results = State()  # Отображение результатов
    export_results = State()  # Экспорт результатов
    ai_assistant_select_data = State()  # Выбор типа данных для ИИ
    ai_assistant_view_data = State()  # Просмотр данных с пагинацией
    ai_assistant_chat = State()  # Диалог с ИИ ассистентом
    objects_select_type = State()  # Выбор типа объекта (сотрудники, организации и т.д.)
    objects_list = State()  # Список объектов с пагинацией
    object_detail = State()  # Детальный просмотр объекта

