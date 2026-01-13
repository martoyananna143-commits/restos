"""Handlers for criterion set dialog."""

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.criterion_set_service import CriterionSetService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.evaluation_type_service import EvaluationTypeService
from app.internal.usecases.organization_service import OrganizationService
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

        # Запускаем диалог создания критерия
        if organization_id:
            organization = await organization_service.get_by_id(organization_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization
                dialog_manager.middleware_data["preset_organization_id"] = organization_id
                # Запускаем диалог с окна выбора типа данных (создание нового критерия)
                await dialog_manager.start(
                    CriterionDialog.select_value_type,
                    mode=StartMode.NORMAL,
                )
                # Устанавливаем organization_id в dialog_data после старта диалога
                dialog_manager.dialog_data["organization_id"] = organization_id
                # Очищаем данные предыдущего критерия
                dialog_manager.dialog_data.pop("criterion_id", None)
                dialog_manager.dialog_data.pop("name", None)
                dialog_manager.dialog_data.pop("code", None)
                dialog_manager.dialog_data.pop("description", None)
                dialog_manager.dialog_data.pop("value_type", None)
            else:
                # Если организация не найдена, запускаем с выбора организации
                await dialog_manager.start(
                    CriterionDialog.select_organization,
                    mode=StartMode.NORMAL,
                )
        else:
            # Если organization_id не известен, запускаем с выбора организации
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
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
):
    """Process Excel file upload for importing criteria and sets.

    Args:
        message: Message object with document.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
        criterion_service: Criterion service instance (injected).
        criterion_set_service: CriterionSet service instance (injected).
        evaluation_type_service: EvaluationType service instance (injected).
    """
    import logging
    import tempfile
    from pathlib import Path

    from openpyxl import load_workbook  # type: ignore

    logger = logging.getLogger(__name__)

    # Проверяем наличие документа
    if not message.document:
        await message.answer(
            "❌ Пожалуйста, отправьте Excel файл (.xlsx).\n\n"
            "Формат файла:\n"
            "• Колонка 1: Название набора критериев\n"
            "• Колонка 2: Вопрос критерия\n"
            "• Колонка 3: Тип критерия (bool, str, num)"
        )
        return

    # Проверяем расширение файла
    file_name = message.document.file_name or ""
    if not file_name.lower().endswith((".xlsx", ".xls")):
        await message.answer(
            "❌ Неверный формат файла. Пожалуйста, отправьте Excel файл (.xlsx или .xls)."
        )
        return

    # Получаем organization_id
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
        else:
            await message.answer("❌ Ошибка: организация не найдена")
            return

    # Получаем все существующие evaluation_types для проверки
    evaluation_types = await evaluation_type_service.get_all()
    evaluation_types_by_name = {et.name: et for et in evaluation_types}
    evaluation_types_by_code = {et.code: et for et in evaluation_types}

    tmp_path = None
    sets_data: dict[str, list[dict[str, str]]] = {}

    try:
        # Скачиваем файл
        bot = dialog_manager.middleware_data.get("bot")
        if not bot:
            await message.answer("❌ Ошибка: бот не найден")
            return

        file_info = await bot.get_file(message.document.file_id)
        file_path = file_info.file_path

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp_file:
            tmp_path = Path(tmp_file.name)

        await bot.download_file(file_path, str(tmp_path))

        # МЕТОД 1: Чтение напрямую из ZIP (Excel это ZIP архив)
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            
            logger.info("Attempting to read Excel as ZIP...")
            
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                # Читаем shared strings (текстовые значения)
                shared_strings = []
                try:
                    with zip_ref.open('xl/sharedStrings.xml') as f:
                        tree = ET.parse(f)
                        root = tree.getroot()
                        ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                        for si in root.findall('.//x:si', ns):
                            t = si.find('.//x:t', ns)
                            if t is not None and t.text:
                                shared_strings.append(t.text)
                except KeyError:
                    logger.warning("No sharedStrings.xml found")
                
                # Читаем первый лист
                with zip_ref.open('xl/worksheets/sheet1.xml') as f:
                    tree = ET.parse(f)
                    root = tree.getroot()
                    ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                    
                    rows_data = []
                    for row in root.findall('.//x:row', ns):
                        # Собираем ячейки с их координатами
                        cells_dict = {}
                        for cell in row.findall('.//x:c', ns):
                            cell_ref = cell.get('r')  # Например, "A1", "B1", "C1"
                            if not cell_ref:
                                continue
                            
                            # Извлекаем номер колонки из координаты (A=0, B=1, C=2, ...)
                            col_letter = ''.join([c for c in cell_ref if c.isalpha()])
                            col_num = 0
                            for char in col_letter:
                                col_num = col_num * 26 + (ord(char.upper()) - ord('A') + 1)
                            col_num -= 1  # A=0, B=1, C=2, ...
                            
                            v = cell.find('x:v', ns)
                            t_attr = cell.get('t')
                            
                            cell_value = ''
                            if v is not None and v.text:
                                if t_attr == 's':  # Shared string reference
                                    idx = int(v.text)
                                    if idx < len(shared_strings):
                                        cell_value = shared_strings[idx]
                                else:
                                    cell_value = v.text
                            
                            cells_dict[col_num] = cell_value
                        
                        # Создаем список значений ячеек в правильном порядке (первые 3 колонки)
                        row_data = []
                        for col_idx in range(3):  # Нужны только первые 3 колонки
                            row_data.append(cells_dict.get(col_idx, ''))
                        
                        if len(row_data) >= 3:
                            rows_data.append(row_data)
                    
                    # Проверяем заголовок - более строгая проверка
                    # Заголовок определяется как строка, где все три колонки содержат ключевые слова заголовка
                    # ИЛИ где тип (третья колонка) не является валидным типом данных
                    start_idx = 0
                    if rows_data and len(rows_data[0]) >= 3:
                        first_row = rows_data[0]
                        first_col = str(first_row[0]).lower().strip() if first_row[0] else ""
                        second_col = str(first_row[1]).lower().strip() if first_row[1] else ""
                        third_col = str(first_row[2]).lower().strip() if first_row[2] else ""
                        
                        # Проверяем, является ли это заголовком:
                        # 1. Все три колонки содержат ключевые слова заголовка
                        # 2. ИЛИ третья колонка не является валидным типом (bool/str/num/boolean/string/number)
                        header_keywords = ["название", "набор", "вопрос", "критерий", "тип", "name", "question", "type", "set"]
                        valid_types = ["bool", "str", "num", "boolean", "string", "number"]
                        
                        is_header = (
                            (any(kw in first_col for kw in header_keywords) and 
                             any(kw in second_col for kw in header_keywords) and 
                             any(kw in third_col for kw in header_keywords)) or
                            (third_col and third_col not in valid_types and 
                             any(kw in third_col for kw in header_keywords))
                        )
                        
                        if is_header:
                            start_idx = 1
                            logger.info(f"Header row detected, skipping. First row: {first_row}")
                        else:
                            logger.info(f"No header detected, processing from first row. First row: {first_row}")
                    
                    # Парсим данные
                    logger.info(f"Total rows read: {len(rows_data)}, start_idx: {start_idx}, will process {len(rows_data) - start_idx} rows")
                    skipped_rows = 0
                    processed_rows = 0
                    for row_idx, row_data in enumerate(rows_data[start_idx:], start=start_idx + 1):
                        logger.info(f"Processing row {row_idx}: raw_data={row_data}")
                        
                        if len(row_data) < 3:
                            logger.warning(f"Row {row_idx} has less than 3 columns: {row_data}")
                            continue
                        
                        set_name = str(row_data[0]).strip() if row_data[0] else ""
                        criterion_question = str(row_data[1]).strip() if row_data[1] else ""
                        criterion_type = str(row_data[2]).strip().lower() if row_data[2] else "bool"
                        
                        logger.debug(f"Row {row_idx} parsed: set_name='{set_name}', question='{criterion_question}', type='{criterion_type}'")
                        
                        if not set_name or not criterion_question:
                            skipped_rows += 1
                            logger.warning(f"Skipping empty row {row_idx}: set_name='{set_name}', question='{criterion_question}'")
                            continue
                        
                        # Нормализация и валидация типа (поддерживаем старые и новые названия)
                        type_mapping = {
                            "boolean": "bool", "bool": "bool",
                            "string": "str", "str": "str",
                            "number": "num", "num": "num"
                        }
                        criterion_type = type_mapping.get(criterion_type, "bool")
                        
                        if set_name not in sets_data:
                            sets_data[set_name] = []
                        
                        sets_data[set_name].append({
                            "question": criterion_question,
                            "type": criterion_type,
                        })
                        processed_rows += 1
                        logger.debug(f"Processed row: set='{set_name}', question='{criterion_question}', type='{criterion_type}'")
            
            logger.info(f"Successfully loaded Excel as ZIP. Processed {processed_rows} rows, skipped {skipped_rows} empty rows, found {len(sets_data)} sets")
            # Логируем детали для отладки
            for set_name, criteria_list in sets_data.items():
                logger.info(f"Set '{set_name}': {len(criteria_list)} criteria")
                for idx, crit in enumerate(criteria_list):
                    logger.info(f"  [{idx + 1}] {crit['question']} ({crit['type']})")
            
        except Exception as zip_error:
            logger.warning(f"ZIP method failed: {zip_error}", exc_info=True)
            
            # МЕТОД 2: Попытка с openpyxl в read_only режиме (игнорирует стили)
            try:
                logger.info("Attempting with openpyxl read_only mode...")
                wb = load_workbook(tmp_path, read_only=True, data_only=True)
                ws = wb.active
                
                rows_list = list(ws.iter_rows(values_only=True))
                
                start_idx = 0
                if rows_list and len(rows_list[0]) >= 3:
                    first_row = rows_list[0]
                    first_col = str(first_row[0]).lower().strip() if first_row[0] else ""
                    second_col = str(first_row[1]).lower().strip() if first_row[1] else ""
                    third_col = str(first_row[2]).lower().strip() if first_row[2] else ""
                    
                    # Проверяем, является ли это заголовком:
                    # 1. Все три колонки содержат ключевые слова заголовка
                    # 2. ИЛИ третья колонка не является валидным типом (bool/str/num/boolean/string/number)
                    header_keywords = ["название", "набор", "вопрос", "критерий", "тип", "name", "question", "type", "set"]
                    valid_types = ["bool", "str", "num", "boolean", "string", "number"]
                    
                    is_header = (
                        (any(kw in first_col for kw in header_keywords) and 
                         any(kw in second_col for kw in header_keywords) and 
                         any(kw in third_col for kw in header_keywords)) or
                        (third_col and third_col not in valid_types and 
                         any(kw in third_col for kw in header_keywords))
                    )
                    
                    if is_header:
                        start_idx = 1
                        logger.info(f"Header row detected, skipping. First row: {first_row}")
                    else:
                        logger.info(f"No header detected, processing from first row. First row: {first_row}")
                
                skipped_rows = 0
                processed_rows = 0
                for row_data in rows_list[start_idx:]:
                    if len(row_data) < 3:
                        continue
                    
                    set_name = str(row_data[0]).strip() if row_data[0] else ""
                    criterion_question = str(row_data[1]).strip() if row_data[1] else ""
                    criterion_type = str(row_data[2]).strip().lower() if row_data[2] else "bool"
                    
                    if not set_name or not criterion_question:
                        skipped_rows += 1
                        logger.debug(f"Skipping empty row: set_name='{set_name}', question='{criterion_question}'")
                        continue
                    
                    # Нормализация и валидация типа (поддерживаем старые и новые названия)
                    type_mapping = {
                        "boolean": "bool", "bool": "bool",
                        "string": "str", "str": "str",
                        "number": "num", "num": "num"
                    }
                    criterion_type = type_mapping.get(criterion_type, "bool")
                    
                    if set_name not in sets_data:
                        sets_data[set_name] = []
                    
                    sets_data[set_name].append({
                        "question": criterion_question,
                        "type": criterion_type,
                    })
                    processed_rows += 1
                    logger.debug(f"Processed row: set='{set_name}', question='{criterion_question}', type='{criterion_type}'")
                
                wb.close()
                logger.info(f"Successfully loaded with openpyxl. Processed {processed_rows} rows, skipped {skipped_rows} empty rows, found {len(sets_data)} sets")
                # Логируем детали для отладки
                for set_name, criteria_list in sets_data.items():
                    logger.info(f"Set '{set_name}': {len(criteria_list)} criteria")
                    for idx, crit in enumerate(criteria_list):
                        logger.info(f"  [{idx + 1}] {crit['question']} ({crit['type']})")
                
            except Exception as openpyxl_error:
                logger.error(f"All methods failed: {openpyxl_error}", exc_info=True)
                await message.answer(
                    "❌ Не удалось прочитать Excel файл.\n\n"
                    "Попробуйте:\n"
                    "1. Создать новый Excel файл\n"
                    "2. Скопировать туда только данные (без форматирования)\n"
                    "3. Сохранить как .xlsx\n"
                    "4. ИЛИ сохранить как .csv и отправить CSV файл"
                )
                if tmp_path and tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
                return

        # Проверка данных
        if not sets_data:
            await message.answer(
                "❌ Файл не содержит данных или имеет неверный формат.\n\n"
                "Формат файла (3 колонки):\n"
                "• Колонка 1: Название набора критериев\n"
                "• Колонка 2: Вопрос критерия\n"
                "• Колонка 3: Тип критерия (bool, str, num)"
            )
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            return


        # Создаем критерии и наборы
        created_sets = []
        created_criteria_count = 0
        failed_criteria = []
        created_evaluation_types = []  # Для отслеживания созданных типов оценки

        logger.info(f"Starting to create criteria from {len(sets_data)} sets")
        for set_name, criteria_list in sets_data.items():
            logger.info(f"Processing set '{set_name}' with {len(criteria_list)} criteria")
            
            # Проверяем/создаем evaluation_type на основе названия набора
            evaluation_type_id = None
            evaluation_type_name = set_name  # Используем название набора как название типа оценки
            
            # Генерируем code из name: lowercase, замена пробелов на подчеркивания, удаление спецсимволов
            import re
            evaluation_type_code = re.sub(r'[^a-zа-яё0-9_]', '', evaluation_type_name.lower().replace(' ', '_'))
            # Убираем множественные подчеркивания
            evaluation_type_code = re.sub(r'_+', '_', evaluation_type_code).strip('_')
            # Если code пустой, используем дефолтный
            if not evaluation_type_code:
                evaluation_type_code = f"evaluation_type_{len(evaluation_types_by_code) + 1}"
            
            # Проверяем, существует ли evaluation_type с таким именем
            if evaluation_type_name in evaluation_types_by_name:
                evaluation_type_id = evaluation_types_by_name[evaluation_type_name].id
                logger.info(f"Using existing evaluation_type '{evaluation_type_name}' (id={evaluation_type_id})")
            else:
                # Проверяем, существует ли evaluation_type с таким code
                if evaluation_type_code in evaluation_types_by_code:
                    # Если code уже существует, добавляем суффикс
                    counter = 1
                    original_code = evaluation_type_code
                    while evaluation_type_code in evaluation_types_by_code:
                        evaluation_type_code = f"{original_code}_{counter}"
                        counter += 1
                
                # Создаем новый evaluation_type
                try:
                    from app.infra.database.repository.evaluation_type.dto import (
                        CreateEvaluationTypeDTO,
                    )
                    
                    create_evaluation_type_dto = CreateEvaluationTypeDTO(
                        name=evaluation_type_name,
                        code=evaluation_type_code,
                        description=f"Автоматически создан при импорте набора критериев '{set_name}' из Excel",
                    )
                    
                    logger.info(f"Creating evaluation_type: name='{evaluation_type_name}', code='{evaluation_type_code}'")
                    evaluation_type = await evaluation_type_service.create(create_evaluation_type_dto)
                    evaluation_type_id = evaluation_type.id
                    
                    # Обновляем кэш
                    evaluation_types_by_name[evaluation_type_name] = evaluation_type
                    evaluation_types_by_code[evaluation_type_code] = evaluation_type
                    created_evaluation_types.append(evaluation_type_name)
                    logger.info(f"Successfully created evaluation_type '{evaluation_type_name}' (id={evaluation_type_id})")
                    
                except Exception as e:
                    logger.error(f"Error creating evaluation_type '{evaluation_type_name}': {e}", exc_info=True)
                    # Если не удалось создать, используем первый доступный или пропускаем набор
                    if evaluation_types:
                        evaluation_type_id = evaluation_types[0].id
                        logger.warning(f"Using fallback evaluation_type (id={evaluation_type_id})")
                    else:
                        logger.error(f"Cannot create evaluation_type and no fallback available. Skipping set '{set_name}'")
                        continue
            
            criterion_ids = []

            # Создаем критерии для этого набора
            for idx, criterion_data in enumerate(criteria_list):
                try:
                    # Преобразуем сокращенный тип в полный для сохранения в базу
                    # Принимаем: bool, str, num
                    # Сохраняем: boolean, string, number
                    type_to_db_mapping = {
                        "bool": "boolean",
                        "str": "string",
                        "num": "number",
                        "boolean": "boolean",  # На случай если уже полный
                        "string": "string",
                        "number": "number",
                    }
                    db_value_type = type_to_db_mapping.get(criterion_data["type"], "boolean")
                    
                    # Генерируем уникальный код критерия (включаем тип для различения дубликатов)
                    # Используем тип в коде, чтобы различать критерии с одинаковыми вопросами
                    base_code = f"{set_name.lower().replace(' ', '_')}_{idx + 1}"
                    code = f"{base_code}_{criterion_data['type']}"

                    from app.infra.database.repository.criterion.dto import (
                        CreateCriterionDTO,
                    )

                    create_criterion_dto = CreateCriterionDTO(
                        organization_id=organization_id,
                        evaluation_type_id=evaluation_type_id,
                        name=criterion_data["question"],
                        code=code,
                        value_type=db_value_type,  # Сохраняем полное название
                        description=None,
                        sort_order=idx,
                    )

                    logger.info(f"Creating criterion {idx + 1}/{len(criteria_list)} for set '{set_name}': code={code}, name={criterion_data['question']}, type={criterion_data['type']} -> {db_value_type}")
                    criterion = await criterion_service.create(create_criterion_dto)
                    criterion_ids.append(criterion.id)
                    created_criteria_count += 1
                    logger.info(f"Successfully created criterion with id={criterion.id}")

                except Exception as e:
                    error_msg = f"Error creating criterion {idx + 1} for set '{set_name}': {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    failed_criteria.append({
                        "set_name": set_name,
                        "index": idx + 1,
                        "question": criterion_data.get("question", "unknown"),
                        "error": str(e)
                    })
                    continue
            
            logger.info(f"Set '{set_name}': created {len(criterion_ids)} out of {len(criteria_list)} criteria")

            if not criterion_ids:
                continue

            # Создаем набор критериев
            try:
                from app.infra.database.repository.criterion_set.dto import (
                    CreateCriterionSetDTO,
                )

                create_set_dto = CreateCriterionSetDTO(
                    organization_id=organization_id,
                    name=set_name,
                    description="Импортирован из Excel файла",
                    is_default=False,
                    criterion_ids=criterion_ids,
                )

                criterion_set = await criterion_set_service.create(create_set_dto)
                created_sets.append(criterion_set.name)

            except Exception as e:
                logger.error(f"Error creating criterion set: {e}", exc_info=True)
                continue

        # Формируем сообщение о результате
        if created_sets:
            result_message = "✅ Импорт завершен успешно!\n\n"
            
            if created_evaluation_types:
                result_message += f"Создано типов оценки: {len(created_evaluation_types)}\n"
                for et_name in created_evaluation_types:
                    result_message += f"  • {et_name}\n"
                result_message += "\n"
            
            result_message += (
                f"Создано наборов: {len(created_sets)}\n"
                f"Создано критериев: {created_criteria_count}\n\n"
                f"Наборы:\n"
            )
            for set_name in created_sets:
                result_message += f"• {set_name}\n"
            
            if failed_criteria:
                result_message += f"\n⚠️ Не удалось создать {len(failed_criteria)} критериев. Проверьте логи для деталей."

            await message.answer(result_message)
            await dialog_manager.switch_to(CriterionSetDialog.select_set)
        else:
            await message.answer(
                "❌ Не удалось создать наборы критериев. "
                "Проверьте формат файла и попробуйте снова."
            )

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        await message.answer(f"❌ Неожиданная ошибка: {str(e)}")
    finally:
        # Cleanup
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except PermissionError:
                logger.warning(f"Could not delete temp file: {tmp_path}")
            except Exception as cleanup_error:
                logger.warning(f"Could not delete temp file: {cleanup_error}")
