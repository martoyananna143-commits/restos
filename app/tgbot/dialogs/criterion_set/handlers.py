"""Handlers for criterion set dialog."""

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.organization_service import OrganizationService
from app.tgbot.dialogs.criterion.states import CriterionDialog
from app.tgbot.dialogs.criterion_set.states import CriterionSetDialog
from app.tgbot.dialogs.greeting.states import GreetingDialog


async def on_create_new_set(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle create new set button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Очищаем данные предыдущего набора
    dialog_manager.dialog_data.pop("name", None)
    dialog_manager.dialog_data.pop("description", None)
    dialog_manager.dialog_data.pop("selected_criterion_ids", None)
    dialog_manager.dialog_data.pop("is_default", None)
    await dialog_manager.switch_to(CriterionSetDialog.name_input)


@inject
async def on_select_existing_set(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
):
    """Handle existing set selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected criterion set ID.
        criterion_set_service: CriterionSet service instance (injected).
    """
    criterion_set_id = int(item_id)

    criterion_set = await criterion_set_service.get_by_id(criterion_set_id)
    if criterion_set:
        dialog_manager.dialog_data["criterion_set_id"] = criterion_set_id
        dialog_manager.dialog_data["name"] = criterion_set.name
        dialog_manager.dialog_data["description"] = criterion_set.description
        dialog_manager.dialog_data["is_default"] = criterion_set.is_default
        dialog_manager.dialog_data["selected_criterion_ids"] = (
            criterion_set.criterion_ids or []
        )
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: набор критериев не найден")


async def process_name_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process name input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    if not message.text:
        await message.answer(
            "Название набора не может быть пустым. Попробуйте еще раз."
        )
        return

    name = message.text.strip()
    if not name:
        await message.answer(
            "Название набора не может быть пустым. Попробуйте еще раз."
        )
        return

    dialog_manager.dialog_data["name"] = name
    
    # Если редактируем существующий набор, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_set_id"):
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionSetDialog.description_input)


async def on_skip_description(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip description button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["description"] = None
    
    # Если редактируем существующий набор, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_set_id"):
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionSetDialog.select_criteria)


async def process_description_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process description input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    description = message.text.strip() if message.text else None
    dialog_manager.dialog_data["description"] = description if description else None
    
    # Если редактируем существующий набор, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_set_id"):
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionSetDialog.select_criteria)


