"""Getters for analytics dialog."""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

from aiogram_dialog import DialogManager
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.analytics_service import AnalyticsService
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.organization_service import OrganizationService
from app.tgbot.dialogs.common.organization import (
    get_organizations_list_data as common_get_organizations_list_data,
)

logger = logging.getLogger(__name__)

# Переопределяем для аналитики, если нужно, или просто используем общую
get_organizations_list_data = common_get_organizations_list_data


async def get_analytics_type_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for analytics type selection window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with analytics types data.
    """
    return {
        "analytics_types": [
            {
                "id": "criteria_stats",
                "name": "📊 Статистика по критериям",
                "description": "Анализ прохождения критериев",
            },
            {
                "id": "ai_assistant",
                "name": "🤖 Ассистент",
                "description": "Диалог с ИИ для анализа данных",
            },
            {
                "id": "objects",
                "name": "📦 Объекты",
                "description": "Просмотр и экспорт объектов",
            },
        ],
    }


async def get_group_by_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for group by selection window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with group by options data.
    """
    return {
        "group_by_options": [
            {
                "id": "criterion",
                "name": "📋 По критериям",
                "description": "Группировка по критериям",
            },
            {
                "id": "employee",
                "name": "👥 По сотрудникам",
                "description": "Группировка по сотрудникам",
            },
            {
                "id": "date",
                "name": "📅 По датам",
                "description": "Группировка по датам",
            },
        ],
    }


@inject
async def get_criteria_list_data(
    dialog_manager: DialogManager,
    criterion_service: CriterionService = Provide[Container.criterion_service],
    *args,
    **kwargs,
):
    """Get data for criteria selection window.

    Args:
        dialog_manager: Dialog manager instance.
        criterion_service: Criterion service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with criteria list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        org = dialog_manager.middleware_data.get("organization")
        if org:
            organization_id = org.id
            dialog_manager.dialog_data["organization_id"] = organization_id
    if not organization_id:
        return {"criteria": [], "has_criteria": False}

    criteria = await criterion_service.get_by_organization_id(organization_id)

    # Фильтруем критерии в зависимости от типа аналитики
    analytics_type = dialog_manager.dialog_data.get("analytics_type")
    if analytics_type == "average_scores":
        # Для среднего балла показываем только числовые критерии
        criteria = [c for c in criteria if c.value_type == "number"]
    # Для других типов аналитики показываем все критерии

    selected_criterion_ids = dialog_manager.dialog_data.get(
        "selected_criterion_ids", []
    )

    criteria_with_selection = []
    for criterion in criteria:
        is_selected = criterion.id in selected_criterion_ids
        criteria_with_selection.append(
            {
                "id": criterion.id,
                "name": criterion.name,
                "code": criterion.code,
                "value_type": criterion.value_type,
                "display_name": f"{criterion.name} ({criterion.code})",
                "is_selected": is_selected,
                "marker": "✅" if is_selected else "⬜",
            }
        )

    return {
        "criteria": criteria_with_selection,
        "has_criteria": len(criteria_with_selection) > 0,
        "selected_count": len(selected_criterion_ids),
    }


@inject
async def get_employees_list_data(
    dialog_manager: DialogManager,
    employee_service: EmployeeService = Provide[Container.employee_service],
    *args,
    **kwargs,
):
    """Get data for employees selection window.

    Args:
        dialog_manager: Dialog manager instance.
        employee_service: Employee service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with employees list data.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    if not organization_id:
        org = dialog_manager.middleware_data.get("organization")
        if org:
            organization_id = org.id
            dialog_manager.dialog_data["organization_id"] = organization_id
    if not organization_id:
        return {"employees": [], "has_employees": False}

    employees = await employee_service.get_by_organization_id(organization_id)

    selected_employee_ids = dialog_manager.dialog_data.get("selected_employee_ids", [])

    employees_with_selection = []
    for employee in employees:
        is_selected = employee.id in selected_employee_ids
        employees_with_selection.append(
            {
                "id": employee.id,
                "full_name": employee.full_name,
                "position": employee.position,
                "display_name": f"{employee.full_name} ({employee.position or 'Без должности'})",
                "is_selected": is_selected,
                "marker": "✅" if is_selected else "⬜",
            }
        )

    return {
        "employees": employees_with_selection,
        "has_employees": len(employees) > 0,
        "selected_count": len(selected_employee_ids),
    }


