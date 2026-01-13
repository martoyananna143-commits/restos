"""States for criterion dialog."""

from aiogram.fsm.state import State, StatesGroup


class CriterionDialog(StatesGroup):
    """States for criterion creation dialog."""

    select_organization = State()
    select_criterion = State()  # Выбор существующего критерия или создание нового
    edit_menu = State()  # Меню редактирования существующего критерия
    select_evaluation_type = State()
    evaluation_type_name_input = State()
    evaluation_type_code_input = State()
    evaluation_type_description_input = State()
    evaluation_type_confirm = State()
    select_value_type = State()  # Выбор типа данных критерия (boolean, string, number)
    name_input = State()
    code_input = State()
    description_input = State()
    confirm = State()
    add_more = State()
    edit_evaluation_type = State()
