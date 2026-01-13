"""Getters for evaluation dialog."""

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.criterion_set_service import CriterionSetService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.evaluation_type_service import EvaluationTypeService
from app.internal.usecases.organization_service import OrganizationService


@inject
async def get_evaluation_types_list_data(
    dialog_manager: DialogManager,
    evaluation_type_service: EvaluationTypeService = Provide[
        Container.evaluation_type_service
    ],
    *args,
    **kwargs,
):
    """Get data for evaluation types list window.

    Args:
        dialog_manager: Dialog manager instance.
        evaluation_type_service: EvaluationType service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with evaluation types list data.
    """
    evaluation_types = await evaluation_type_service.get_all()

    return {
        "evaluation_types": evaluation_types,
        "has_evaluation_types": len(evaluation_types) > 0,
        "no_evaluation_types": len(evaluation_types) == 0,
    }


@inject
async def get_employees_list_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    *args,
    **kwargs,
):
    """Get data for employees list window.

    Args:
        dialog_manager: Dialog manager instance.
        employee_service: Employee service instance (injected).
        organization_service: Organization service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with employees list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        # Try to get from middleware_data or load by user
        organization = dialog_manager.middleware_data.get("organization")
        if organization:
            organization_id = organization.id
            dialog_manager.dialog_data["organization_id"] = organization_id
        else:
            telegram_id = None
            if dialog_manager.event and dialog_manager.event.from_user:
                telegram_id = dialog_manager.event.from_user.id
            if telegram_id:
                organization = await organization_service.get_by_user_telegram_id(
                    telegram_id
                )
                if organization:
                    organization_id = organization.id
                    dialog_manager.dialog_data["organization_id"] = organization_id
                    dialog_manager.middleware_data["organization"] = organization

    if not organization_id:
        return {
            "employees": [],
            "has_employees": False,
            "no_employees": True,
        }

    # Check if filled_by_employee is already set (for non-administrators)
    filled_by_employee_id = dialog_manager.dialog_data.get("filled_by_employee_id")
    if not filled_by_employee_id:
        # For non-administrators: automatically set current user as filled_by_employee
        telegram_id = None
        if dialog_manager.event and dialog_manager.event.from_user:
            telegram_id = dialog_manager.event.from_user.id

        if telegram_id and organization_id:
            employee = await employee_service.get_by_telegram_id_and_organization_id(
                telegram_id, organization_id
            )
            if employee:
                employee_type_code = employee.meta.get("employee_type_code")
                is_administrator = employee_type_code == "administrator"

                # Auto-select for non-administrators
                if not is_administrator:
                    dialog_manager.dialog_data["filled_by_employee_id"] = employee.id
                    dialog_manager.dialog_data["filled_by_employee_name"] = (
                        employee.full_name
                    )
                    filled_by_employee_id = employee.id

    employees = await employee_service.get_by_organization_id(organization_id)

    # Исключаем заполняющего сотрудника из списка оцениваемых
    # (нельзя оценивать самого себя)
    if filled_by_employee_id:
        employees = [emp for emp in employees if emp.id != filled_by_employee_id]

    return {
        "employees": employees,
        "has_employees": len(employees) > 0,
        "no_employees": len(employees) == 0,
        "filled_by_employee_id": filled_by_employee_id,  # Add this to check in window
    }


@inject
async def get_criterion_sets_list_data(
    dialog_manager: DialogManager,
    criterion_set_service: CriterionSetService = Provide[
        Container.criterion_set_service
    ],
    *args,
    **kwargs,
):
    """Get data for criterion sets list window.

    Args:
        dialog_manager: Dialog manager instance.
        criterion_set_service: CriterionSet service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criterion sets list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        return {
            "criterion_sets": [],
            "has_criterion_sets": False,
            "no_criterion_sets": True,
            "has_default_set": False,
        }

    criterion_sets = await criterion_set_service.get_by_organization_id(organization_id)

    # Проверяем наличие дефолтного набора
    default_set = next((cs for cs in criterion_sets if cs.is_default), None)

    # Для окна комбинирования наборов
    selected_set_ids = dialog_manager.dialog_data.get(
        "selected_set_ids_for_combine", []
    )
    selected_count = len(selected_set_ids)
    can_combine = selected_count >= 2

    criterion_sets_with_display = []
    for cs in criterion_sets:
        display_name = f"{cs.name} (Дефолтный)" if cs.is_default else cs.name
        # Добавляем маркер выбора для окна комбинирования
        selected_marker = "✅" if cs.id in selected_set_ids else "⬜"
        criterion_sets_with_display.append(
            {
                "id": cs.id,
                "name": cs.name,
                "description": cs.description,
                "is_default": cs.is_default,
                "display_name": display_name,
                "selected_marker": selected_marker,
            }
        )

    # Сохраняем default_set_id в dialog_data для использования в handlers
    if default_set:
        dialog_manager.dialog_data["default_set_id"] = default_set.id
    else:
        dialog_manager.dialog_data.pop("default_set_id", None)

    return {
        "criterion_sets": criterion_sets_with_display,
        "has_criterion_sets": len(criterion_sets) > 0,
        "no_criterion_sets": len(criterion_sets) == 0,
        "has_default_set": default_set is not None,
        "default_set_id": default_set.id if default_set else None,
        "selected_set_ids": selected_set_ids,
        "selected_count": selected_count,
        "can_combine": can_combine,
    }


