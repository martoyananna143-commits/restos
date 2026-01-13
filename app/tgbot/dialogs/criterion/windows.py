"""Windows for criterion dialog."""

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

from app.tgbot.dialogs.common.evaluation_type import (
    create_evaluation_type_code_input_window,
    create_evaluation_type_confirm_window,
    create_evaluation_type_description_input_window,
    create_evaluation_type_name_input_window,
    create_evaluation_type_select_window,
)
from app.tgbot.dialogs.common.organization import create_organization_select_window
from app.tgbot.dialogs.criterion.getters import (
    get_criteria_list_data,
    get_criterion_form_data,
    is_editing,
)
from app.tgbot.dialogs.criterion.handlers import (
    on_add_more_no,
    on_add_more_yes,
    on_cancel_criterion,
    on_confirm_criterion,
    on_confirm_evaluation_type,
    on_create_new_criterion,
    on_create_organization_from_criterion,
    on_edit_code,
    on_edit_description,
    on_edit_evaluation_type,
    on_edit_name,
    on_edit_value_type,
    on_save_changes,
    on_select_existing_criterion,
    on_select_value_type_boolean,
    on_select_value_type_number,
    on_select_value_type_string,
    on_skip_description,
    on_skip_evaluation_type_description,
    process_code_input,
    process_description_input,
    process_evaluation_type_code_input,
    process_evaluation_type_description_input,
    process_evaluation_type_name_input,
    process_name_input,
)
from app.tgbot.dialogs.criterion.states import CriterionDialog


def select_organization_window():
    """Create organization selection window.

    Returns:
        Window: The configured organization selection window.
    """
    return create_organization_select_window(
        state=CriterionDialog.select_organization,
        message_text="Выберите организацию для работы с критериями:",
        next_state=CriterionDialog.select_criterion,
        cancel_handler=on_cancel_criterion,
        create_organization_handler=on_create_organization_from_criterion,
        use_scrolling=True,
    )


def select_criterion_window():
    """Create criterion selection window.

    Returns:
        Window: The configured criterion selection window.
    """
    return Window(
        Format("Выберите критерий или создайте новый:"),
        ScrollingGroup(
            Select(
                Format("{item[display_name]}"),
                item_id_getter=lambda c: c["id"] if isinstance(c, dict) else c.id,
                items="criteria",
                id="select_criterion",
                on_click=on_select_existing_criterion,
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
                on_click=on_create_new_criterion,
            ),
        ),
        Back(Const("Назад")),
        state=CriterionDialog.select_criterion,
        getter=get_criteria_list_data,
    )


def edit_menu_window():
    """Create edit menu window for existing criterion.

    Returns:
        Window: The configured edit menu window.
    """
    return Window(
        Format(
            "Редактирование критерия:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Описание: {description}\n"
            "Тип оценки: {evaluation_type_name}\n"
            "Тип данных: {value_type_name}\n\n"
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
                text=Const("Изменить код 🔤"),
                id="edit_code",
                on_click=on_edit_code,
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
                text=Const("Изменить тип оценки 📊"),
                id="edit_evaluation_type",
                on_click=on_edit_evaluation_type,
            ),
        ),
        Row(
            Button(
                text=Const("Изменить тип данных 🔢"),
                id="edit_value_type",
                on_click=on_edit_value_type,
            ),
        ),
        Row(
            Button(
                text=Const("Сохранить изменения ✅"),
                id="save_changes",
                on_click=on_save_changes,
            ),
        ),
        Back(Const("Назад")),
        state=CriterionDialog.edit_menu,
        getter=get_criterion_form_data,
    )


def select_evaluation_type_window():
    """Create evaluation type selection window.

    Returns:
        Window: The configured evaluation type selection window.
    """
    return create_evaluation_type_select_window(
        state=CriterionDialog.select_evaluation_type,
        message_text="Выберите тип оценки:",
        next_state=CriterionDialog.name_input,
        create_evaluation_type_state=CriterionDialog.evaluation_type_name_input,
        use_scrolling=True,  # Menu selection - no pagination
    )


def edit_evaluation_type_window():
    """Edit evaluation type selection window.

    Returns:
        Window: The configured evaluation type selection window.
    """
    return create_evaluation_type_select_window(
        state=CriterionDialog.edit_evaluation_type,
        message_text="Выберите тип оценки:",
        next_state=CriterionDialog.edit_menu,
        create_evaluation_type_state=CriterionDialog.evaluation_type_name_input,
        use_scrolling=True,  # Menu selection - no pagination
        switch_to=SwitchTo(
            Const("Назад"),
            id="back_evaluation_type_edit_window",
            state=CriterionDialog.edit_menu,
        ),
    )


def evaluation_type_name_input_window():
    """Create evaluation type name input window.

    Returns:
        Window: The configured evaluation type name input window.
    """
    return create_evaluation_type_name_input_window(
        state=CriterionDialog.evaluation_type_name_input,
        process_name_handler=process_evaluation_type_name_input,
        back_state=CriterionDialog.select_evaluation_type,
    )


