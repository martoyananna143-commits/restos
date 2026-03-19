"""Handlers for evaluation dialog."""

from datetime import datetime

from aiogram import Bot
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.infra.database.repository.criterion_value.criterion_value_asyncpg import (
    CriterionValueRepositoryAsyncpg,
)
from app.infra.database.repository.criterion_value.dto import CreateCriterionValueDTO
from app.infra.database.repository.evaluation.dto import (
    CreateEvaluationDTO,
    UpdateEvaluationDTO,
)
from app.internal import Container
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.criterion_set_service import CriterionSetService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.evaluation_service import EvaluationService
from app.internal.usecases.organization_service import OrganizationService
from app.internal.usecases.excel_report_service import ExcelReportService
from app.internal.usecases.pdf_report_service import PDFReportService
from app.tgbot.dialogs.common.evaluation_type import (
    confirm_evaluation_type,
    process_evaluation_type_code_input as common_process_code,
    process_evaluation_type_description_input as common_process_description,
    process_evaluation_type_name_input as common_process_name,
    skip_evaluation_type_description as common_skip_description,
)
from app.tgbot.dialogs.evaluation.states import EvaluationDialog
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.dialogs.criterion_set.states import CriterionSetDialog
from app.tgbot.services import broadcaster


@inject
async def _on_evaluation_type_selected(
    evaluation_type, 
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Callback after evaluation type selection.

    Args:
        evaluation_type: Selected evaluation type.
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    dialog_manager.dialog_data["evaluation_type_name"] = evaluation_type.name
    
    # Check if user is administrator
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    
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
                
                # For non-administrators: automatically set filled_by_employee and skip organization/filled_by selection
                if not is_administrator:
                    dialog_manager.dialog_data["filled_by_employee_id"] = employee.id
                    dialog_manager.dialog_data["filled_by_employee_name"] = employee.full_name
                    await dialog_manager.switch_to(EvaluationDialog.select_evaluated_employee)
                    return True  # signal: we already switched, don't call switch_to(next_state)

    # For administrators: also try to skip org selection if org is already known
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if not organization:
            organization = await organization_service.get_by_id(organization_id)
            if organization:
                dialog_manager.middleware_data["organization"] = organization
        if organization:
            await dialog_manager.switch_to(EvaluationDialog.select_filled_by_employee)
            return True  # signal: we already switched


async def on_organization_window_start(
    organization,
    dialog_manager: DialogManager,
):
    """Callback after organization selection.

    Args:
        organization: Selected organization.
        dialog_manager: Dialog manager.
    """
    # Store organization in middleware data for use in other handlers
    dialog_manager.middleware_data["organization"] = organization


async def on_cancel_evaluation(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle cancel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await callback.answer("Создание замера отменено")

    await dialog_manager.done()


@inject
async def on_select_filled_by_employee_window_start(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Auto-skip filled by employee selection window if employee is already selected.
    
    Args:
        dialog_manager: Dialog manager.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    # Check if filled_by_employee is already set
    filled_by_employee_id = dialog_manager.dialog_data.get("filled_by_employee_id")
    if filled_by_employee_id:
        # Already set, skip this window
        await dialog_manager.switch_to(EvaluationDialog.select_evaluated_employee)
        return
    
    # If not set, try to auto-select for non-administrators
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            telegram_id = None
            if dialog_manager.event and dialog_manager.event.from_user:
                telegram_id = dialog_manager.event.from_user.id
            if telegram_id:
                organization = await organization_service.get_by_user_telegram_id(telegram_id)
                if organization:
                    organization_id = organization.id
                    dialog_manager.dialog_data["organization_id"] = organization_id
                    dialog_manager.middleware_data["organization"] = organization
    
    if organization_id:
        telegram_id = None
        if dialog_manager.event and dialog_manager.event.from_user:
            telegram_id = dialog_manager.event.from_user.id
        
        if telegram_id:
            employee = await employee_service.get_by_telegram_id_and_organization_id(
                telegram_id, organization_id
            )
            if employee:
                employee_type_code = employee.meta.get("employee_type_code")
                is_administrator = employee_type_code == "administrator"
                
                # Auto-select for non-administrators
                if not is_administrator:
                    dialog_manager.dialog_data["filled_by_employee_id"] = employee.id
                    dialog_manager.dialog_data["filled_by_employee_name"] = employee.full_name
                    # Skip this window
                    await dialog_manager.switch_to(EvaluationDialog.select_evaluated_employee)


@inject
async def on_select_filled_by_employee(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle filled by employee selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected employee ID.
        employee_service: Employee service instance (injected).
    """
    employee_id = int(item_id)

    employee = await employee_service.get_by_id(employee_id)
    if not employee:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: сотрудник не найден")
        return

    # Проверяем, что выбранный сотрудник принадлежит той же организации
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не выбрана")
        return

    if employee.organization_id != organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: выбранный сотрудник не принадлежит вашей организации. "
                "Выберите сотрудника из вашей организации."
            )
        return

    dialog_manager.dialog_data["filled_by_employee_id"] = employee_id
    dialog_manager.dialog_data["filled_by_employee_name"] = employee.full_name
    await dialog_manager.switch_to(EvaluationDialog.select_evaluated_employee)


@inject
async def on_select_evaluated_employee(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    employee_service: EmployeeService = Provide[Container.employee_service],
):
    """Handle evaluated employee selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected employee ID.
        employee_service: Employee service instance (injected).
    """
    employee_id = int(item_id)

    # Проверяем, что выбранный сотрудник не совпадает с заполняющим
    filled_by_employee_id = dialog_manager.dialog_data.get("filled_by_employee_id")
    if filled_by_employee_id and employee_id == filled_by_employee_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: нельзя оценивать самого себя. Выберите другого сотрудника."
            )
        return

    employee = await employee_service.get_by_id(employee_id)
    if not employee:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: сотрудник не найден")
        return

    # Проверяем, что выбранный сотрудник принадлежит той же организации
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не выбрана")
        return

    if employee.organization_id != organization_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: выбранный сотрудник не принадлежит вашей организации. "
                "Выберите сотрудника из вашей организации."
            )
        return

    dialog_manager.dialog_data["evaluated_employee_id"] = employee_id
    dialog_manager.dialog_data["evaluated_employee_name"] = employee.full_name
    # Проверяем наличие дефолтного набора критериев
    await dialog_manager.switch_to(EvaluationDialog.select_criterion_set)


@inject
async def on_use_default_criterion_set(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle use default criterion set button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        criterion_set_service: CriterionSet service instance (injected).
        criterion_service: Criterion service instance (injected).
        organization_service: Organization service instance (injected).
    """
    data = dialog_manager.dialog_data
    default_set_id = data.get("default_set_id")

    if not default_set_id:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: дефолтный набор не найден")
        return

    criterion_set = await criterion_set_service.get_by_id(default_set_id)
    if not criterion_set:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: набор критериев не найден")
        return

    # Get all organizations where user is a member
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id
    
    user_organization_ids = []
    if telegram_id:
        user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        user_organization_ids = [org.id for org in user_organizations]
        # Update dialog_data and middleware_data with first organization (for compatibility)
        if user_organizations:
            dialog_manager.dialog_data["organization_id"] = user_organizations[0].id
            dialog_manager.middleware_data["organization"] = user_organizations[0]
            dialog_manager.dialog_data["user_organization_ids"] = user_organization_ids
    
    # Проверяем, что набор критериев принадлежит одной из организаций пользователя
    if user_organization_ids and criterion_set.organization_id not in user_organization_ids:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: дефолтный набор критериев не принадлежит вашей организации."
            )
        return

    # Получаем критерии из набора
    criteria = await criterion_service.get_by_ids(criterion_set.criterion_ids or [])
    criteria_list = [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "value_type": c.value_type if hasattr(c, "value_type") and c.value_type else "boolean",  # По умолчанию boolean для обратной совместимости
        }
        for c in criteria
    ]

    data["criterion_set_id"] = default_set_id
    data["criteria"] = criteria_list
    data["current_question_index"] = 0
    data["criterion_answers"] = {}
    data["criterion_comments"] = {}

    await on_select_webform_method(callback, button, dialog_manager)


async def on_combine_criterion_sets(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle combine criterion sets button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    dialog_manager.dialog_data["selected_set_ids_for_combine"] = []
    await dialog_manager.switch_to(EvaluationDialog.combine_criterion_sets)


async def on_toggle_criterion_set_for_combine(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
):
    """Handle criterion set toggle for combining.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected criterion set ID.
    """
    criterion_set_id = int(item_id)

    selected_set_ids = dialog_manager.dialog_data.get(
        "selected_set_ids_for_combine", []
    )

    if criterion_set_id in selected_set_ids:
        selected_set_ids.remove(criterion_set_id)
    else:
        selected_set_ids.append(criterion_set_id)

    dialog_manager.dialog_data["selected_set_ids_for_combine"] = selected_set_ids
    # Обновляем окно, чтобы показать изменения
    await dialog_manager.switch_to(EvaluationDialog.combine_criterion_sets)


@inject
async def on_finish_combining_sets(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle finish combining sets button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        criterion_set_service: CriterionSet service instance (injected).
        criterion_service: Criterion service instance (injected).
        organization_service: Organization service instance (injected).
    """
    data = dialog_manager.dialog_data
    selected_set_ids = data.get("selected_set_ids_for_combine", [])

    if len(selected_set_ids) < 2:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Выберите минимум 2 набора для комбинирования."
            )
        return

    # Порядок критериев сохраняется в порядке выбора наборов
    all_criterion_ids: list[int] = []  # ordered, no duplicates
    seen_criterion_ids: set[int] = set()
    set_names = []

    # Get all organizations where user is a member
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id
    
    user_organization_ids = []
    if telegram_id:
        user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        user_organization_ids = [org.id for org in user_organizations]
        # Update dialog_data and middleware_data with first organization (for compatibility)
        if user_organizations:
            dialog_manager.dialog_data["organization_id"] = user_organizations[0].id
            dialog_manager.middleware_data["organization"] = user_organizations[0]
            dialog_manager.dialog_data["user_organization_ids"] = user_organization_ids
    
    if not user_organization_ids:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: организация не найдена")
        return

    data = dialog_manager.dialog_data
    for set_id in selected_set_ids:
        criterion_set = await criterion_set_service.get_by_id(set_id)
        if criterion_set:
            if criterion_set.organization_id not in user_organization_ids:
                from aiogram.types import Message as MessageType

                if callback.message and isinstance(callback.message, MessageType):
                    await callback.message.answer(
                        f"Ошибка: набор '{criterion_set.name}' не принадлежит вашей организации. "
                        "Выберите наборы из вашей организации."
                    )
                return
            set_names.append(criterion_set.name)
            if criterion_set.criterion_ids:
                for cid in criterion_set.criterion_ids:
                    if cid not in seen_criterion_ids:
                        seen_criterion_ids.add(cid)
                        all_criterion_ids.append(cid)

    if not all_criterion_ids:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: в выбранных наборах нет критериев.")
        return

    criteria = await criterion_service.get_by_ids(all_criterion_ids)
    # Сохраняем порядок в котором наборы были выбраны
    criteria_by_id = {c.id: c for c in criteria}
    criteria_ordered = [criteria_by_id[cid] for cid in all_criterion_ids if cid in criteria_by_id]
    criteria_list = [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "value_type": c.value_type if hasattr(c, "value_type") and c.value_type else "boolean",
        }
        for c in criteria_ordered
    ]

    # Формируем название комбинированного набора
    combined_set_name = f"Комбинированный: {', '.join(set_names)}"

    # Используем первую организацию пользователя для создания комбинированного набора
    primary_organization_id = user_organization_ids[0] if user_organization_ids else None
    
    if not primary_organization_id:
        from aiogram.types import Message as MessageType
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: не найдена организация для создания набора")
        return

    # Проверяем, существует ли уже набор с таким же названием и организацией
    existing_sets = await criterion_set_service.get_by_organization_id(primary_organization_id)
    existing_combined_set = None
    
    for existing_set in existing_sets:
        if existing_set.name == combined_set_name and existing_set.organization_id == primary_organization_id:
            existing_combined_set = existing_set
            break

    # Если набор существует, используем его, иначе создаем новый
    if existing_combined_set:
        criterion_set_id = existing_combined_set.id
    else:
        # Создаем новый комбинированный набор
        from app.infra.database.repository.criterion_set.dto import CreateCriterionSetDTO
        
        create_dto = CreateCriterionSetDTO(
            organization_id=primary_organization_id,
            name=combined_set_name,
            description=f"Автоматически созданный комбинированный набор из: {', '.join(set_names)}",
            is_default=False,
            is_active=True,
            criterion_ids=all_criterion_ids,
        )
        try:
            new_set = await criterion_set_service.create(create_dto)
            criterion_set_id = new_set.id
        except Exception as e:
            # Если произошла ошибка (например, набор уже существует из-за уникального ограничения),
            # перезапрашиваем список наборов и ищем существующий
            from aiogram.types import Message as MessageType
            
            # Перезапрашиваем список наборов на случай, если набор был создан параллельно
            updated_sets = await criterion_set_service.get_by_organization_id(primary_organization_id)
            found_set = None
            
            for existing_set in updated_sets:
                if existing_set.name == combined_set_name and existing_set.organization_id == primary_organization_id:
                    found_set = existing_set
                    break
            
            if found_set:
                criterion_set_id = found_set.id
            else:
                # Если не нашли, выводим ошибку
                if callback.message and isinstance(callback.message, MessageType):
                    await callback.message.answer(
                        f"Ошибка при создании комбинированного набора: {str(e)}"
                    )
                return

    data["criterion_set_id"] = criterion_set_id
    data["criteria"] = criteria_list
    data["current_question_index"] = 0
    data["criterion_answers"] = {}
    data["criterion_comments"] = {}
    data["combined_set_names"] = set_names  # Для отображения в отчете

    await callback.answer(
        f"Наборы '{', '.join(set_names)}' объединены. Всего критериев: {len(criteria_list)}",
    )

    await on_select_webform_method(callback, button, dialog_manager)


@inject
async def on_select_criterion_set(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle criterion set selection.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected criterion set ID.
        criterion_set_service: CriterionSet service instance (injected).
        criterion_service: Criterion service instance (injected).
        organization_service: Organization service instance (injected).
    """
    criterion_set_id = int(item_id)

    criterion_set = await criterion_set_service.get_by_id(criterion_set_id)
    if not criterion_set:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("Ошибка: набор критериев не найден")
        return

    # Get all organizations where user is a member
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id
    
    user_organization_ids = []
    if telegram_id:
        user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        user_organization_ids = [org.id for org in user_organizations]
        # Update dialog_data and middleware_data with first organization (for compatibility)
        if user_organizations:
            dialog_manager.dialog_data["organization_id"] = user_organizations[0].id
            dialog_manager.middleware_data["organization"] = user_organizations[0]
            dialog_manager.dialog_data["user_organization_ids"] = user_organization_ids
    
    # Проверяем, что набор критериев принадлежит одной из организаций пользователя
    if user_organization_ids and criterion_set.organization_id not in user_organization_ids:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "Ошибка: выбранный набор критериев не принадлежит вашей организации. "
                "Выберите набор из вашей организации."
            )
        return

    # Получаем критерии из набора
    import logging
    logger = logging.getLogger(__name__)
    
    data = dialog_manager.dialog_data
    criterion_ids = criterion_set.criterion_ids or []
    logger.info(f"on_select_criterion_set: criterion_set_id={criterion_set_id}, criterion_ids={criterion_ids}, len={len(criterion_ids)}")
    
    criteria = await criterion_service.get_by_ids(criterion_ids)
    logger.info(f"on_select_criterion_set: loaded {len(criteria)} criteria from database")
    
    criteria_list = [
        {
            "id": c.id,
            "name": c.name,
            "code": c.code,
            "value_type": c.value_type if hasattr(c, "value_type") and c.value_type else "boolean",  # По умолчанию boolean для обратной совместимости
        }
        for c in criteria
    ]
    
    logger.info(f"on_select_criterion_set: criteria_list={[c.get('id') for c in criteria_list]}, value_types={[c.get('value_type') for c in criteria_list]}")

    data["criterion_set_id"] = criterion_set_id
    data["criteria"] = criteria_list
    data["current_question_index"] = 0
    data["criterion_answers"] = {}
    data["criterion_comments"] = {}
    data.pop("combined_set_names", None)

    await on_select_webform_method(callback, None, dialog_manager)


@inject
async def on_create_new_criterion_set_from_evaluation(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle create new criterion set button click from evaluation dialog.

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
                            "❌ У вас нет прав доступа для создания наборов критериев. "
                            "Только администраторы могут создавать наборы критериев."
                        )
                    return

        # Сохраняем состояние оценки для возможного возврата
        evaluation_state = {
            "organization_id": organization_id,
            "evaluation_type_name": dialog_manager.dialog_data.get("evaluation_type_name"),
            "filled_by_employee_id": dialog_manager.dialog_data.get("filled_by_employee_id"),
            "evaluated_employee_id": dialog_manager.dialog_data.get("evaluated_employee_id"),
        }
        dialog_manager.middleware_data["evaluation_state"] = evaluation_state
        dialog_manager.middleware_data["from_evaluation"] = True  # Флаг для возврата в evaluation

        # Пытаемся получить organization из БД, если organization_id не известен
        if not organization_id and telegram_id:
            user_svc = dialog_manager.middleware_data.get("user_service")
            if not user_svc:
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
                    CriterionSetDialog.name_input,
                    mode=StartMode.NORMAL,
                )
                dialog_manager.dialog_data["organization_id"] = organization_id
                dialog_manager.dialog_data.pop("name", None)
                dialog_manager.dialog_data.pop("description", None)
                dialog_manager.dialog_data.pop("selected_criterion_ids", None)
                dialog_manager.dialog_data.pop("is_default", None)
            else:
                await dialog_manager.start(
                    CriterionSetDialog.select_organization,
                    mode=StartMode.NORMAL,
                )
        else:
            await dialog_manager.start(
                CriterionSetDialog.select_organization,
                mode=StartMode.NORMAL,
            )
    else:
        await dialog_manager.start(
            CriterionSetDialog.select_organization,
            mode=StartMode.NORMAL,
        )


@inject
async def on_select_criterion_set_window_start(
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[Container.criterion_set_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Auto-check if criterion sets exist and navigate to create if empty.
    
    Args:
        dialog_manager: Dialog manager.
        criterion_set_service: CriterionSet service instance (injected).
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    # Get all organizations where user is a member
    telegram_id = None
    if dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    
    user_organization_ids = []
    if telegram_id:
        # Get all organizations where user is a member
        user_organizations = await organization_service.get_all_by_user_telegram_id(telegram_id)
        user_organization_ids = [org.id for org in user_organizations]
        # Update dialog_data and middleware_data with first organization (for compatibility)
        if user_organizations:
            organization_id = user_organizations[0].id
            dialog_manager.dialog_data["organization_id"] = organization_id
            dialog_manager.middleware_data["organization"] = user_organizations[0]
            dialog_manager.dialog_data["user_organization_ids"] = user_organization_ids
        else:
            organization_id = None
    else:
        organization_id = None

    if user_organization_ids:
        # Получаем наборы критериев из всех организаций пользователя
        all_criterion_sets = []
        for org_id in user_organization_ids:
            org_criterion_sets = await criterion_set_service.get_by_organization_id(org_id)
            all_criterion_sets.extend(org_criterion_sets)
        criterion_sets = all_criterion_sets
        
        # Если наборов нет, переходим к созданию нового набора
        if len(criterion_sets) == 0:
            # Проверяем права администратора
            telegram_id = None
            if dialog_manager.event and dialog_manager.event.from_user:
                telegram_id = dialog_manager.event.from_user.id
            
            if telegram_id:
                employee = await employee_service.get_by_telegram_id_and_organization_id(
                    telegram_id, organization_id
                )
                if employee:
                    employee_type_code = employee.meta.get("employee_type_code")
                    is_administrator = employee_type_code == "administrator"
                    
                    if is_administrator:
                        # Сохраняем флаг для возврата в evaluation
                        dialog_manager.middleware_data["from_evaluation"] = True
                        # Переходим к созданию нового набора
                        await dialog_manager.switch_to(CriterionSetDialog.name_input)
                        # Очищаем данные предыдущего набора
                        dialog_manager.dialog_data.pop("name", None)
                        dialog_manager.dialog_data.pop("description", None)
                        dialog_manager.dialog_data.pop("selected_criterion_ids", None)
                        dialog_manager.dialog_data.pop("is_default", None)
                        return


async def on_answer_yes(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle answer Yes button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    criterion_answers = data.get("criterion_answers", {})

    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        criterion_id = current_criterion["id"]
        # Убеждаемся, что ключ всегда int для консистентности
        criterion_id = (
            int(criterion_id)
            if isinstance(criterion_id, str) and criterion_id.isdigit()
            else criterion_id
        )
        criterion_answers[criterion_id] = True
        data["criterion_answers"] = criterion_answers
        # Сохраняем тип вопроса для правильного возврата назад
        data["last_question_type"] = "boolean"
        await dialog_manager.switch_to(EvaluationDialog.add_comment)


async def on_answer_no(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle answer No button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    criterion_answers = data.get("criterion_answers", {})

    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        criterion_id = current_criterion["id"]
        # Убеждаемся, что ключ всегда int для консистентности
        criterion_id = (
            int(criterion_id)
            if isinstance(criterion_id, str) and criterion_id.isdigit()
            else criterion_id
        )
        criterion_answers[criterion_id] = False
        data["criterion_answers"] = criterion_answers
        # Сохраняем тип вопроса для правильного возврата назад
        data["last_question_type"] = "boolean"
        await dialog_manager.switch_to(EvaluationDialog.add_comment)


async def on_prev_question(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 1)

    current_question_index -= 1
    data["current_question_index"] = current_question_index

    await dialog_manager.switch_to(EvaluationDialog.question_loop)


async def process_text_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process text input for string type criterion.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    criterion_answers = data.get("criterion_answers", {})

    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        criterion_id = current_criterion["id"]
        # Убеждаемся, что ключ всегда int для консистентности
        criterion_id = (
            int(criterion_id)
            if isinstance(criterion_id, str) and criterion_id.isdigit()
            else criterion_id
        )
        text_value = message.text.strip() if message.text else ""
        criterion_answers[criterion_id] = text_value
        data["criterion_answers"] = criterion_answers
        # Сохраняем тип вопроса для правильного возврата назад
        data["last_question_type"] = "string"
        await dialog_manager.switch_to(EvaluationDialog.add_comment)


async def process_number_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process number input for number type criterion.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    criterion_answers = data.get("criterion_answers", {})

    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        criterion_id = current_criterion["id"]
        # Убеждаемся, что ключ всегда int для консистентности
        criterion_id = (
            int(criterion_id)
            if isinstance(criterion_id, str) and criterion_id.isdigit()
            else criterion_id
        )
        
        # Пытаемся преобразовать в число
        try:
            number_text = message.text.strip() if message.text else ""
            if "." in number_text:
                number_value = float(number_text)
            else:
                number_value = int(number_text)
            criterion_answers[criterion_id] = number_value
            data["criterion_answers"] = criterion_answers
            # Сохраняем тип вопроса для правильного возврата назад
            data["last_question_type"] = "number"
            await dialog_manager.switch_to(EvaluationDialog.add_comment)
        except (ValueError, TypeError):
            from aiogram.types import Message as MessageType

            if message and isinstance(message, MessageType):
                await message.answer("Ошибка: введите корректное число (например: 10 или 10.5)")


async def on_skip_comment(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip comment button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])

    current_question_index += 1
    data["current_question_index"] = current_question_index

    if current_question_index >= len(criteria):
        await dialog_manager.switch_to(EvaluationDialog.send_to_employee)
    else:
        await dialog_manager.switch_to(EvaluationDialog.question_loop)


async def on_back_to_last_question(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle back to last question button click from send_to_employee window.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    
    # Уменьшаем индекс, чтобы вернуться к последнему вопросу
    if current_question_index >= len(criteria):
        current_question_index = len(criteria) - 1
    else:
        current_question_index = max(0, current_question_index - 1)
    
    data["current_question_index"] = current_question_index
    
    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        value_type = current_criterion.get("value_type", "boolean")
        
        # Сохраняем тип вопроса для правильного возврата из add_comment
        data["last_question_type"] = value_type
        
        # Переходим к правильному окну в зависимости от типа данных
        if value_type == "boolean":
            await dialog_manager.switch_to(EvaluationDialog.answer_question)
        elif value_type == "string":
            await dialog_manager.switch_to(EvaluationDialog.answer_text)
        elif value_type == "number":
            await dialog_manager.switch_to(EvaluationDialog.answer_number)
        else:
            await dialog_manager.switch_to(EvaluationDialog.answer_question)


async def process_comment_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process comment input.

    Args:
        message: Message object.
        widget: MessageInput widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    criterion_comments = data.get("criterion_comments", {})

    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        criterion_id = current_criterion["id"]
        # Убеждаемся, что ключ всегда int для консистентности
        criterion_id = (
            int(criterion_id)
            if isinstance(criterion_id, str) and criterion_id.isdigit()
            else criterion_id
        )
        comment = message.text.strip() if message.text else ""
        criterion_comments[criterion_id] = comment
        data["criterion_comments"] = criterion_comments

    # Переходим к следующему вопросу или завершаем
    current_question_index += 1
    data["current_question_index"] = current_question_index

    if current_question_index >= len(criteria):
        # Все вопросы пройдены, переходим к отправке
        await dialog_manager.switch_to(EvaluationDialog.send_to_employee)
    else:
        # Переходим к следующему вопросу
        await dialog_manager.switch_to(EvaluationDialog.question_loop)


async def on_next_question(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle next question button click (for navigation within question loop).

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    
    if current_question_index < len(criteria):
        current_criterion = criteria[current_question_index]
        value_type = current_criterion.get("value_type", "boolean")
        
        # Переходим к правильному окну в зависимости от типа данных
        if value_type == "boolean":
            await dialog_manager.switch_to(EvaluationDialog.answer_question)
        elif value_type == "string":
            await dialog_manager.switch_to(EvaluationDialog.answer_text)
        elif value_type == "number":
            await dialog_manager.switch_to(EvaluationDialog.answer_number)
        else:
            await dialog_manager.switch_to(EvaluationDialog.answer_question)
    else:
        await dialog_manager.switch_to(EvaluationDialog.answer_question)


@inject
async def on_send_to_employee(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    criterion_value_repo: CriterionValueRepositoryAsyncpg = Provide[
        Container.criterion_value_repository
    ],
):
    """Handle send to employee button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        evaluation_service: Evaluation service instance (injected).
        criterion_service: Criterion service instance (injected).
        criterion_value_repo: CriterionValue repository instance (injected).
    """
    data = dialog_manager.dialog_data

    try:
        # Проверяем наличие обязательных данных
        evaluation_type_id = data.get("evaluation_type_id")
        organization_id = data.get("organization_id")
        filled_by_employee_id = data.get("filled_by_employee_id")
        evaluated_employee_id = data.get("evaluated_employee_id")

        if not evaluation_type_id or not organization_id or not filled_by_employee_id:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Ошибка: не все обязательные данные заполнены"
                )
            return

        # Проверяем, что заполняющий и оцениваемый сотрудники не совпадают
        if evaluated_employee_id and filled_by_employee_id == evaluated_employee_id:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Ошибка: нельзя оценивать самого себя. Выберите другого сотрудника."
                )
            return

        # Проверяем, что оцениваемый сотрудник принадлежит той же организации
        if evaluated_employee_id:
            evaluated_employee = await employee_service.get_by_id(evaluated_employee_id)
            if not evaluated_employee:
                from aiogram.types import Message as MessageType

                if callback.message and isinstance(callback.message, MessageType):
                    await callback.message.answer("Ошибка: оцениваемый сотрудник не найден")
                return

            if evaluated_employee.organization_id != organization_id:
                from aiogram.types import Message as MessageType

                if callback.message and isinstance(callback.message, MessageType):
                    await callback.message.answer(
                        "Ошибка: оцениваемый сотрудник не принадлежит вашей организации. "
                        "Невозможно создать оценку."
                    )
                return

        # Проверяем, что заполняющий сотрудник принадлежит той же организации
        filled_by_employee = await employee_service.get_by_id(filled_by_employee_id)
        if not filled_by_employee:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Ошибка: заполняющий сотрудник не найден")
            return

        if filled_by_employee.organization_id != organization_id:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer(
                    "Ошибка: заполняющий сотрудник не принадлежит выбранной организации. "
                    "Невозможно создать оценку."
                )
            return

        # Создаем оценку
        criterion_set_id = data.get("criterion_set_id")
        create_evaluation_dto = CreateEvaluationDTO(
            evaluation_type_id=evaluation_type_id,
            organization_id=organization_id,
            filled_by_employee_id=filled_by_employee_id,
            evaluated_employee_id=evaluated_employee_id,
            criterion_set_id=criterion_set_id,
            status="completed",
        )

        evaluation = await evaluation_service.create(create_evaluation_dto)

        # Получаем дополнительные данные для сохранения в dialog_data
        organization = await organization_service.get_by_id(organization_id)
        organization_name = organization.name if organization else "Не указано"

        criterion_set_name = None
        if criterion_set_id:
            criterion_set = await criterion_set_service.get_by_id(criterion_set_id)
            if criterion_set:
                # Если это комбинированный набор, показываем имена исходных наборов
                combined_set_names = data.get("combined_set_names")
                if combined_set_names:
                    criterion_set_name = f"Комбинированный: {', '.join(combined_set_names)}"
                else:
                    criterion_set_name = criterion_set.name

        # Подсчитываем статистику
        criteria = data.get("criteria", [])
        criterion_answers = data.get("criterion_answers", {})
        criterion_comments = data.get("criterion_comments", {})

        # Функция для получения ответа по ID критерия (проверяет разные варианты ключа)
        def get_answer_by_id(criterion_id, answers_dict):
            """Получить ответ по ID критерия, проверяя разные варианты ключа."""
            if criterion_id in answers_dict:
                return answers_dict[criterion_id]
            if str(criterion_id) in answers_dict:
                return answers_dict[str(criterion_id)]
            try:
                int_id = (
                    int(criterion_id) if isinstance(criterion_id, str) else criterion_id
                )
                if int_id in answers_dict:
                    return answers_dict[int_id]
            except (ValueError, TypeError):
                pass
            return None

        # Функция для нормализации значения ответа к булевому типу
        def normalize_answer_value(answer):
            if isinstance(answer, bool):
                return answer
            elif isinstance(answer, str):
                return answer.lower() in ("true", "1", "yes", "да")
            elif isinstance(answer, (int, float)):
                return bool(answer)
            else:
                return False

        total_criteria = len(criteria)
        # Подсчитываем статистику только для boolean критериев
        passed_criteria = 0
        boolean_criteria_count = 0
        
        for criterion in criteria:
            criterion_id = criterion["id"]
            value_type = criterion.get("value_type", "boolean")
            answer = get_answer_by_id(criterion_id, criterion_answers)
            
            # Подсчитываем статистику только для boolean критериев
            if value_type == "boolean" and answer is not None:
                boolean_criteria_count += 1
                if answer is True:
                    passed_criteria += 1
        
        failed_criteria = boolean_criteria_count - passed_criteria
        score_percentage = (
            (passed_criteria / boolean_criteria_count * 100) if boolean_criteria_count > 0 else 0.0
        )

        # Сохраняем все данные в dialog_data для генерации PDF
        data["evaluation_id"] = evaluation.id
        data["organization_name"] = organization_name
        data["criterion_set_name"] = criterion_set_name
        data["total_criteria"] = total_criteria
        data["passed_criteria"] = passed_criteria
        data["failed_criteria"] = failed_criteria
        data["score_percentage"] = score_percentage
        data["evaluation_date"] = (
            evaluation.evaluation_date.strftime("%d.%m.%Y %H:%M")
            if evaluation.evaluation_date
            else datetime.now().strftime("%d.%m.%Y %H:%M")
        )

        # Обновляем оценку со статистикой
        update_dto = UpdateEvaluationDTO(
            total_criteria=total_criteria,
            passed_criteria=passed_criteria,
            failed_criteria=failed_criteria,
            score_percentage=score_percentage,
        )
        await evaluation_service.update(evaluation.id, update_dto)

        # Создаем значения критериев
        for criterion in criteria:
            criterion_id = criterion["id"]
            answer = get_answer_by_id(criterion_id, criterion_answers)
            comment = get_answer_by_id(criterion_id, criterion_comments)

            if answer is not None:
                create_criterion_value_dto = CreateCriterionValueDTO(
                    evaluation_id=evaluation.id,
                    criterion_id=criterion_id,
                    value=answer,
                    notes=comment,
                )
                await criterion_value_repo.create(create_criterion_value_dto)

        # Формируем сообщение для отправки
        evaluated_employee_name = data.get("evaluated_employee_name", "Не указано")
        evaluation_type_name = data.get("evaluation_type_name", "Не указано")
        filled_by_employee_name = data.get("filled_by_employee_name", "Не указано")

        message_text = (
            f"📊 Результаты оценки\n\n"
            f"Тип оценки: {evaluation_type_name}\n"
            f"Оцениваемый: {evaluated_employee_name}\n"
            f"Оценивающий: {filled_by_employee_name}\n\n"
            f"Результаты:\n"
            f"Всего критериев: {total_criteria}\n"
            f"Пройдено: {passed_criteria}\n"
            f"Не пройдено: {failed_criteria}\n"
            f"Процент успешных: {score_percentage:.1f}%\n\n"
        )

        # Добавляем детали по каждому критерию
        for criterion in criteria:
            criterion_id = criterion["id"]
            value_type = criterion.get("value_type", "boolean")
            answer = get_answer_by_id(criterion_id, criterion_answers)
            comment = get_answer_by_id(criterion_id, criterion_comments)

            if answer is not None:
                # Форматируем ответ в зависимости от типа данных
                if value_type == "boolean":
                    answer_text = "✅ Да" if answer is True else "❌ Нет"
                elif value_type == "string":
                    answer_text = f"📝 {answer}"
                elif value_type == "number":
                    answer_text = f"🔢 {answer}"
                else:
                    answer_text = str(answer)
                
                message_text += f"{criterion['name']}: {answer_text}\n"
                if comment:
                    message_text += f"  Комментарий: {comment}\n"

        # Отправляем сообщение сотруднику
        if evaluated_employee_id:
            employee = await employee_service.get_by_id(evaluated_employee_id)

            if employee and employee.telegram_id:
                # Получаем bot из dialog_manager
                bot = dialog_manager.middleware_data.get("bot")
                if not bot:
                    # Пытаемся получить из event
                    if dialog_manager.event:
                        bot = getattr(dialog_manager.event, "bot", None)

                if bot and isinstance(bot, Bot):
                    await broadcaster.send_message(
                        bot,
                        employee.telegram_id,
                        message_text,
                    )

        await callback.answer("Оценка успешно создана и отправлена!", show_alert=True)

        # Переходим к окну генерации PDF
        await dialog_manager.switch_to(EvaluationDialog.generate_pdf)

    except Exception as e:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при создании оценки: {str(e)}")
        return


@inject
async def on_generate_pdf(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    pdf_report_service: PDFReportService = Provide[Container.pdf_report_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    criterion_value_repo: CriterionValueRepositoryAsyncpg = Provide[Container.criterion_value_repository],
    criterion_service: CriterionService = Provide[Container.criterion_service],
):
    """Handle generate PDF button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        pdf_report_service: PDF report service instance (injected).
        employee_service: Employee service instance (injected).
        criterion_value_repo: Criterion value repository (injected).
        criterion_service: Criterion service (injected).
    """
    data = dialog_manager.dialog_data

    try:
        # Получаем все данные из dialog_data
        evaluation_id = data.get("evaluation_id")
        if not evaluation_id:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Ошибка: ID оценки не найден")
            return

        evaluation_type_name = data.get("evaluation_type_name", "Не указано")
        organization_name = data.get("organization_name", "Не указано")
        evaluated_employee_name = data.get("evaluated_employee_name", "Не указано")
        filled_by_employee_name = data.get("filled_by_employee_name", "Не указано")
        evaluation_date = data.get(
            "evaluation_date", datetime.now().strftime("%d.%m.%Y %H:%M")
        )
        criterion_set_name = data.get("criterion_set_name")

        # Check if from web form - load criteria from DB
        from_web_form = data.get("from_web_form", False)
        
        if from_web_form:
            # Load criteria values from database
            criterion_values = await criterion_value_repo.get_by_evaluation_id(evaluation_id)
            
            # Get criteria names
            criterion_ids = [cv.criterion_id for cv in criterion_values]
            criteria_objs = await criterion_service.get_by_ids(criterion_ids)
            criteria_map = {c.id: c for c in criteria_objs}
            
            criteria = []
            criterion_answers = {}
            criterion_comments = {}
            
            for cv in criterion_values:
                crit = criteria_map.get(cv.criterion_id)
                criteria.append({
                    "id": cv.criterion_id,
                    "name": crit.name if crit else f"Критерий {cv.criterion_id}",
                    "value_type": crit.value_type if crit else "boolean",
                })
                criterion_answers[cv.criterion_id] = cv.value
                criterion_comments[cv.criterion_id] = cv.notes
        else:
            criteria = data.get("criteria", [])
            criterion_answers = data.get("criterion_answers", {})
            criterion_comments = data.get("criterion_comments", {})

        # Функция для нормализации значения ответа к булевому типу
        def normalize_answer_value(answer):
            if isinstance(answer, bool):
                return answer
            elif isinstance(answer, str):
                return answer.lower() in ("true", "1", "yes", "да")
            elif isinstance(answer, (int, float)):
                return bool(answer)
            else:
                return False

        # Формируем список критериев с нормализованными значениями
        # Нормализуем ключи в словарях ответов (могут быть строки или числа из-за сериализации)
        def get_answer_by_id(criterion_id, answers_dict):
            """Получить ответ по ID критерия, проверяя разные варианты ключа."""
            # Пробуем найти по исходному ключу
            if criterion_id in answers_dict:
                return answers_dict[criterion_id]
            # Пробуем найти по строковому ключу
            if str(criterion_id) in answers_dict:
                return answers_dict[str(criterion_id)]
            # Пробуем найти по числовому ключу
            try:
                int_id = (
                    int(criterion_id) if isinstance(criterion_id, str) else criterion_id
                )
                if int_id in answers_dict:
                    return answers_dict[int_id]
            except (ValueError, TypeError):
                pass
            return None

        criteria_list = []
        boolean_criteria_count = 0
        passed_criteria = 0
        
        for criterion in criteria:
            criterion_id = criterion["id"]
            value_type = criterion.get("value_type", "boolean")
            answer = get_answer_by_id(criterion_id, criterion_answers)
            comment = get_answer_by_id(criterion_id, criterion_comments)

            # Сохраняем исходное значение для PDF
            criteria_list.append(
                {
                    "name": criterion.get("name", "Не указано"),
                    "value": answer,  # Сохраняем исходное значение
                    "value_type": value_type,
                    "comment": comment or "",
                }
            )
            
            # Подсчитываем статистику только для boolean критериев
            if value_type == "boolean" and answer is not None:
                boolean_criteria_count += 1
                if answer is True:
                    passed_criteria += 1

        # Пересчитываем статистику только для boolean критериев
        total_criteria = len(criteria_list)
        failed_criteria = boolean_criteria_count - passed_criteria
        score_percentage = (
            (passed_criteria / boolean_criteria_count * 100) if boolean_criteria_count > 0 else 0.0
        )

        pdf_path = pdf_report_service.generate_evaluation_report(
            evaluation_id=evaluation_id,
            evaluation_type_name=evaluation_type_name,
            organization_name=organization_name,
            evaluated_employee_name=evaluated_employee_name,
            filled_by_employee_name=filled_by_employee_name,
            evaluation_date=evaluation_date,
            criteria=criteria_list,
            total_criteria=total_criteria,
            passed_criteria=passed_criteria,
            failed_criteria=failed_criteria,
            score_percentage=score_percentage,
            criterion_set_name=criterion_set_name,
            boolean_criteria_count=boolean_criteria_count,
        )

        bot = dialog_manager.middleware_data.get("bot")
        if not bot:
            if dialog_manager.event:
                bot = getattr(dialog_manager.event, "bot", None)

        if bot and isinstance(bot, Bot):
            if callback.from_user:
                await broadcaster.send_document(
                    bot,
                    callback.from_user.id,
                    pdf_path,
                    caption=f"📄 PDF отчет по оценке #{evaluation_id}",
                )

            evaluated_employee_id = data.get("evaluated_employee_id")
            if evaluated_employee_id:
                employee = await employee_service.get_by_id(evaluated_employee_id)
                if employee and employee.telegram_id:
                    await broadcaster.send_document(
                        bot,
                        employee.telegram_id,
                        pdf_path,
                        caption=f"📄 PDF отчет по вашей оценке #{evaluation_id}",
                    )

        # Помечаем, что PDF сгенерирован
        dialog_manager.dialog_data["pdf_generated"] = True

        await callback.answer(
            "PDF отчет успешно сгенерирован и отправлен!",
        )

        # Возвращаемся в окно выбора отчетов
        await dialog_manager.switch_to(EvaluationDialog.generate_pdf)

    except Exception as e:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при генерации PDF отчета: {str(e)}")
        return


@inject
async def on_generate_excel(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    excel_report_service: ExcelReportService = Provide[Container.excel_report_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    criterion_value_repo: CriterionValueRepositoryAsyncpg = Provide[Container.criterion_value_repository],
    criterion_service: CriterionService = Provide[Container.criterion_service],
):
    """Handle generate Excel button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
        excel_report_service: Excel report service instance (injected).
        employee_service: Employee service instance (injected).
        criterion_value_repo: Criterion value repository (injected).
        criterion_service: Criterion service (injected).
    """
    data = dialog_manager.dialog_data

    try:
        # Получаем все данные из dialog_data
        evaluation_id = data.get("evaluation_id")
        if not evaluation_id:
            from aiogram.types import Message as MessageType

            if callback.message and isinstance(callback.message, MessageType):
                await callback.message.answer("Ошибка: ID оценки не найден")
            return

        evaluation_type_name = data.get("evaluation_type_name", "Не указано")
        organization_name = data.get("organization_name", "Не указано")
        evaluated_employee_name = data.get("evaluated_employee_name", "Не указано")
        filled_by_employee_name = data.get("filled_by_employee_name", "Не указано")
        evaluation_date = data.get(
            "evaluation_date", datetime.now().strftime("%d.%m.%Y %H:%M")
        )
        criterion_set_name = data.get("criterion_set_name")

        # Check if from web form - load criteria from DB
        from_web_form = data.get("from_web_form", False)
        
        if from_web_form:
            # Load criteria values from database
            criterion_values = await criterion_value_repo.get_by_evaluation_id(evaluation_id)
            
            # Get criteria names
            criterion_ids = [cv.criterion_id for cv in criterion_values]
            criteria_objs = await criterion_service.get_by_ids(criterion_ids)
            criteria_map = {c.id: c for c in criteria_objs}
            
            criteria = []
            criterion_answers = {}
            criterion_comments = {}
            
            for cv in criterion_values:
                crit = criteria_map.get(cv.criterion_id)
                criteria.append({
                    "id": cv.criterion_id,
                    "name": crit.name if crit else f"Критерий {cv.criterion_id}",
                    "value_type": crit.value_type if crit else "boolean",
                })
                criterion_answers[cv.criterion_id] = cv.value
                criterion_comments[cv.criterion_id] = cv.notes
        else:
            criteria = data.get("criteria", [])
            criterion_answers = data.get("criterion_answers", {})
            criterion_comments = data.get("criterion_comments", {})

        # Функция для получения ответа по ID критерия
        def get_answer_by_id(criterion_id, answers_dict):
            if isinstance(answers_dict, dict):
                return answers_dict.get(str(criterion_id)) or answers_dict.get(criterion_id)
            return None

        criteria_list = []
        boolean_criteria_count = 0
        passed_criteria = 0

        for criterion in criteria:
            criterion_id = criterion["id"]
            value_type = criterion.get("value_type", "boolean")
            answer = get_answer_by_id(criterion_id, criterion_answers)
            comment = get_answer_by_id(criterion_id, criterion_comments)

            # Сохраняем исходное значение для Excel
            criteria_list.append(
                {
                    "name": criterion.get("name", "Не указано"),
                    "value": answer,  # Сохраняем исходное значение
                    "value_type": value_type,
                    "comment": comment or "",
                }
            )

            # Подсчитываем статистику только для boolean критериев
            if value_type == "boolean" and answer is not None:
                boolean_criteria_count += 1
                if answer is True:
                    passed_criteria += 1

        # Пересчитываем статистику только для boolean критериев
        total_criteria = len(criteria_list)
        failed_criteria = boolean_criteria_count - passed_criteria
        score_percentage = (
            (passed_criteria / boolean_criteria_count * 100)
            if boolean_criteria_count > 0
            else 0.0
        )

        excel_path = excel_report_service.generate_evaluation_report(
            evaluation_id=evaluation_id,
            evaluation_type_name=evaluation_type_name,
            organization_name=organization_name,
            evaluated_employee_name=evaluated_employee_name,
            filled_by_employee_name=filled_by_employee_name,
            evaluation_date=evaluation_date,
            criteria=criteria_list,
            total_criteria=total_criteria,
            passed_criteria=passed_criteria,
            failed_criteria=failed_criteria,
            score_percentage=score_percentage,
            criterion_set_name=criterion_set_name,
            boolean_criteria_count=boolean_criteria_count,
        )

        bot = dialog_manager.middleware_data.get("bot")
        if not bot:
            if dialog_manager.event:
                bot = getattr(dialog_manager.event, "bot", None)

        if bot and isinstance(bot, Bot):
            if callback.from_user:
                await broadcaster.send_document(
                    bot,
                    callback.from_user.id,
                    excel_path,
                    caption=f"📊 Excel отчет по оценке #{evaluation_id}",
                )

            evaluated_employee_id = data.get("evaluated_employee_id")
            if evaluated_employee_id:
                employee = await employee_service.get_by_id(evaluated_employee_id)
                if employee and employee.telegram_id:
                    await broadcaster.send_document(
                        bot,
                        employee.telegram_id,
                        excel_path,
                        caption=f"📊 Excel отчет по вашей оценке #{evaluation_id}",
                    )

        # Помечаем, что Excel сгенерирован
        dialog_manager.dialog_data["excel_generated"] = True

        await callback.answer(
            "Excel отчет успешно сгенерирован и отправлен!",
        )

        # Возвращаемся в окно выбора отчетов
        await dialog_manager.switch_to(EvaluationDialog.generate_pdf)

    except Exception as e:
        from aiogram.types import Message as MessageType

        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"Ошибка при генерации Excel отчета: {str(e)}")
        return


# ==================== Evaluation Method Selection ====================

async def on_select_bot_method(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle bot evaluation method selection - continue with bot questions.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.switch_to(EvaluationDialog.question_loop)


async def on_select_webform_method(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle web form evaluation method selection - create token and send URL button.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    from aiogram.types import Message as MessageType, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
    from app.api.routers.webapp import create_encrypted_token
    from app.settings import config
    
    data = dialog_manager.dialog_data
    
    # Get required data
    organization_id = data.get("organization_id")
    criterion_set_id = data.get("criterion_set_id")
    filled_by_employee_id = data.get("filled_by_employee_id")
    evaluated_employee_id = data.get("evaluated_employee_id")
    evaluation_type_id = data.get("evaluation_type_id", 1)
    
    if not organization_id or not criterion_set_id or not filled_by_employee_id:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("❌ Ошибка: не все данные заполнены для создания формы")
        return
    
    try:
        # Create encrypted token
        token = create_encrypted_token(
            organization_id=organization_id,
            criterion_set_id=criterion_set_id,
            filled_by_employee_id=filled_by_employee_id,
            evaluated_employee_id=evaluated_employee_id,
            evaluation_type_id=evaluation_type_id,
        )
        
        # Build form URL with token
        # If WEBAPP_API_URL is set (two tunnels setup), include it as api_base param
        from urllib.parse import urlencode
        if config.WEBAPP_API_URL:
            params = urlencode({"token": token, "api_base": config.WEBAPP_API_URL})
            form_url = f"{config.WEBAPP_BASE_URL}?{params}"
        else:
            form_url = f"{config.WEBAPP_BASE_URL}?token={token}"
        
        # Get names for display
        evaluated_name = data.get("evaluated_employee_name", "сотрудника")
        criteria_count = len(data.get("criteria", []))
        
        # Check if URL is localhost (Telegram doesn't allow localhost in button URLs)
        is_localhost = "localhost" in config.WEBAPP_BASE_URL or "127.0.0.1" in config.WEBAPP_BASE_URL
        
        # Get bot
        bot = dialog_manager.middleware_data.get("bot")
        if not bot:
            if dialog_manager.event:
                bot = getattr(dialog_manager.event, "bot", None)
        
        if bot and callback.from_user:
            if is_localhost:
                # For localhost: send URL as text (for local development)
                message_text = (
                    f"📋 <b>Форма оценки готова!</b>\n\n"
                    f"👤 Оцениваемый: {evaluated_name}\n"
                    f"📊 Критериев: {criteria_count}\n\n"
                    f"🔗 <b>Ссылка на форму:</b>\n<code>{form_url}</code>\n\n"
                    f"<i>💡 Для кнопки вместо ссылки используйте туннель (serveo.net)</i>\n"
                    f"После заполнения результаты будут сохранены автоматически."
                )
                await bot.send_message(
                    callback.from_user.id,
                    message_text,
                    parse_mode="HTML",
                )
            else:
                # For public URLs: send as button
                message_text = (
                    f"📋 <b>Форма оценки готова!</b>\n\n"
                    f"👤 Оцениваемый: {evaluated_name}\n"
                    f"📊 Критериев: {criteria_count}\n\n"
                    f"После заполнения результаты будут сохранены автоматически."
                )
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="🌐 Открыть форму оценки", web_app=WebAppInfo(url=form_url))]
                    ]
                )
                await bot.send_message(
                    callback.from_user.id,
                    message_text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
        
        await callback.answer("Форма создана!")
        
        # End dialog - user will fill form via link
        await dialog_manager.done()
        
    except Exception as e:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"❌ Ошибка при создании формы: {str(e)}")


# Wrapper handlers for evaluation type creation using common functions
async def process_evaluation_type_name_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process evaluation type name input."""
    await common_process_name(
        message, widget, dialog_manager, EvaluationDialog.evaluation_type_code_input
    )


async def process_evaluation_type_code_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process evaluation type code input."""
    await common_process_code(
        message,
        widget,
        dialog_manager,
        EvaluationDialog.evaluation_type_description_input,
    )


async def process_evaluation_type_description_input(
    message: Message, widget: MessageInput, dialog_manager: DialogManager
):
    """Process evaluation type description input."""
    await common_process_description(
        message, widget, dialog_manager, EvaluationDialog.evaluation_type_confirm
    )


async def on_skip_evaluation_type_description(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip evaluation type description button click."""
    await common_skip_description(
        callback, button, dialog_manager, EvaluationDialog.evaluation_type_confirm
    )


async def on_confirm_evaluation_type(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle confirm evaluation type button click."""
    # После создания типа оценки возвращаемся к выбору типа оценки
    # чтобы пользователь мог выбрать только что созданный тип
    await confirm_evaluation_type(
        callback, button, dialog_manager, EvaluationDialog.select_evaluation_type
    )


async def on_skip_pdf(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Handle skip PDF generation button click.

    Args:
        callback: Callback query.
        button: Button widget.
        dialog_manager: Dialog manager.
    """
    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )


@inject
async def on_select_evaluation_to_delete(
    callback: CallbackQuery,
    widget,
    dialog_manager: DialogManager,
    item_id: str,
    evaluation_service: EvaluationService = Provide[Container.evaluation_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle evaluation selection for deletion.

    Args:
        callback: Callback query.
        widget: Widget instance.
        dialog_manager: Dialog manager.
        item_id: Selected evaluation ID.
        evaluation_service: Evaluation service instance (injected).
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
    """
    from app.tgbot.dialogs.organization.handlers import _check_administrator_access
    from aiogram.types import Message as MessageType
    
    # Check administrator access
    if not await _check_administrator_access(callback, dialog_manager, employee_service):
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(
                "❌ У вас нет прав доступа для удаления замеров. "
                "Только администраторы могут удалять замеры."
            )
        return
    
    evaluation_id = int(item_id)
    
    # Delete evaluation
    success = await evaluation_service.delete(evaluation_id)
    if success:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer(f"✅ Замер #{evaluation_id} успешно удален.")
        # Return to greeting menu
        await dialog_manager.start(
            GreetingDialog.greeting,
            mode=StartMode.RESET_STACK,
        )
    else:
        if callback.message and isinstance(callback.message, MessageType):
            await callback.message.answer("❌ Ошибка: не удалось удалить замер.")