async def get_current_question_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for current question window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with current question data.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    data = dialog_manager.dialog_data
    current_question_index = data.get("current_question_index", 0)
    criteria = data.get("criteria", [])
    criterion_answers = data.get("criterion_answers", {})
    criterion_comments = data.get("criterion_comments", {})
    
    logger.info(f"get_current_question_data: current_question_index={current_question_index}, len(criteria)={len(criteria)}, criteria={[c.get('id') for c in criteria] if criteria else 'empty'}")

    if current_question_index >= len(criteria):
        return {
            "question_text": "Все вопросы пройдены",
            "current_question": None,
            "current_question_index": current_question_index,
            "total_questions": len(criteria),
            "has_next": False,
        }

    current_criterion = criteria[current_question_index]
    current_answer = criterion_answers.get(current_criterion["id"])
    current_comment = criterion_comments.get(current_criterion["id"])
    value_type = current_criterion.get("value_type", "boolean")

    # Форматируем текущий ответ в зависимости от типа
    answer_display = None
    if current_answer is not None:
        if value_type == "boolean":
            answer_display = "Да" if current_answer else "Нет"
        elif value_type == "string":
            answer_display = str(current_answer)
        elif value_type == "number":
            answer_display = str(current_answer)

    return {
        "question_text": f"Вопрос {current_question_index + 1} из {len(criteria)}:\n\n{current_criterion['name']}",
        "current_question": current_criterion,
        "current_question_index": current_question_index,
        "total_questions": len(criteria),
        "has_next": current_question_index < len(criteria) - 1,
        "value_type": value_type,
        "current_answer": answer_display,
        "current_answer_raw": current_answer,
        "has_comment": current_comment is not None and current_comment != "",
    }


async def get_add_comment_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for add comment window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with add comment window data.
    """
    data = dialog_manager.dialog_data
    last_question_type = data.get("last_question_type", "boolean")

    return {
        "last_question_type": last_question_type,
        "is_boolean_question": last_question_type == "boolean",
        "is_string_question": last_question_type == "string",
        "is_number_question": last_question_type == "number",
    }


async def get_report_generation_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for report generation window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with report generation status data.
    """
    data = dialog_manager.dialog_data
    pdf_generated = data.get("pdf_generated", False)
    excel_generated = data.get("excel_generated", False)
    both_generated = pdf_generated and excel_generated

    # Формируем текст сообщения
    if both_generated:
        message_text = (
            "Оценка успешно создана! ✅\n\n"
            "Оба отчета сгенерированы:\n"
            "✅ PDF отчет\n"
            "✅ Excel отчет"
        )
    elif pdf_generated:
        message_text = (
            "Оценка успешно создана! ✅\n\n"
            "PDF отчет сгенерирован ✅\n"
            "Хотите также сгенерировать Excel отчет?"
        )
    elif excel_generated:
        message_text = (
            "Оценка успешно создана! ✅\n\n"
            "Excel отчет сгенерирован ✅\n"
            "Хотите также сгенерировать PDF отчет?"
        )
    else:
        message_text = "Оценка успешно создана! ✅\n\nХотите сгенерировать отчет?"

    return {
        "message_text": message_text,
        "pdf_generated": pdf_generated,
        "excel_generated": excel_generated,
        "both_generated": both_generated,
        "show_pdf_button": not pdf_generated,
        "show_excel_button": not excel_generated,
        "show_skip_button": not both_generated,
    }
