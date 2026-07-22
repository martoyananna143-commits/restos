"""States for help dialog."""

from aiogram.fsm.state import State, StatesGroup


class HelpDialog(StatesGroup):
    """States for help/tutorial dialog."""

    main_help = State()  # Главное меню помощи
    step_1_welcome = State()  # Шаг 1: Добро пожаловать
    step_2_organization = State()  # Шаг 2: Создание организации
    step_3_employees = State()  # Шаг 3: Добавление сотрудников
    step_4_criteria = State()  # Шаг 4: Создание критериев
    step_5_sets = State()  # Шаг 5: Наборы критериев
    step_6_evaluation = State()  # Шаг 6: Проведение оценки
    step_7_analytics = State()  # Шаг 7: Аналитика и отчеты
    step_8_advanced = State()  # Шаг 8: Продвинутые возможности
    final_step = State()  # Финальный шаг