@inject
async def get_results_data(
    dialog_manager: DialogManager,
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    *args,
    **kwargs,
):
    """Get data for results display window.

    Args:
        dialog_manager: Dialog manager instance.
        analytics_service: Analytics service instance (injected).
        criterion_service: Criterion service instance (injected).
        employee_service: Employee service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with results data.
    """
    data = dialog_manager.dialog_data
    organization_id = data.get("organization_id")
    analytics_type = data.get("analytics_type", "criteria_stats")
    criterion_ids = data.get("selected_criterion_ids")
    employee_ids = data.get("selected_employee_ids")

    # Для average_scores, если критерии не выбраны, показываем все числовые критерии
    if analytics_type == "average_scores" and (
        not criterion_ids or len(criterion_ids) == 0
    ):
        criterion_ids = None  # None означает "все критерии"

    # Преобразуем строки ISO формата обратно в datetime объекты
    date_from_str = data.get("date_from")
    date_to_str = data.get("date_to")
    date_from = None
    date_to = None

    if date_from_str:
        try:
            date_from = datetime.fromisoformat(date_from_str)
        except (ValueError, TypeError):
            date_from = None

    if date_to_str:
        try:
            date_to = datetime.fromisoformat(date_to_str)
        except (ValueError, TypeError):
            date_to = None

    if not organization_id:
        return {"results_text": "❌ Ошибка: организация не выбрана"}

    try:
        if analytics_type == "criteria_stats":
            result = await analytics_service.get_criteria_statistics(
                organization_id=organization_id,
                criterion_ids=criterion_ids,
                employee_ids=employee_ids,
                date_from=date_from,
                date_to=date_to,
            )

            # Форматируем результаты
            results_lines = ["📊 Статистика по критериям\n"]
            results_lines.append(
                f"📈 Всего замеров: {result.get('total_evaluations', 0)}\n"
            )

            statistics = result.get("statistics", [])
            if not statistics:
                results_lines.append("\nНет данных для отображения.")
            else:
                criterion_names = {}
                all_criterion_ids = {stat["criterion_id"] for stat in statistics}
                for criterion_id in all_criterion_ids:
                    criterion = await criterion_service.get_by_id(criterion_id)
                    if criterion:
                        criterion_names[criterion_id] = criterion.name

                for stat in statistics[:20]:  # Ограничиваем до 20 для читаемости
                    criterion_id = stat["criterion_id"]
                    criterion_name = criterion_names.get(
                        criterion_id, f"Критерий #{criterion_id}"
                    )
                    total = stat["total"]
                    passed = stat["passed"]
                    failed = stat["failed"]

                    if total > 0:
                        passed_pct = (passed / total * 100) if total > 0 else 0
                        results_lines.append(
                            f"\n📋 {criterion_name}:\n"
                            f"  📊 Всего: {total}\n"
                            f"  ✅ Пройдено: {passed} ({passed_pct:.1f}%)\n"
                            f"  ❌ Не пройдено: {failed}"
                        )

                        if "number_avg" in stat:
                            results_lines.append(
                                f"  📈 Среднее: {stat['number_avg']:.2f}\n"
                                f"  📉 Мин: {stat['number_min']:.2f}, 📊 Макс: {stat['number_max']:.2f}"
                            )

            results_text = "\n".join(results_lines)

        elif analytics_type == "average_scores":
            group_by = data.get("group_by", "criterion")
            # Если критерии не выбраны, передаем None вместо пустого списка
            # чтобы получить данные по всем критериям
            criterion_ids_for_query = criterion_ids if criterion_ids else None
            result = await analytics_service.get_average_scores(
                organization_id=organization_id,
                criterion_ids=criterion_ids_for_query,
                employee_ids=employee_ids,
                date_from=date_from,
                date_to=date_to,
                group_by=group_by,
            )

            results_lines = [f"📈 Средний балл (группировка: {group_by})\n"]
            averages = result.get("averages", [])

            if not averages:
                results_lines.append("\n⚠️ Нет данных для отображения.")
                # Добавляем отладочную информацию
                if criterion_ids_for_query:
                    results_lines.append(
                        f"\n(✅ Выбрано критериев: {len(criterion_ids_for_query)})"
                    )
                else:
                    results_lines.append(
                        "\n(📋 Критерии не выбраны - показываются все)"
                    )
            else:
                if group_by == "criterion":
                    criterion_names = {}
                    criterion_types = {}
                    for avg in averages:
                        criterion_id = avg["criterion_id"]
                        if criterion_id not in criterion_names:
                            criterion = await criterion_service.get_by_id(criterion_id)
                            if criterion:
                                criterion_names[criterion_id] = criterion.name
                                criterion_types[criterion_id] = criterion.value_type
                        # Используем тип из результата, если есть
                        if "value_type" in avg:
                            criterion_types[criterion_id] = avg["value_type"]

                    for avg in averages[:20]:
                        criterion_id = avg["criterion_id"]
                        criterion_name = criterion_names.get(
                            criterion_id, f"Критерий #{criterion_id}"
                        )
                        value_type = criterion_types.get(
                            criterion_id, avg.get("value_type", "boolean")
                        )

                        if value_type == "boolean":
                            # Для boolean показываем процент прохождения
                            results_lines.append(
                                f"\n📋 {criterion_name}:\n"
                                f"  ✅ Процент прохождения: {avg['average']:.2f}%\n"
                                f"  📊 Количество: {avg['count']}"
                            )
                        elif value_type == "number":
                            # Для number показываем среднее значение
                            results_lines.append(
                                f"\n📋 {criterion_name}:\n"
                                f"  📈 Среднее значение: {avg['average']:.2f}\n"
                                f"  📊 Количество: {avg['count']}"
                            )
                        else:
                            # Для других типов (string) не показываем средний балл
                            results_lines.append(
                                f"\n📋 {criterion_name}:\n"
                                f"  📊 Количество: {avg['count']}\n"
                                f"  📝 (Текстовый критерий - средний балл не применим)"
                            )
                elif group_by == "employee":
                    employee_names = {}
                    for avg in averages:
                        employee_id = avg["employee_id"]
                        if employee_id not in employee_names:
                            employee = await employee_service.get_by_id(employee_id)
                            if employee:
                                employee_names[employee_id] = employee.full_name

                    for avg in averages[:20]:
                        employee_id = avg["employee_id"]
                        employee_name = employee_names.get(
                            employee_id, f"Сотрудник #{employee_id}"
                        )
                        results_lines.append(
                            f"\n👤 {employee_name}:\n"
                            f"  📈 Средний балл: {avg['average']:.2f}%\n"
                            f"  📊 Количество замеров: {avg['count']}"
                        )
                else:  # date
                    for avg in averages[:30]:
                        results_lines.append(
                            f"\n📅 {avg['date']}:\n"
                            f"  📈 Средний балл: {avg['average']:.2f}%\n"
                            f"  📊 Количество замеров: {avg['count']}"
                        )

            results_text = "\n".join(results_lines)

        else:  # custom_query
            filters = {
                "criterion_ids": criterion_ids,
                "employee_ids": employee_ids,
                "date_from": date_from,
                "date_to": date_to,
            }
            result = await analytics_service.get_custom_query(
                organization_id=organization_id,
                filters=filters,
            )

            results_lines = ["🔍 Произвольный запрос\n"]
            results_lines.append(
                f"📊 Найдено результатов: {result.get('total_results', 0)}\n"
            )

            results_data = result.get("results", [])
            if not results_data:
                results_lines.append("\n⚠️ Нет данных для отображения.")
            else:
                results_lines.append(
                    f"\n📋 Показано первых {min(10, len(results_data))} результатов:\n"
                )
                for eval_data in results_data[:10]:
                    eval_id = eval_data.get("id")
                    eval_date = eval_data.get("evaluation_date")
                    score = eval_data.get("score_percentage", 0.0)
                    results_lines.append(
                        f"📊 Замер #{eval_id} ({eval_date.strftime('%d.%m.%Y') if eval_date else 'N/A'}): "
                        f"{score:.1f}%"
                    )

            results_text = "\n".join(results_lines)

    except Exception as e:
        results_text = f"❌ Ошибка при получении данных: {str(e)}"

    return {"results_text": results_text}


