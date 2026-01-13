"""States for greeting dialog."""

from aiogram.fsm.state import State, StatesGroup


class GreetingDialog(StatesGroup):
    """States for greeting dialog."""

    greeting = State()
    organizations_menu = State()  # Меню управления организациями
    employees_menu = State()  # Меню управления сотрудниками
    criteria_and_sets_menu = State()  # Меню управления критериями и наборами критериев
    evaluations_menu = State()  # Меню управления оценками/замерами