def evaluation_type_code_input_window():
    """Create evaluation type code input window.

    Returns:
        Window: The configured evaluation type code input window.
    """
    return create_evaluation_type_code_input_window(
        state=CriterionDialog.evaluation_type_code_input,
        process_code_handler=process_evaluation_type_code_input,
        back_state=CriterionDialog.evaluation_type_name_input,
    )


def evaluation_type_description_input_window():
    """Create evaluation type description input window.

    Returns:
        Window: The configured evaluation type description input window.
    """
    return create_evaluation_type_description_input_window(
        state=CriterionDialog.evaluation_type_description_input,
        process_description_handler=process_evaluation_type_description_input,
        skip_handler=on_skip_evaluation_type_description,
        back_state=CriterionDialog.evaluation_type_code_input,
    )


def evaluation_type_confirm_window():
    """Create evaluation type confirm window.

    Returns:
        Window: The configured evaluation type confirm window.
    """
    return create_evaluation_type_confirm_window(
        state=CriterionDialog.evaluation_type_confirm,
        confirm_handler=on_confirm_evaluation_type,
        back_state=CriterionDialog.evaluation_type_description_input,
    )


def select_value_type_window():
    """Create value type selection window.

    Returns:
        Window: The configured value type selection window.
    """
    return Window(
        Format("Выберите тип данных для критерия:"),
        Row(
            Button(
                text=Const("Да/Нет (boolean) ✓"),
                id="boolean",
                on_click=on_select_value_type_boolean,
            ),
        ),
        Row(
            Button(
                text=Const("Текст (string) 📝"),
                id="string",
                on_click=on_select_value_type_string,
            ),
        ),
        Row(
            Button(
                text=Const("Число (number) 🔢"),
                id="number",
                on_click=on_select_value_type_number,
            ),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_value_type_edit_window",
            state=CriterionDialog.edit_menu,
            when="is_editing",
        ),
        Back(
            Const("Назад"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=CriterionDialog.select_value_type,
        getter=is_editing,
    )


def name_input_window():
    """Create name input window.

    Returns:
        Window: The configured name input window.
    """
    return Window(
        Format(
            "Введите название критерия:",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format("Введите новое название критерия:", when="is_editing"),
        MessageInput(process_name_input),
        SwitchTo(
            Const("Назад"),
            id="back_name_input_window",
            state=CriterionDialog.select_evaluation_type,
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        SwitchTo(
            Const("Назад"),
            id="back_name_edit_window",
            state=CriterionDialog.edit_menu,
            when="is_editing",
        ),
        state=CriterionDialog.name_input,
        getter=get_criterion_form_data,
    )


def code_input_window():
    """Create code input window.

    Returns:
        Window: The configured code input window.
    """
    return Window(
        Format(
            "Введите код критерия (уникальный идентификатор):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новый код критерия (уникальный идентификатор):", when="is_editing"
        ),
        MessageInput(process_code_input),
        SwitchTo(
            Const("Назад"),
            id="back_code_edit_window",
            state=CriterionDialog.edit_menu,
            when="is_editing",
        ),
        Back(
            Const("Назад"),
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        state=CriterionDialog.code_input,
        getter=get_criterion_form_data,
    )


def description_input_window():
    """Create description input window.

    Returns:
        Window: The configured description input window.
    """
    return Window(
        Format(
            "Введите описание критерия (или нажмите 'Пропустить'):",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Введите новое описание критерия (или нажмите 'Пропустить'):",
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
                id="back_description_edit_window",
                state=CriterionDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=CriterionDialog.description_input,
        getter=get_criterion_form_data,
    )


def confirm_window():
    """Create confirm window.

    Returns:
        Window: The configured confirm window.
    """
    return Window(
        Format(
            "Проверьте данные критерия:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Описание: {description}\n"
            "Тип оценки: {evaluation_type_name}\n\n"
            "Всё верно?",
            when=lambda data, widget, manager: not data.get("is_editing", False),
        ),
        Format(
            "Проверьте изменения критерия:\n\n"
            "Название: {name}\n"
            "Код: {code}\n"
            "Описание: {description}\n"
            "Тип оценки: {evaluation_type_name}\n\n"
            "Сохранить изменения?",
            when="is_editing",
        ),
        Row(
            Button(
                text=Const("Подтвердить ✅"),
                id="confirm",
                on_click=on_confirm_criterion,
            ),
            SwitchTo(
                Const("Назад"),
                id="back_description_edit_window",
                state=CriterionDialog.edit_menu,
                when="is_editing",
            ),
            Back(
                Const("Назад"),
                when=lambda data, widget, manager: not data.get("is_editing", False),
            ),
        ),
        state=CriterionDialog.confirm,
        getter=get_criterion_form_data,
    )


def add_more_window():
    """Create add more window.

    Returns:
        Window: The configured add more window.
    """
    return Window(
        Const("Добавить еще один критерий?"),
        Row(
            Button(
                text=Const("Да ➕"),
                id="add_more_yes",
                on_click=on_add_more_yes,
            ),
            Button(
                text=Const("Нет, завершить ✅"),
                id="add_more_no",
                on_click=on_add_more_no,
            ),
        ),
        state=CriterionDialog.add_more,
    )
