"""States for evaluation dialog."""

from aiogram.fsm.state import State, StatesGroup


class EvaluationDialog(StatesGroup):
    """States for evaluation dialog."""

    select_evaluation_type = State()
    evaluation_type_name_input = State()
    evaluation_type_code_input = State()
    evaluation_type_description_input = State()
    evaluation_type_confirm = State()
    select_organization = State()
    select_filled_by_employee = State()
    select_evaluated_employee = State()
    select_criterion_set = State()  # Опционально, если есть дефолтный набор
    combine_criterion_sets = State()  # Выбор нескольких наборов для комбинирования
    question_loop = State()  # Цикл вопросов
    answer_question = State()  # Выбор Да/Нет для вопроса (boolean)
    answer_text = State()  # Ввод текста для вопроса (string)
    answer_number = State()  # Ввод числа для вопроса (number)
    add_comment = State()  # Опциональный комментарий
    send_to_employee = State()  # Отправка результата
    generate_pdf = State()  # Генерация PDF отчета