async def get_ai_data_type_data(
    dialog_manager: DialogManager,
    *args,
    **kwargs,
):
    """Get data for AI data type selection window.

    Args:
        dialog_manager: Dialog manager instance.
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with data type options.
    """
    return {
        "data_types": [
            {
                "id": "organizations",
                "name": "🏢 По организациям",
                "description": "Загрузить данные об организациях",
            },
            {
                "id": "employees",
                "name": "👥 По сотрудникам",
                "description": "Загрузить данные о сотрудниках",
            },
            {
                "id": "evaluations",
                "name": "📊 По замерам",
                "description": "Загрузить данные о замерах",
            },
            {
                "id": "criteria",
                "name": "📋 По критериям",
                "description": "Загрузить данные о критериях",
            },
            {
                "id": "all",
                "name": "📈 Все данные",
                "description": "Загрузить все доступные данные",
            },
        ],
    }


def _format_organization(org) -> str:
    """Format organization data for display.

    Args:
        org: OrganizationDTO object.

    Returns:
        Formatted string.
    """
    org_name = getattr(org, "name", "N/A")
    org_id = getattr(org, "id", "N/A")
    org_code = getattr(org, "code", "N/A")
    org_address = getattr(org, "address", None)
    org_phone = getattr(org, "phone", None)
    org_active = getattr(org, "is_active", True)

    org_info = f"🏢 {org_name}\n"
    org_info += f"   ID: {org_id} | Код: {org_code}\n"
    org_info += f"   Активна: {'Да' if org_active else 'Нет'}"
    if org_address:
        org_info += f"\n   Адрес: {org_address}"
    if org_phone:
        org_info += f"\n   Телефон: {org_phone}"
    return org_info


def _format_employee(employee) -> str:
    """Format employee data for display.

    Args:
        employee: EmployeeDTO object.

    Returns:
        Formatted string.
    """
    hire_date_str = (
        employee.hire_date.strftime("%Y-%m-%d") if employee.hire_date else "Не указана"
    )

    emp_info = f"👤 {employee.full_name}\n"
    emp_info += f"   ID: {employee.id}\n"
    emp_info += f"   Должность: {employee.position or 'Не указана'}\n"
    emp_info += f"   Телефон: {employee.phone or 'Не указан'}\n"
    emp_info += f"   Telegram: {employee.telegram_id or 'Не указан'}"
    if employee.username:
        emp_info += f" (@{employee.username})"
    emp_info += f"\n   Дата найма: {hire_date_str}\n"
    emp_info += f"   Активен: {'Да' if employee.is_active else 'Нет'}"
    return emp_info


def _format_evaluation(
    eval_data: Dict,
    employee_names_map: Dict[int, str],
    criterion_names_map: Dict[int, str],
) -> str:
    """Format evaluation data for display.

    Args:
        eval_data: Evaluation data dictionary.
        employee_names_map: Map of employee IDs to names.
        criterion_names_map: Map of criterion IDs to names.

    Returns:
        Formatted string.
    """
    eval_id = eval_data.get("id")
    eval_date = eval_data.get("evaluation_date")
    filled_by_id = eval_data.get("filled_by_employee_id")
    evaluated_id = eval_data.get("evaluated_employee_id")
    eval_type_id = eval_data.get("evaluation_type_id")
    score = eval_data.get("score_percentage", 0.0)
    total_criteria = eval_data.get("total_criteria", 0)
    passed_criteria = eval_data.get("passed_criteria", 0)
    failed_criteria = eval_data.get("failed_criteria", 0)
    comment = eval_data.get("comment")
    status = eval_data.get("status", "unknown")
    criterion_values = eval_data.get("criterion_values", [])

    filled_by_name = (
        employee_names_map.get(filled_by_id, f"ID {filled_by_id}")
        if filled_by_id and isinstance(filled_by_id, int)
        else "Не указан"
    )
    evaluated_name = (
        employee_names_map.get(evaluated_id, f"ID {evaluated_id}")
        if evaluated_id and isinstance(evaluated_id, int)
        else "Самозаполнение"
    )

    eval_info = f"📊 Замер #{eval_id}\n"
    eval_info += (
        f"   Дата: {eval_date.strftime('%Y-%m-%d %H:%M') if eval_date else 'N/A'}\n"
    )
    eval_info += f"   Тип замера ID: {eval_type_id}\n"
    eval_info += f"   Заполнил: {filled_by_name}\n"
    eval_info += f"   Оцениваемый: {evaluated_name}\n"
    eval_info += f"   Балл: {score:.1f}%\n"
    eval_info += f"   Критерии: {passed_criteria}/{total_criteria} прошло, {failed_criteria} не прошло\n"
    eval_info += f"   Статус: {status}"
    if comment:
        eval_info += f"\n   Комментарий: {comment[:100]}"

    if criterion_values:
        eval_info += f"\n   Значения ({len(criterion_values)}):"
        for cv in criterion_values[:5]:  # Показываем первые 5
            criterion_id = cv.get("criterion_id")
            criterion_name = criterion_names_map.get(criterion_id, f"ID {criterion_id}")
            value = cv.get("value")
            value_type = cv.get("value_type", "boolean")
            if value_type == "boolean":
                value_str = "Да" if value else "Нет"
            elif value_type == "number":
                value_str = str(value)
            elif value_type == "string":
                value_str = f"'{value}'"
            else:
                value_str = str(value)
            eval_info += f"\n     • {criterion_name}: {value_str}"
        if len(criterion_values) > 5:
            eval_info += f"\n     ... и еще {len(criterion_values) - 5}"

    return eval_info