@inject
async def on_create_new_criterion_from_set(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle create new criterion button click from criterion set dialog.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    from aiogram.types import Message as MessageType

    # Check administrator access
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id

    if telegram_id:
        organization_id = dialog_manager.dialog_data.get("organization_id")
        if not organization_id:
            organization = await organization_service.get_by_user_telegram_id(telegram_id)
            if organization:
                organization_id = organization.id
                dialog_manager.dialog_data["organization_id"] = organization_id
                dialog_manager.middleware_data["organization"] = organization

        if organization_id:
            employee = await employee_service.get_by_telegram_id_and_organization_id(
                telegram_id, organization_id
            )
            if employee:
                employee_type_code = employee.meta.get("employee_type_code")
                is_administrator = employee_type_code == "administrator"

                if not is_administrator:
                    if callback.message and isinstance(callback.message, MessageType):
                        await callback.message.answer(
                            "❌ У вас нет прав доступа для создания критериев. "
                            "Только администраторы могут создавать критерии."
                        )
                    return

        # Сохраняем состояние создания набора критериев для возврата
        criterion_set_state = {
            "organization_id": organization_id,
            "name": dialog_manager.dialog_data.get("name"),
            "description": dialog_manager.dialog_data.get("description"),
            "selected_criterion_ids": dialog_manager.dialog_data.get("selected_criterion_ids", []),
            "is_default": dialog_manager.dialog_data.get("is_default", False),
            "criterion_set_id": dialog_manager.dialog_data.get("criterion_set_id"),
        }
        dialog_manager.middleware_data["criterion_set_state"] = criterion_set_state
        dialog_manager.middleware_data["from_criterion_set"] = True  # Флаг для возврата

        # Пытаемся получить organization из БД, если organization_id не известен
        if not organization_id and telegram_id:
            from app.internal import Container as C
            user_svc = C.user_service()
            user = await user_svc.repository.get_by_telegram_id_any_chat(telegram_id)
            if user and getattr(user, "current_organization_id", None):
                org = await organization_service.get_by_id(int(user.current_organization_id))
                if org:
                    organization_id = org.id
            if not organization_id:
                org = await organization_service.get_by_user_telegram_id(telegram_id)
                if org:
                    organization_id = org.id

        if organization_id:
            organization = await organization_service.get_by_id(organization_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization
                dialog_manager.middleware_data["preset_organization_id"] = organization_id
                await dialog_manager.start(
                    CriterionDialog.select_value_type,
                    mode=StartMode.NORMAL,
                )
                dialog_manager.dialog_data["organization_id"] = organization_id
                dialog_manager.dialog_data.pop("criterion_id", None)
                dialog_manager.dialog_data.pop("name", None)
                dialog_manager.dialog_data.pop("code", None)
                dialog_manager.dialog_data.pop("description", None)
                dialog_manager.dialog_data.pop("value_type", None)
            else:
                await dialog_manager.start(
                    CriterionDialog.select_organization,
                    mode=StartMode.NORMAL,
                )
        else:
            await dialog_manager.start(
                CriterionDialog.select_organization,
                mode=StartMode.NORMAL,
            )
    else:
        await dialog_manager.start(
            CriterionDialog.select_organization,
            mode=StartMode.NORMAL,
        )


async def on_toggle_criterion(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    criterion_service: CriterionService = Provide[Container.criterion_service],
):
    """Handle criterion toggle (select/deselect).

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected criterion ID.
        criterion_service: Criterion service instance (injected).
    """
    criterion_id = int(item_id)

    selected_ids = dialog_manager.dialog_data.get("selected_criterion_ids", [])

    if criterion_id in selected_ids:
        selected_ids.remove(criterion_id)
    else:
        selected_ids.append(criterion_id)

    dialog_manager.dialog_data["selected_criterion_ids"] = selected_ids
    # Обновляем окно, чтобы показать изменения
    await dialog_manager.switch_to(CriterionSetDialog.select_criteria)


async def on_finish_criteria_selection(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle finish criteria selection button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    selected_ids = dialog_manager.dialog_data.get("selected_criterion_ids", [])

    if not selected_ids:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Выберите хотя бы один критерий для набора.")
        return

    # Если редактируем существующий набор, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_set_id"):
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionSetDialog.set_default)


async def on_set_default_yes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle set default yes button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["is_default"] = True
    
    # Если редактируем существующий набор, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_set_id"):
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionSetDialog.confirm)


async def on_set_default_no(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle set default no button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["is_default"] = False
    
    # Если редактируем существующий набор, возвращаемся в меню редактирования
    if dialog_manager.dialog_data.get("criterion_set_id"):
        await dialog_manager.switch_to(CriterionSetDialog.edit_menu)
    else:
        await dialog_manager.switch_to(CriterionSetDialog.confirm)


@inject
async def on_confirm_criterion_set(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
):
    """Handle confirm criterion set button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        criterion_set_service: CriterionSet service instance (injected).
    """
    data = dialog_manager.dialog_data

    organization_id = data.get("organization_id")
    if not organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
        return

    name = data.get("name", "").strip()
    if not name:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: название набора обязательно")
        await dialog_manager.switch_to(CriterionSetDialog.name_input)
        return

    selected_criterion_ids = data.get("selected_criterion_ids", [])
    if not selected_criterion_ids:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: выберите хотя бы один критерий")
        await dialog_manager.switch_to(CriterionSetDialog.select_criteria)
        return

    from app.infra.database.repository.criterion_set.dto import (
        CreateCriterionSetDTO,
        UpdateCriterionSetDTO,
    )

    criterion_set_id = data.get("criterion_set_id")

    try:
        if criterion_set_id:
            # Обновляем существующий набор
            update_dto = UpdateCriterionSetDTO(
                name=name,
                description=data.get("description"),
                is_default=data.get("is_default", False),
                criterion_ids=selected_criterion_ids,
            )
            criterion_set = await criterion_set_service.update(
                criterion_set_id, update_dto
            )
            if criterion_set:
                await callback.answer(
                    f"Набор критериев '{criterion_set.name}' успешно обновлен!",
                )
        else:
            # Создаем новый набор
            create_dto = CreateCriterionSetDTO(
                organization_id=organization_id,
                name=name,
                description=data.get("description"),
                is_default=data.get("is_default", False),
                criterion_ids=selected_criterion_ids,
            )
            criterion_set = await criterion_set_service.create(create_dto)
            await callback.answer(
                f"Набор критериев '{criterion_set.name}' успешно создан!",
            )
    except Exception as e:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                f"Ошибка при сохранении набора критериев: {str(e)}"
            )
        return

    # Проверяем, пришли ли мы из evaluation
    from_evaluation = dialog_manager.middleware_data.get("from_evaluation", False)
    if from_evaluation:
        # Возвращаемся в evaluation dialog
        from app.tgbot.dialogs.evaluation.states import EvaluationDialog
        
        # Восстанавливаем состояние оценки
        evaluation_state = dialog_manager.middleware_data.get("evaluation_state", {})
        if evaluation_state:
            dialog_manager.dialog_data["organization_id"] = evaluation_state.get("organization_id")
            dialog_manager.dialog_data["evaluation_type_name"] = evaluation_state.get("evaluation_type_name")
            dialog_manager.dialog_data["filled_by_employee_id"] = evaluation_state.get("filled_by_employee_id")
            dialog_manager.dialog_data["evaluated_employee_id"] = evaluation_state.get("evaluated_employee_id")
        
        # Используем созданный набор критериев
        if criterion_set:
            dialog_manager.dialog_data["criterion_set_id"] = criterion_set.id
        
        # Очищаем флаг
        dialog_manager.middleware_data.pop("from_evaluation", None)
        dialog_manager.middleware_data.pop("evaluation_state", None)
        
        # Переходим к выбору набора критериев (теперь он будет виден в списке)
        await dialog_manager.start(
            EvaluationDialog.select_criterion_set,
            mode=StartMode.NORMAL,
        )
    else:
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )


