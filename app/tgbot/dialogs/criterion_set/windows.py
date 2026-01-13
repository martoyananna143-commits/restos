"""Windows for criterion set dialog."""

from aiogram_dialog import Window
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import (
    Back,
    Button,
    Row,
    ScrollingGroup,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format

from app.tgbot.dialogs.common.criterion_set import create_criterion_set_select_window
from app.tgbot.dialogs.common.organization import create_organization_select_window
from app.tgbot.dialogs.criterion_set.getters import (
    get_criteria_list_data,
    get_criterion_set_form_data,
    get_criterion_sets_list_data,
)
from app.tgbot.dialogs.criterion_set.handlers import (
    on_back_from_criterion_set_creation,
    on_cancel_criterion_set,
    on_confirm_criterion_set,
    on_create_new_criterion_from_set,
    on_create_new_set,
    on_edit_criteria,
    on_edit_default_status,
    on_edit_description,
    on_edit_name,
    on_finish_criteria_selection,
    on_save_changes,
    on_select_existing_set,
    on_set_default_no,
    on_set_default_yes,
    on_skip_description,
    on_toggle_criterion,
    on_upload_excel_clicked,
    process_description_input,
    process_name_input,
    process_excel_upload,
)
from app.tgbot.dialogs.criterion_set.states import CriterionSetDialog


def select_organization_window():
    """Create organization selection window.

    Returns:
        Window: The configured organization selection window.
    """
    return create_organization_select_window(
        state=CriterionSetDialog.select_organization,
        message_text="Выберите организацию для работы с наборами критериев:",
        next_state=CriterionSetDialog.select_set,
        cancel_handler=on_cancel_criterion_set,
    )


def select_set_window():
    """Create criterion set selection window.

    Returns:
        Window: The configured criterion set selection window.
    """
    return Window(
        Format("Выберите набор критериев или создайте новый:"),
        ScrollingGroup(
            Select(
                Format("{item[display_name]}"),
                item_id_getter=lambda cs: cs["id"] if isinstance(cs, dict) else cs.id,
                items="criterion_sets",
                id="select_criterion_set",
                on_click=on_select_existing_set,
            ),
            id="scrolling_criterion_sets",
            width=1,
            height=10,
            when="has_criterion_sets",
        ),
        Row(
            Button(
                text=Const("Создать новый набор ➕"),
                id="create_new_set",
                on_click=on_create_new_set,
                when="no_criterion_sets",
            ),
        ),
        Row(
            Button(
                text=Const("Загрузить из Excel 📊"),
                id="upload_excel",
                on_click=on_upload_excel_clicked,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_criterion_set",
            state=CriterionSetDialog.select_organization,
        ),
        state=CriterionSetDialog.select_set,
        getter=get_criterion_sets_list_data,
    )


def edit_menu_window():
    """Create edit menu window for existing criterion set.

    Returns:
        Window: The configured edit menu window.
    """
    return Window(
        Format(
            "Редактирование набора критериев:\n\n"
            "Название: {name}\n"
            "Описание: {description}\n"
            "Критериев в наборе: {criteria_count}\n"
            "Дефолтный: {is_default_text}\n\n"
            "Что вы хотите изменить?"
        ),
        Row(
            Button(
                text=Const("Изменить название ✏️"),
                id="edit_name",
                on_click=on_edit_name,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить описание 📝"),
                id="edit_description",
                on_click=on_edit_description,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить критерии 📋"),
                id="edit_criteria",
                on_click=on_edit_criteria,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить дефолтный статус ⭐"),
                id="edit_default_status",
                on_click=on_edit_default_status,
            ),
        ),
        Row(
            Button(
                text=Const("Сохранить изменения ✅"),
                id="save_changes",
                on_click=on_save_changes,
            ),
        ),
        SwitchTo(Const("Назад"), id="back_edit_menu_window", state=CriterionSetDialog.select_set),
        state=CriterionSetDialog.edit_menu,
        getter=get_criterion_set_form_data,
    )


def name_input_window():
    """Create name input window.

    Returns:
        Window: The configured name input window.
    """
    return Window(
        Format(
            "Введите название набора критериев:",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format("Введите новое название набора критериев:", when="is_editing"),
        MessageInput(process_name_input),
        SwitchTo(
            Const("Назад"),
            id="back_name_input_edit_window",
            state=CriterionSetDialog.edit_menu,
            when="is_editing",
        ),
        Button(
            Const("Назад"),
            id="back_name_input_from_evaluation",
            on_click=on_back_from_criterion_set_creation,
            when=lambda data, widget, manager: (
                not data.get("is_editing", False)
                and manager.middleware_data.get("from_evaluation", False)
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_set_input_default",
            state=CriterionSetDialog.select_set,
            when=lambda data, widget, manager: (
                not data.get("is_editing", False)
                and not manager.middleware_data.get("from_evaluation", False)
            ),
        ),
        state=CriterionSetDialog.name_input,
        getter=get_criterion_set_form_data,
    )


def description_input_window():
    """Create description input window.

    Returns:
        Window: The configured description input window.
    """
    return Window(
        Format(
            "Введите описание набора критериев (или нажмите 'Пропустить'):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новое описание набора критериев (или нажмите 'Пропустить'):",
            when="is_editing",
        ),
        MessageInput(process_description_input),
        Row(
            Button(
                text=Const("Пропустить ⏭️"),
                id="skip_description",
                on_click=on_skip_description,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_description_input_edit_window",
                state=CriterionSetDialog.edit_menu,
                when="is_editing",
            ),
            Button(
                Const("Назад"),
                id="back_description_input_from_evaluation",
                on_click=on_back_from_criterion_set_creation,
                when=lambda data, widget, manager: (
                    not data.get("is_editing", False)
                    and manager.middleware_data.get("from_evaluation", False)
                ),
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: (
                    not data.get("is_editing", False)
                    and not manager.middleware_data.get("from_evaluation", False)
                ),
            ),
        ),
        state=CriterionSetDialog.description_input,
        getter=get_criterion_set_form_data,
    )


def select_criteria_window():
    """Create criteria selection window.

    Returns:
        Window: The configured criteria selection window.
    """
    return Window(
        Format(
            "Выберите критерии для включения в набор:\n\nВыбрано: {criteria_count}",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Измените критерии в наборе (нажмите для добавления/удаления):\n\nВыбрано: {criteria_count}",
            when="is_editing",
        ),
        ScrollingGroup(
            Select(
                Format("{item[name]} {item[selected_marker]}"),
                item_id_getter=lambda c: c["id"] if isinstance(c, dict) else c.id,
                items="criteria",
                id="toggle_criterion",
                on_click=on_toggle_criterion,
            ),
            id="scrolling_criteria",
            width=1,
            height=10,
            when="has_criteria",
        ),
        Row(
            Button(
                text=Const("Создать новый критерий ➕"),
                id="create_new_criterion",
                on_click=on_create_new_criterion_from_set,
                when="no_criteria",
            ),
        ),
        Row(
            Button(
                text=Const("Завершить выбор ✅"),
                id="finish_criteria_selection",
                on_click=on_finish_criteria_selection,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_select_criteria_edit_window",
            state=CriterionSetDialog.edit_menu,
            when="is_editing",
        ),
        Back(
            Const("Назад"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=CriterionSetDialog.select_criteria,
        getter=get_criteria_list_data,
    )


def set_default_window():
    """Create set default window.

    Returns:
        Window: The configured set default window.
    """
    return Window(
        Format(
            "Установить этот набор как дефолтный?\n\n"
            "Дефолтный набор будет использоваться по умолчанию при создании оценки.",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Изменить дефолтный статус набора?\n\n"
            "Текущий статус: {current_default_text}\n\n"
            "Дефолтный набор будет использоваться по умолчанию при создании оценки.",
            when="is_editing",
        ),
        Row(
            Button(
                text=Const("Да ✅"),
                id="set_default_yes",
                on_click=on_set_default_yes,
            ),
            Button(
                text=Const("Нет"),
                id="set_default_no",
                on_click=on_set_default_no,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_set_default_edit_window",
            state=CriterionSetDialog.edit_menu,
            when="is_editing",
        ),
        Back(
            Const("Назад"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=CriterionSetDialog.set_default,
        getter=get_criterion_set_form_data,
    )


def confirm_window():
    """Create confirm window.

    Returns:
        Window: The configured confirm window.
    """
    return Window(
        Format(
            "Проверьте данные набора критериев:\n\n"
            "Название: {name}\n"
            "Описание: {description}\n"
            "Критериев в наборе: {criteria_count}\n"
            "Дефолтный: {is_default_text}\n\n"
            "Всё верно?",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Проверьте изменения набора критериев:\n\n"
            "Название: {name}\n"
            "Описание: {description}\n"
            "Критериев в наборе: {criteria_count}\n"
            "Дефолтный: {is_default_text}\n\n"
            "Сохранить изменения?",
            when="is_editing",
        ),
        Row(
            Button(
                text=Const("Подтвердить ✅"),
                id="confirm",
                on_click=on_confirm_criterion_set,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_confirm_window",
                state=CriterionSetDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=CriterionSetDialog.confirm,
        getter=get_criterion_set_form_data,
    )


def upload_excel_window():
    """Create Excel upload window.

    Returns:
        Window: The configured Excel upload window.
    """
    return Window(
        Const(
            "Загрузите Excel файл с критериями и наборами.\n\n"
            "Формат файла:\n"
            "• Колонка 1: Название набора критериев\n"
            "• Колонка 2: Вопрос критерия\n"
            "• Колонка 3: Тип критерия (bool, str, num)\n\n"
            "Пример:\n"
            "Набор 1 | Вопрос 1? | bool\n"
            "Набор 1 | Вопрос 2? | str\n"
            "Набор 2 | Вопрос 3? | num\n\n"
            "Отправьте Excel файл (.xlsx):"
        ),
        MessageInput(process_excel_upload),
        SwitchTo(
            Const("Назад"),
            id="back_upload_excel",
            state=CriterionSetDialog.select_set,
        ),
        state=CriterionSetDialog.upload_excel,
    )