def _format_criterion(criterion) -> str:
    """Format criterion data for display.

    Args:
        criterion: CriterionDTO object.

    Returns:
        Formatted string.
    """
    crit_info = f"📋 {criterion.name}\n"
    crit_info += f"   ID: {criterion.id} | Код: {criterion.code}\n"
    crit_info += f"   Тип значения: {criterion.value_type}\n"
    if criterion.category_id:
        crit_info += f"   Категория ID: {criterion.category_id}\n"
    crit_info += f"   Обязательный: {'Да' if criterion.is_required else 'Нет'}\n"
    crit_info += f"   Активен: {'Да' if criterion.is_active else 'Нет'}\n"
    crit_info += f"   Порядок: {criterion.sort_order}"
    if criterion.description:
        crit_info += f"\n   Описание: {criterion.description[:100]}"
    return crit_info


@inject
async def get_ai_view_data(
    dialog_manager: DialogManager,
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    *args,
    **kwargs,
):
    """Get paginated data for AI data view window.

    Args:
        dialog_manager: Dialog manager instance.
        analytics_service: Analytics service instance (injected).
        organization_service: Organization service instance (injected).
        criterion_service: Criterion service instance (injected).
        employee_service: Employee service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with paginated data for display.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    data_type = dialog_manager.dialog_data.get("ai_data_type", "none")
    current_page = dialog_manager.dialog_data.get("ai_data_page", 0)
    items_per_page = 4  # По 4 объекта на странице

    if not organization_id or data_type == "none":
        return {
            "display_text": "❌ Данные не выбраны.",
            "has_prev": False,
            "has_next": False,
            "current_page": 0,
            "total_pages": 0,
        }

    # Получаем информацию об организации
    organization = await organization_service.get_by_id(organization_id)
    org_name = organization.name if organization else f"Организация #{organization_id}"

    try:
        formatted_items: List[str] = []

        if data_type in ["organizations", "all"]:
            orgs_data = await get_organizations_list_data(dialog_manager)
            organizations = orgs_data.get("organizations", [])
            for org in organizations:
                formatted_items.append(_format_organization(org))

        if data_type in ["employees", "all"]:
            employees = await employee_service.get_by_organization_id(organization_id)
            for employee in employees:
                formatted_items.append(_format_employee(employee))

        if data_type in ["evaluations", "all"]:
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=None,
                    employee_ids=None,
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )

            # Получаем имена сотрудников и критериев
            employee_ids_set = set()
            criterion_ids_set = set()
            for eval_data in evaluations_data:
                filled_by_id = eval_data.get("filled_by_employee_id")
                evaluated_id = eval_data.get("evaluated_employee_id")
                if filled_by_id:
                    employee_ids_set.add(filled_by_id)
                if evaluated_id:
                    employee_ids_set.add(evaluated_id)

                criterion_values = eval_data.get("criterion_values", [])
                for cv in criterion_values:
                    criterion_id = cv.get("criterion_id")
                    if criterion_id:
                        criterion_ids_set.add(criterion_id)

            employee_names_map = {}
            if employee_ids_set:
                employees_list = await employee_service.get_by_organization_id(
                    organization_id
                )
                for emp in employees_list:
                    if emp.id in employee_ids_set:
                        employee_names_map[emp.id] = emp.full_name

            criterion_names_map = {}
            if criterion_ids_set:
                criteria_list = await criterion_service.get_by_organization_id(
                    organization_id
                )
                for crit in criteria_list:
                    if crit.id in criterion_ids_set:
                        criterion_names_map[crit.id] = crit.name

            for eval_data in evaluations_data:
                formatted_items.append(
                    _format_evaluation(
                        eval_data, employee_names_map, criterion_names_map
                    )
                )

        if data_type in ["criteria", "all"]:
            criteria = await criterion_service.get_by_organization_id(organization_id)
            for criterion in criteria:
                formatted_items.append(_format_criterion(criterion))

        # Пагинация
        total_items = len(formatted_items)
        total_pages = (
            (total_items + items_per_page - 1) // items_per_page
            if total_items > 0
            else 1
        )

        # Ограничиваем текущую страницу
        if current_page >= total_pages:
            current_page = max(0, total_pages - 1)
            dialog_manager.dialog_data["ai_data_page"] = current_page

        start_idx = current_page * items_per_page
        end_idx = start_idx + items_per_page
        page_items = formatted_items[start_idx:end_idx]

        # Формируем текст для отображения
        data_type_names = {
            "organizations": "Организации",
            "employees": "Сотрудники",
            "evaluations": "Замеры",
            "criteria": "Критерии",
            "all": "Все данные",
        }
        type_name = data_type_names.get(data_type, "Данные")

        display_lines = [
            f"📊 <b>{type_name}</b> - Организация: {org_name}",
            f"Страница {current_page + 1} из {total_pages}",
            f"Всего объектов: {total_items}",
            "─" * 30,
        ]

        if page_items:
            display_lines.extend(page_items)
        else:
            display_lines.append("Нет данных для отображения")

        display_text = "\n".join(display_lines)

        return {
            "display_text": display_text,
            "has_prev": current_page > 0,
            "has_next": current_page < total_pages - 1,
            "current_page": current_page,
            "total_pages": total_pages,
        }

    except Exception as e:
        logger.error(f"Error loading paginated data: {e}", exc_info=True)
        return {
            "display_text": f"❌ Ошибка при загрузке данных: {str(e)}",
            "has_prev": False,
            "has_next": False,
            "current_page": 0,
            "total_pages": 0,
        }


async def _load_data_context(
    data_type: str,
    organization_id: int,
    org_name: str,
    dialog_manager,
    analytics_service,
    organization_service,
    criterion_service,
    employee_service,
) -> str:
    """Load data context from DB for AI assistant.

    Extracted as a standalone function so it can be called both from
    the getter and from the message handler (as a fallback).

    Returns:
        Formatted data context string.
    """
    context_parts: List[str] = []
    try:
        if data_type in ["organizations", "all"]:
            orgs_data = await get_organizations_list_data(dialog_manager)
            organizations = orgs_data.get("organizations", [])

            context_parts.append(f"🏢 Организации ({len(organizations)}):")
            for org in organizations[:50]:
                o_name = getattr(org, "name", "N/A")
                o_id = getattr(org, "id", "N/A")
                o_code = getattr(org, "code", "N/A")
                o_address = getattr(org, "address", None)
                o_phone = getattr(org, "phone", None)
                o_active = getattr(org, "is_active", True)
                org_info = (
                    f"  - {o_name} (ID: {o_id}, Код: {o_code}, "
                    f"Активна: {'Да' if o_active else 'Нет'}"
                )
                if o_address:
                    org_info += f", Адрес: {o_address}"
                if o_phone:
                    org_info += f", Телефон: {o_phone}"
                org_info += ")"
                context_parts.append(org_info)
            if len(organizations) > 50:
                context_parts.append(
                    f"  ... и еще {len(organizations) - 50} организаций"
                )
            context_parts.append("")

        if data_type in ["employees", "all"]:
            employees = await employee_service.get_by_organization_id(organization_id)
            context_parts.append(
                f"👥 Сотрудники организации '{org_name}' ({len(employees)}):"
            )
            for employee in employees[:100]:
                hire_date_str = (
                    employee.hire_date.strftime("%Y-%m-%d")
                    if employee.hire_date
                    else "Не указана"
                )
                context_parts.append(
                    f"  - {employee.full_name} (ID: {employee.id}, "
                    f"Должность: {employee.position or 'Не указана'}, "
                    f"Телефон: {employee.phone or 'Не указан'}, "
                    f"Telegram ID: {employee.telegram_id or 'Не указан'}, "
                    f"Username: {employee.username or 'Не указан'}, "
                    f"Дата найма: {hire_date_str}, "
                    f"Активен: {'Да' if employee.is_active else 'Нет'})"
                )
            if len(employees) > 100:
                context_parts.append(
                    f"  ... и еще {len(employees) - 100} сотрудников"
                )
            context_parts.append("")

        if data_type in ["evaluations", "all"]:
            evaluations_data = (
                await analytics_service.evaluation_repository.get_analytics_data(
                    organization_id=organization_id,
                    criterion_ids=None,
                    employee_ids=None,
                    date_from=None,
                    date_to=None,
                    evaluation_type_id=None,
                )
            )

            employee_ids_set = set()
            for eval_data in evaluations_data:
                filled_by_id = eval_data.get("filled_by_employee_id")
                evaluated_id = eval_data.get("evaluated_employee_id")
                if filled_by_id:
                    employee_ids_set.add(filled_by_id)
                if evaluated_id:
                    employee_ids_set.add(evaluated_id)

            employee_names_map = {}
            if employee_ids_set:
                employees_list = await employee_service.get_by_organization_id(
                    organization_id
                )
                for emp in employees_list:
                    if emp.id in employee_ids_set:
                        employee_names_map[emp.id] = emp.full_name

            criterion_ids_set = set()
            for eval_data in evaluations_data:
                criterion_values = eval_data.get("criterion_values", [])
                for cv in criterion_values:
                    criterion_id = cv.get("criterion_id")
                    if criterion_id:
                        criterion_ids_set.add(criterion_id)

            criterion_names_map = {}
            if criterion_ids_set:
                criteria_list = await criterion_service.get_by_organization_id(
                    organization_id
                )
                for crit in criteria_list:
                    if crit.id in criterion_ids_set:
                        criterion_names_map[crit.id] = crit.name

            context_parts.append(
                f"📊 Замеры организации '{org_name}' ({len(evaluations_data)}):"
            )

            date_stats: Dict[str, int] = defaultdict(int)
            employee_eval_stats: Dict[int, int] = defaultdict(int)

            for eval_data in evaluations_data[:100]:
                eval_id = eval_data.get("id")
                eval_date = eval_data.get("evaluation_date")
                filled_by_id = eval_data.get("filled_by_employee_id")
                evaluated_id = eval_data.get("evaluated_employee_id")
                eval_type_id = eval_data.get("evaluation_type_id")
                score = eval_data.get("score_percentage", 0.0)
                total_criteria = eval_data.get("total_criteria", 0)
                passed_criteria = eval_data.get("passed_criteria", 0)
                failed_criteria = eval_data.get("failed_criteria", 0)
                comment = eval_data.get("comment")
                status = eval_data.get("status", "unknown")
                criterion_values = eval_data.get("criterion_values", [])

                if eval_date:
                    date_stats[eval_date.strftime("%Y-%m-%d")] += 1
                if evaluated_id:
                    employee_eval_stats[evaluated_id] += 1

                filled_by_name = (
                    employee_names_map.get(filled_by_id, f"ID {filled_by_id}")
                    if filled_by_id and isinstance(filled_by_id, int)
                    else "Не указан"
                )
                evaluated_name = (
                    employee_names_map.get(evaluated_id, f"ID {evaluated_id}")
                    if evaluated_id and isinstance(evaluated_id, int)
                    else (
                        "Самозаполнение"
                        if not evaluated_id
                        else f"ID {evaluated_id}"
                    )
                )

                eval_info = (
                    f"  - Замер #{eval_id}: "
                    f"Дата: {eval_date.strftime('%Y-%m-%d %H:%M') if eval_date else 'N/A'}, "
                    f"Тип замера ID: {eval_type_id}, "
                    f"Заполнил: {filled_by_name}, "
                    f"Оцениваемый: {evaluated_name}, "
                    f"Балл: {score:.1f}%, "
                    f"Всего критериев: {total_criteria}, "
                    f"Прошло: {passed_criteria}, "
                    f"Не прошло: {failed_criteria}, "
                    f"Статус: {status}"
                )
                if comment:
                    eval_info += f", Комментарий: {comment[:100]}"
                context_parts.append(eval_info)

                if criterion_values:
                    context_parts.append(
                        f"    Значения критериев ({len(criterion_values)}):"
                    )
                    for cv in criterion_values[:10]:
                        criterion_id = cv.get("criterion_id")
                        criterion_name = criterion_names_map.get(
                            criterion_id, f"Критерий ID {criterion_id}"
                        )
                        value = cv.get("value")
                        value_type = cv.get("value_type", "boolean")
                        notes = cv.get("notes")
                        cv_info = f"      - {criterion_name}: "
                        if value_type == "boolean":
                            cv_info += f"{'Да' if value else 'Нет'}"
                        elif value_type == "number":
                            cv_info += f"{value}"
                        elif value_type == "string":
                            cv_info += f"'{value}'"
                        else:
                            cv_info += f"{value}"
                        if notes:
                            cv_info += f" (Примечание: {notes[:50]})"
                        context_parts.append(cv_info)
                    if len(criterion_values) > 10:
                        context_parts.append(
                            f"      ... и еще {len(criterion_values) - 10} значений"
                        )

            if len(evaluations_data) > 100:
                context_parts.append(
                    f"  ... и еще {len(evaluations_data) - 100} замеров"
                )
            context_parts.extend(
                [
                    "",
                    f"  Статистика: Замеров по дням: {len(date_stats)} уникальных дней, "
                    f"Сотрудников с замерами: {len(employee_eval_stats)}",
                    "",
                ]
            )

        if data_type in ["criteria", "all"]:
            criteria = await criterion_service.get_by_organization_id(organization_id)
            context_parts.append(
                f"📋 Критерии организации '{org_name}' ({len(criteria)}):"
            )
            for criterion in criteria[:100]:
                context_parts.append(
                    f"  - {criterion.name} (ID: {criterion.id}, Код: {criterion.code}, "
                    f"Тип: {criterion.value_type}, "
                    f"Категория ID: {criterion.category_id or 'Нет'}, "
                    f"Обязательный: {'Да' if criterion.is_required else 'Нет'}, "
                    f"Активен: {'Да' if criterion.is_active else 'Нет'}, "
                    f"Порядок сортировки: {criterion.sort_order}, "
                    f"Описание: {criterion.description or 'Нет'})"
                )
            if len(criteria) > 100:
                context_parts.append(f"  ... и еще {len(criteria) - 100} критериев")
            context_parts.append("")

        if data_type == "all":
            context_parts.insert(
                0,
                f"Данные для анализа организации '{org_name}' (ID: {organization_id}):",
            )
            context_parts.insert(1, "")

        data_context = "\n".join(context_parts)
        if not data_context.strip():
            data_context = f"Нет данных для типа '{data_type}' в организации '{org_name}'."
        return data_context

    except Exception as e:
        logger.error("Error loading data for AI assistant: %s", e, exc_info=True)
        return f"❌ Ошибка при загрузке данных: {e}"


@inject
async def get_ai_assistant_data(
    dialog_manager: DialogManager,
    analytics_service: AnalyticsService = Provide[Container.analytics_service],
    organization_service: OrganizationService = Provide[Container.organization_service],
    criterion_service: CriterionService = Provide[Container.criterion_service],
    employee_service: EmployeeService = Provide[Container.employee_service],
    *args,
    **kwargs,
):
    """Get data for AI assistant chat window.

    Loads analytics data from database and formats it for AI context.

    Args:
        dialog_manager: Dialog manager instance.
        analytics_service: Analytics service instance (injected).
        organization_service: Organization service instance (injected).
        criterion_service: Criterion service instance (injected).
        employee_service: Employee service instance (injected).
        *args: Variable length argument list.
        **kwargs: Arbitrary keyword arguments.

    Returns:
        Dictionary with AI assistant data including context and conversation history.
    """
    organization_id = dialog_manager.dialog_data.get("organization_id")
    data_type = dialog_manager.dialog_data.get("ai_data_type", "none")

    # Проверяем последний ответ - сначала из dialog_data, потом из персистентного хранилища
    last_response = dialog_manager.dialog_data.get("ai_last_response")
    conversation_history = dialog_manager.dialog_data.get("ai_conversation_history", [])

    if not last_response or not conversation_history:
        # Пытаемся загрузить из Redis
        user_id = None
        chat_id = None

        if dialog_manager.event:
            if (
                hasattr(dialog_manager.event, "from_user")
                and dialog_manager.event.from_user
            ):
                user_id = dialog_manager.event.from_user.id
            if hasattr(dialog_manager.event, "chat") and dialog_manager.event.chat:
                chat_id = dialog_manager.event.chat.id
            elif (
                hasattr(dialog_manager.event, "message")
                and dialog_manager.event.message
            ):
                chat_id = dialog_manager.event.message.chat.id

        if not user_id:
            user_data = dialog_manager.middleware_data.get("user_data", {})
            user_id = user_data.get("telegram_id")

        if user_id and chat_id:
            storage = dialog_manager.middleware_data.get("storage")
            if storage:
                from app.internal.usecases.ai_assistant_service import (
                    AIAssistantService,
                )

                ai_service = AIAssistantService(storage)
                stored_data = await ai_service.load_conversation_data(user_id, chat_id)

                if stored_data:
                    if not last_response:
                        last_response = stored_data.get("ai_last_response")
                    if not conversation_history:
                        conversation_history = stored_data.get(
                            "ai_conversation_history", []
                        )
                    # Восстанавливаем данные в dialog_data для совместимости
                    if last_response:
                        dialog_manager.dialog_data["ai_last_response"] = last_response
                        dialog_manager.dialog_data["ai_last_user_message"] = (
                            stored_data.get("ai_last_user_message")
                        )
                        # НЕ устанавливаем show_last_response автоматически - это будет определено позже
                        # в зависимости от того, на каком окне мы находимся
                    if conversation_history:
                        dialog_manager.dialog_data["ai_conversation_history"] = (
                            conversation_history
                        )

    # Если тип данных не выбран, работаем без данных
    if data_type == "none":
        conversation_history = dialog_manager.dialog_data.get(
            "ai_conversation_history", []
        )

        # Проверяем, находимся ли мы на окне AI-чата
        from app.tgbot.dialogs.analytics.states import AnalyticsDialog

        is_on_ai_chat_window = False
        try:
            current_context = dialog_manager.current_context()
            if (
                current_context
                and current_context.state == AnalyticsDialog.ai_assistant_chat
            ):
                is_on_ai_chat_window = True
        except Exception:
            pass

        # Check processing message first - it has priority over last_response
        # If processing is in progress, show processing message
        processing_message = dialog_manager.dialog_data.get("ai_processing_message")
        show_response = dialog_manager.dialog_data.get("show_last_response", False)
        is_error_message = last_response and last_response.startswith("❌")

        if processing_message:
            # Показываем сообщение о том, что запрос обрабатывается (приоритет)
            assistant_message = processing_message
        elif last_response and (show_response or is_error_message):
            # Есть ответ и нужно его показать, ИЛИ это сообщение об ошибке (всегда показываем)
            assistant_message = (
                "🤖 Последний ответ ассистента:\n\n"
                f"{last_response}\n\n"
                "💬 Задайте следующий вопрос:"
            )
        elif last_response and not show_response:
            # Есть ответ, но не нужно показывать - показываем кнопку
            assistant_message = (
                "💬 У вас есть новый ответ от ассистента!\n\n"
                "Нажмите кнопку '📋 Показать последний ответ', чтобы увидеть его.\n\n"
                "Или задайте новый вопрос:"
            )
        elif not conversation_history:
            assistant_message = (
                "🤖 Привет! Я ваш AI-ассистент.\n\n"
                "⚠️ <b>Важно:</b> ИИ может совершать ошибки. Пожалуйста, перепроверяйте важные данные и не полагайтесь исключительно на ответы ИИ.\n\n"
                "Вы можете задать мне любой вопрос, и я постараюсь помочь вам.\n\n"
                "Если хотите проанализировать данные из базы, вернитесь назад и выберите тип данных для загрузки."
            )
        else:
            assistant_message = "💬 Продолжаем разговор. Задайте следующий вопрос:"

        # Определяем, находимся ли мы на окне AI-чата
        is_on_ai_chat_window = False
        try:
            current_context = dialog_manager.current_context()
            if (
                current_context
                and current_context.state == AnalyticsDialog.ai_assistant_chat
            ):
                is_on_ai_chat_window = True
        except Exception:
            pass

        return {
            "assistant_message": assistant_message,
            "conversation_history": conversation_history,
            "data_context": "",
            "organization_name": "",
            "has_last_response": bool(last_response),
            "show_last_response": dialog_manager.dialog_data.get(
                "show_last_response", False
            ),
            "is_on_ai_chat_window": is_on_ai_chat_window,
        }

    if not organization_id:
        # Определяем, находимся ли мы на окне AI-чата
        is_on_ai_chat_window = False
        try:
            current_context = dialog_manager.current_context()
            if (
                current_context
                and current_context.state == AnalyticsDialog.ai_assistant_chat
            ):
                is_on_ai_chat_window = True
        except Exception:
            pass

        return {
            "assistant_message": "❌ Организация не выбрана.",
            "conversation_history": [],
            "data_context": "",
            "organization_name": "",
            "has_last_response": False,
            "show_last_response": False,
            "is_on_ai_chat_window": is_on_ai_chat_window,
        }

    # Получаем информацию об организации
    organization = await organization_service.get_by_id(organization_id)
    org_name = organization.name if organization else f"Организация #{organization_id}"

    # ──────────────────────────────────────────────────────────────
    # CACHE-FIRST: если data_context уже загружен и валиден,
    # НЕ перезагружаем из БД (предотвращает потерю данных при
    # bg.update() ре-рендере и убирает избыточные DB запросы).
    # ──────────────────────────────────────────────────────────────
    cached_context = dialog_manager.dialog_data.get("ai_data_context", "")
    if cached_context and not cached_context.startswith("❌"):
        data_context = cached_context
        logger.debug(
            "Using cached data_context (%d chars) for data_type=%s",
            len(data_context), data_type,
        )
    else:
        # Загружаем данные в зависимости от выбранного типа
        data_context = await _load_data_context(
            data_type=data_type,
            organization_id=organization_id,
            org_name=org_name,
            dialog_manager=dialog_manager,
            analytics_service=analytics_service,
            organization_service=organization_service,
            criterion_service=criterion_service,
            employee_service=employee_service,
        )
        # Cache data_context in dialog_data
        dialog_manager.dialog_data["ai_data_context"] = data_context
        logger.info(
            "Loaded and cached data_context (%d chars) for data_type=%s",
            len(data_context), data_type,
        )

    # Проверяем последний ответ
    last_response = dialog_manager.dialog_data.get("ai_last_response")

    # Получаем историю разговора из dialog_data
    conversation_history = dialog_manager.dialog_data.get("ai_conversation_history", [])

    # Формируем приветственное сообщение
    # Check processing message first - it has priority over last_response
    # If processing is in progress, show processing message
    processing_message = dialog_manager.dialog_data.get("ai_processing_message") or ""
    show_response = dialog_manager.dialog_data.get("show_last_response", False)
    is_error_message = last_response and last_response.startswith("❌")
    
    # Debug logging
    if last_response:
        logger.debug(
            f"AI response available: show_response={show_response}, "
            f"is_error={is_error_message}, has_data={bool(data_context)}"
        )

    # Telegram message limit is 4096 chars, keep some buffer
    MAX_MESSAGE_LEN = 3800
    MAX_RESPONSE_LEN = 3000
    
    if processing_message:
        # Показываем сообщение о том, что запрос обрабатывается (приоритет)
        assistant_message = processing_message
    elif last_response:
        # Если есть ответ, показываем его автоматически (если не обрабатывается запрос)
        # Это нужно для случая, когда ответ приходит через bg.update()
        # Обрезаем ответ если слишком длинный
        truncated_response = last_response
        if len(last_response) > MAX_RESPONSE_LEN:
            truncated_response = last_response[:MAX_RESPONSE_LEN] + "\n\n... (ответ обрезан из-за ограничений Telegram)"
        
        # Показываем ответ БЕЗ полного data_context (он уже в system message)
        assistant_message = (
            "🤖 Последний ответ ассистента:\n\n"
            f"{truncated_response}\n\n"
            "💬 Задайте следующий вопрос:"
        )
        
        # Проверяем общую длину и обрезаем если нужно
        if len(assistant_message) > MAX_MESSAGE_LEN:
            assistant_message = assistant_message[:MAX_MESSAGE_LEN] + "..."
    elif not conversation_history:
        data_type_names = {
            "organizations": "организаций",
            "employees": "сотрудников",
            "evaluations": "замеров",
            "criteria": "критериев",
            "all": "всех данных",
        }
        data_type_name = data_type_names.get(data_type, "данных")

        assistant_message = (
            f"🤖 Привет! Я ваш AI-ассистент для анализа данных.\n\n"
            f"⚠️ <b>Важно:</b> ИИ может совершать ошибки. Пожалуйста, перепроверяйте важные данные и не полагайтесь исключительно на ответы ИИ.\n\n"
            f"Загружены данные: {data_type_name} для организации '{org_name}'.\n\n"
            f"Задайте мне вопрос, например:\n"
        )

        if data_type in ["employees", "all"]:
            assistant_message += "• Какие сотрудники работают в организации?\n"
        if data_type in ["evaluations", "all"]:
            assistant_message += "• Какие замеры были проведены?\n"
            assistant_message += "• Какой средний балл по замерам?\n"
        if data_type in ["criteria", "all"]:
            assistant_message += "• Какие критерии используются?\n"
        if data_type == "all":
            assistant_message += "• Покажи общую статистику\n"

        assistant_message += "\nИли задайте любой другой вопрос по данным!"
    else:
        # Продолжение разговора - данные уже в system message
        assistant_message = (
            "💬 Продолжаем разговор. Задайте следующий вопрос:\n\n"
            f"📊 Данные загружены ({len(data_context)} символов)"
        )
        if len(assistant_message) > MAX_MESSAGE_LEN:
            assistant_message = assistant_message[:MAX_MESSAGE_LEN] + "..."

    # Определяем, находимся ли мы на окне AI-чата
    is_on_ai_chat_window = False
    try:
        current_context = dialog_manager.current_context()
        if (
            current_context
            and current_context.state == AnalyticsDialog.ai_assistant_chat
        ):
            is_on_ai_chat_window = True
    except Exception:
        pass

    return {
        "assistant_message": assistant_message,
        "conversation_history": conversation_history,
        "data_context": data_context,
        "organization_name": org_name,
        "has_last_response": bool(last_response),
        "show_last_response": dialog_manager.dialog_data.get(
            "show_last_response", False
        ),
        "is_on_ai_chat_window": is_on_ai_chat_window,
    }