async def on_back_from_criterion_set_creation(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle back button click from criterion set creation (when coming from evaluation).

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    # Проверяем, пришли ли мы из evaluation
    from_evaluation = dialog_manager.middleware_data.get("from_evaluation", False)
    if from_evaluation:
        # Возвращаемся в evaluation dialog
        from app.tgbot.dialogs.evaluation.states import EvaluationDialog
        
        # Восстанавливаем состояние оценки
        evaluation_state = dialog_manager.middleware_data.get("evaluation_state", {})
        if evaluation_state:
            dialog_manager.dialog_data["organization_id"] = evaluation_state.get("organization_id")
            dialog_manager.dialog_data["evaluation_type_name"] = evaluation_state.get("evaluation_type_name")
            dialog_manager.dialog_data["filled_by_employee_id"] = evaluation_state.get("filled_by_employee_id")
            dialog_manager.dialog_data["evaluated_employee_id"] = evaluation_state.get("evaluated_employee_id")
        
        # Очищаем флаг
        dialog_manager.middleware_data.pop("from_evaluation", None)
        dialog_manager.middleware_data.pop("evaluation_state", None)
        
        # Переходим к выбору набора критериев
        await dialog_manager.start(
            EvaluationDialog.select_criterion_set,
            mode=StartMode.NORMAL,
        )
    else:
        # Обычный возврат назад
        await dialog_manager.switch_to(CriterionSetDialog.select_set)


async def on_cancel_criterion_set(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle cancel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await callback.answer("Создание набора критериев отменено")

    await dialog_manager.done()


# Edit menu handlers
async def on_edit_name(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit name button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionSetDialog.name_input)


async def on_edit_description(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit description button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionSetDialog.description_input)


async def on_edit_criteria(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit criteria button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionSetDialog.select_criteria)


async def on_edit_default_status(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle edit default status button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionSetDialog.set_default)


async def on_save_changes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle save changes button click - goes to confirm window.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionSetDialog.confirm)


async def on_upload_excel_clicked(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle upload Excel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(CriterionSetDialog.upload_excel)


@inject
async def process_excel_upload(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    criterion_service: CriterionService = Provide[Container.criterion_service],
    criterion_set_service: CriterionSetService = Provide[Container.criterion_set_service],
):
    """Process Excel file upload for importing criteria and sets.

    File format (4 columns):
        Col 1: Combined set name
        Col 2: Sub-set name
        Col 3: Criterion question
        Col 4: Criterion type (bool, str, num)

    Creates sub-sets with their criteria, then a combined set that
    contains all criteria from all sub-sets in file order.
    """
    import logging
    import tempfile
    from collections import OrderedDict
    from pathlib import Path

    logger = logging.getLogger(__name__)

    # --- Validate document ---------------------------------------------------
    if not message.document:
        await message.answer(
            "❌ Пожалуйста, отправьте Excel файл (.xlsx).\n\n"
            "Формат файла (4 колонки):\n"
            "• Колонка A: Название объединённого набора\n"
            "• Колонка B: Название субнабора критериев\n"
            "• Колонка C: Вопрос/название критерия\n"
            "• Колонка D: Тип данных (bool, str, num)\n\n"
            "Поддерживаемые типы:\n"
            "• Да/Нет, bool, boolean — для ответов Да/Нет\n"
            "• Текст, str, string — для текстовых ответов\n"
            "• Число, num, number, оценка — для числовых ответов"
        )
        return

    file_name = message.document.file_name or ""
    if not file_name.lower().endswith((".xlsx", ".xls")):
        await message.answer(
            "❌ Неверный формат файла. Пожалуйста, отправьте Excel файл (.xlsx или .xls)."
        )
        return

    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
        else:
            await message.answer("❌ Ошибка: организация не найдена")
            return

    # --- Type helpers --------------------------------------------------------
    _TYPE_MAPPING: dict[str, str] = {
        # English
        "boolean": "bool", "bool": "bool",
        "string": "str", "str": "str", "text": "str",
        "number": "num", "num": "num", "numeric": "num",
        "integer": "num", "int": "num", "float": "num",
        # Russian
        "да/нет": "bool", "да нет": "bool", "логический": "bool", "булевый": "bool",
        "текст": "str", "строка": "str", "текстовый": "str",
        "число": "num", "числовой": "num", "цифра": "num", "оценка": "num",
    }
    _TYPE_TO_DB: dict[str, str] = {
        "bool": "boolean", "str": "string", "num": "number",
        "boolean": "boolean", "string": "string", "number": "number",
    }
    _VALID_TYPES = set(_TYPE_MAPPING.keys())
    _HEADER_KW = [
        "название", "набор", "вопрос", "критерий", "тип",
        "name", "question", "type", "set", "категория", "раздел", "субнабор",
    ]

    NUM_COLUMNS = 4  # combined_set | sub_set | question | type

    # --- Read rows -----------------------------------------------------------
    tmp_path = None
    rows_data: list[list[str]] = []

    try:
        bot = dialog_manager.middleware_data.get("bot")
        if not bot:
            await message.answer("❌ Ошибка: бот не найден")
            return

        file_info = await bot.get_file(message.document.file_id)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = Path(tmp_file.name)
        await bot.download_file(file_info.file_path, str(tmp_path))

        # METHOD 1: raw ZIP/XML (faster, no style issues)
        try:
            import zipfile
            import xml.etree.ElementTree as ET

            logger.info("Reading Excel as ZIP…")
            with zipfile.ZipFile(tmp_path, "r") as zf:
                shared_strings: list[str] = []
                try:
                    with zf.open("xl/sharedStrings.xml") as f:
                        tree = ET.parse(f)
                        ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                        for si in tree.getroot().findall(".//x:si", ns):
                            t = si.find(".//x:t", ns)
                            shared_strings.append(t.text if t is not None and t.text else "")
                except KeyError:
                    pass

                with zf.open("xl/worksheets/sheet1.xml") as f:
                    tree = ET.parse(f)
                    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    for row in tree.getroot().findall(".//x:row", ns):
                        cells: dict[int, str] = {}
                        for cell in row.findall(".//x:c", ns):
                            ref = cell.get("r")
                            if not ref:
                                continue
                            col_num = 0
                            for ch in ref:
                                if ch.isalpha():
                                    col_num = col_num * 26 + (ord(ch.upper()) - ord("A") + 1)
                                else:
                                    break
                            col_num -= 1

                            v = cell.find("x:v", ns)
                            val = ""
                            if v is not None and v.text:
                                if cell.get("t") == "s":
                                    idx = int(v.text)
                                    val = shared_strings[idx] if idx < len(shared_strings) else ""
                                else:
                                    val = v.text
                            cells[col_num] = val

                        row_vals = [cells.get(i, "") for i in range(NUM_COLUMNS)]
                        rows_data.append(row_vals)

            logger.info("ZIP method OK, %d raw rows", len(rows_data))

        except Exception as zip_err:
            logger.warning("ZIP method failed: %s", zip_err, exc_info=True)
            # METHOD 2: openpyxl
            try:
                from openpyxl import load_workbook  # type: ignore

                logger.info("Trying openpyxl read_only…")
                wb = load_workbook(tmp_path, read_only=True, data_only=True)
                ws = wb.active
                for row_tuple in ws.iter_rows(values_only=True):
                    vals = list(row_tuple) + [""] * NUM_COLUMNS
                    rows_data.append([str(v).strip() if v else "" for v in vals[:NUM_COLUMNS]])
                wb.close()
                logger.info("openpyxl OK, %d raw rows", len(rows_data))
            except Exception as opx_err:
                logger.error("All read methods failed: %s", opx_err, exc_info=True)
                await message.answer(
                    "❌ Не удалось прочитать Excel файл.\n\n"
                    "Попробуйте:\n"
                    "1. Создать новый Excel файл\n"
                    "2. Скопировать туда только данные (без форматирования)\n"
                    "3. Сохранить как .xlsx"
                )
                return

        # --- Skip header row -------------------------------------------------
        start_idx = 0
        if rows_data:
            cols_lower = [str(c).lower().strip() for c in rows_data[0]]
            last_col = cols_lower[-1] if cols_lower else ""
            is_header = (
                (any(kw in cols_lower[0] for kw in _HEADER_KW)
                 and any(kw in cols_lower[1] for kw in _HEADER_KW))
                or (last_col and last_col not in _VALID_TYPES
                    and any(kw in last_col for kw in _HEADER_KW))
            )
            if is_header:
                start_idx = 1
                logger.info("Header detected, skipping row 1: %s", rows_data[0])

        # --- Parse rows into structured data ---------------------------------
        # combined_name -> OrderedDict[sub_name -> [(question, type_short), ...]]
        combined_sets: OrderedDict[str, OrderedDict[str, list[dict[str, str]]]] = OrderedDict()
        # Global ordered list of all criteria (for combined sets, preserving file order)
        all_rows_ordered: list[dict[str, str]] = []  # {combined, sub, question, type}

        skipped = 0
        processed = 0
        for row_idx, rv in enumerate(rows_data[start_idx:], start=start_idx + 1):
            combined_name = str(rv[0]).strip() if rv[0] else ""
            sub_name = str(rv[1]).strip() if rv[1] else ""
            question = str(rv[2]).strip() if rv[2] else ""
            raw_type = str(rv[3]).strip().lower() if rv[3] else "bool"

            if not combined_name or not sub_name or not question:
                skipped += 1
                continue

            crit_type = _TYPE_MAPPING.get(raw_type, "bool")

            if combined_name not in combined_sets:
                combined_sets[combined_name] = OrderedDict()
            if sub_name not in combined_sets[combined_name]:
                combined_sets[combined_name][sub_name] = []

            entry = {"question": question, "type": crit_type}
            combined_sets[combined_name][sub_name].append(entry)
            all_rows_ordered.append({
                "combined": combined_name, "sub": sub_name,
                "question": question, "type": crit_type,
            })
            processed += 1

        logger.info(
            "Parsed %d data rows (%d skipped). Combined sets: %d",
            processed, skipped, len(combined_sets),
        )

        if not combined_sets:
            await message.answer(
                "❌ Файл не содержит данных или имеет неверный формат.\n\n"
                "Формат файла (4 колонки):\n"
                "• Колонка A: Название объединённого набора\n"
                "• Колонка B: Название субнабора критериев\n"
                "• Колонка C: Вопрос критерия\n"
                "• Колонка D: Тип критерия (bool, str, num)\n\n"
                "Первая строка может быть заголовком (пропускается автоматически)."
            )
            return

        # --- Create criteria & sets ------------------------------------------
        from app.infra.database.repository.criterion.dto import CreateCriterionDTO
        from app.infra.database.repository.criterion_set.dto import CreateCriterionSetDTO

        created_sets: list[str] = []
        created_criteria_count = 0
        failed_criteria: list[dict] = []
        global_sort_order = 0  # сквозной порядок по файлу

        for combined_name, sub_sets in combined_sets.items():
            # All criterion IDs for the combined set (in file order)
            combined_criterion_ids: list[int] = []

            for sub_name, criteria_list in sub_sets.items():
                sub_criterion_ids: list[int] = []

                for idx, crit in enumerate(criteria_list):
                    try:
                        db_type = _TYPE_TO_DB.get(crit["type"], "boolean")
                        code = (
                            f"{sub_name.lower().replace(' ', '_')}"
                            f"_{idx + 1}_{crit['type']}"
                        )
                        dto = CreateCriterionDTO(
                            organization_id=organization_id,
                            name=crit["question"],
                            code=code,
                            value_type=db_type,
                            description=None,
                            sort_order=global_sort_order,
                        )
                        criterion = await criterion_service.create(dto)
                        sub_criterion_ids.append(criterion.id)
                        combined_criterion_ids.append(criterion.id)
                        created_criteria_count += 1
                        global_sort_order += 1
                    except Exception as e:
                        logger.error("Criterion create error: %s", e, exc_info=True)
                        failed_criteria.append({
                            "set_name": sub_name,
                            "question": crit.get("question", "?"),
                            "error": str(e),
                        })

                # Create sub-set
                if sub_criterion_ids:
                    try:
                        sub_dto = CreateCriterionSetDTO(
                            organization_id=organization_id,
                            name=sub_name,
                            description=f"Субнабор из «{combined_name}»",
                            is_default=False,
                            criterion_ids=sub_criterion_ids,
                        )
                        await criterion_set_service.create(sub_dto)
                        created_sets.append(sub_name)
                    except Exception as e:
                        logger.error("Sub-set create error (%s): %s", sub_name, e, exc_info=True)

            # Create combined set (contains all sub-sets' criteria in file order)
            if combined_criterion_ids:
                try:
                    combined_dto = CreateCriterionSetDTO(
                        organization_id=organization_id,
                        name=combined_name,
                        description=(
                            f"Объединённый набор из: "
                            f"{', '.join(sub_sets.keys())}"
                        ),
                        is_default=False,
                        criterion_ids=combined_criterion_ids,
                    )
                    await criterion_set_service.create(combined_dto)
                    created_sets.append(combined_name)
                except Exception as e:
                    logger.error(
                        "Combined set create error (%s): %s",
                        combined_name, e, exc_info=True,
                    )

        # --- Result message --------------------------------------------------
        if created_sets:
            msg = (
                "✅ Импорт завершён успешно!\n\n"
                f"Создано наборов: {len(created_sets)}\n"
                f"Создано критериев: {created_criteria_count}\n\n"
                "Наборы:\n"
            )
            for sn in created_sets:
                msg += f"• {sn}\n"
            if failed_criteria:
                msg += (
                    f"\n⚠️ Не удалось создать {len(failed_criteria)} критериев. "
                    "Проверьте логи для деталей."
                )
            await message.answer(msg)
            await dialog_manager.switch_to(CriterionSetDialog.select_set)
        else:
            await message.answer(
                "❌ Не удалось создать наборы критериев. "
                "Проверьте формат файла и попробуйте снова."
            )

    except Exception as e:
        logger.error("Unexpected error: %s", e, exc_info=True)
        await message.answer(f"❌ Неожиданная ошибка: {str(e)}")
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception as err:
                logger.warning("Could not delete temp file: %s", err)


@inject
async def on_open_criteria_select_webapp(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Open criteria multi-select in Telegram Mini Web App."""
    from app.tgbot.webapp_helper import generate_page_url, send_webapp_or_link

    telegram_id = callback.from_user.id if callback.from_user else None
    if not telegram_id:
        return

    organization = dialog_manager.middleware_data.get("organization")
    if not organization and telegram_id:
        org_id = dialog_manager.dialog_data.get("organization_id")
        if org_id:
            organization = await organization_service.get_by_id(org_id)

    if not organization:
        if callback.message and isinstance(callback.message, Message):
            await callback.message.answer("Организация не найдена.")
        return

    set_id = dialog_manager.dialog_data.get("criterion_set_id")
    url = generate_page_url(
        "criteria_select",
        organization.id,
        telegram_id,
        extra={"criterion_set_id": set_id},
    )

    await send_webapp_or_link(
        message=callback.message,
        url=url,
        text="📋 <b>Выбор критериев</b>\n\nОткройте Mini App для удобного выбора критериев с чекбоксами:",
        button_text="📋 Выбрать критерии (Mini App)",
    )
    await callback.answer()
