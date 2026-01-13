"""States for criterion set dialog."""

from aiogram.fsm.state import State, StatesGroup


class CriterionSetDialog(StatesGroup):
    """States for criterion set creation/management dialog."""

    select_organization = State()
    select_set = State()  # Выбор существующего набора или создание нового
    edit_menu = State()  # Меню редактирования существующего набора
    name_input = State()
    description_input = State()
    select_criteria = State()  # Выбор критериев для набора
    set_default = State()  # Установка как дефолтный
    confirm = State()
    upload_excel = State()  # Загрузка Excel файла для импорта критериев и наборов

