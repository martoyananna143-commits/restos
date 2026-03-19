"""Handlers for export dialog."""

from aiogram import Bot
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager, StartMode
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.infra.database.repository.criterion_value.criterion_value_asyncpg import (
    CriterionValueRepositoryAsyncpg,
)
from app.internal import Container
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.excel_report_service import ExcelReportService
from app.internal.usecases.pdf_report_service import PDFReportService
from app.tgbot.dialogs.greeting.states import GreetingDialog
from app.tgbot.services import broadcaster


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
    """Handle generate PDF button click."""
    data = dialog_manager.dialog_data

    try:
        evaluation_id = data.get("evaluation_id")
        if not evaluation_id:
            await callback.answer("Ошибка: ID оценки не найден", show_alert=True)
            return

        # Load criteria values from database
        criterion_values = await criterion_value_repo.get_by_evaluation_id(evaluation_id)
        criterion_ids = [cv.criterion_id for cv in criterion_values]
        criteria_objs = await criterion_service.get_by_ids(criterion_ids)
        criteria_map = {c.id: c for c in criteria_objs}

        # Build criteria list
        criteria_list = []
        for cv in criterion_values:
            crit = criteria_map.get(cv.criterion_id)
            criteria_list.append({
                "name": crit.name if crit else f"Критерий {cv.criterion_id}",
                "value": cv.value,
                "value_type": crit.value_type if crit else "boolean",
                "comment": cv.notes or "",
            })

        # Generate PDF
        pdf_path = pdf_report_service.generate_evaluation_report(
            evaluation_id=evaluation_id,
            evaluation_type_name=data.get("evaluation_type_name", "Оценка"),
            organization_name=data.get("organization_name", "Не указано"),
            evaluated_employee_name=data.get("evaluated_employee_name", "Не указано"),
            filled_by_employee_name=data.get("filled_by_employee_name", "Не указано"),
            evaluation_date=data.get("evaluation_date"),
            criteria=criteria_list,
            total_criteria=data.get("total_criteria", len(criteria_list)),
            passed_criteria=data.get("passed_criteria", 0),
            failed_criteria=data.get("failed_criteria", 0),
            score_percentage=data.get("score_percentage", 0.0),
            criterion_set_name=data.get("criterion_set_name"),
            boolean_criteria_count=(data.get("passed_criteria", 0) + data.get("failed_criteria", 0)),
        )

        # Send PDF
        bot = dialog_manager.middleware_data.get("bot")
        if not bot and dialog_manager.event:
            bot = getattr(dialog_manager.event, "bot", None)

        if bot and isinstance(bot, Bot) and callback.from_user:
            await broadcaster.send_document(
                bot,
                callback.from_user.id,
                pdf_path,
                caption=f"📄 PDF отчет по оценке #{evaluation_id}",
            )

        dialog_manager.dialog_data["pdf_generated"] = True
        await callback.answer("PDF отчет отправлен!")

    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


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
    """Handle generate Excel button click."""
    data = dialog_manager.dialog_data

    try:
        evaluation_id = data.get("evaluation_id")
        if not evaluation_id:
            await callback.answer("Ошибка: ID оценки не найден", show_alert=True)
            return

        # Load criteria values from database
        criterion_values = await criterion_value_repo.get_by_evaluation_id(evaluation_id)
        criterion_ids = [cv.criterion_id for cv in criterion_values]
        criteria_objs = await criterion_service.get_by_ids(criterion_ids)
        criteria_map = {c.id: c for c in criteria_objs}

        # Build criteria list
        criteria_list = []
        for cv in criterion_values:
            crit = criteria_map.get(cv.criterion_id)
            criteria_list.append({
                "name": crit.name if crit else f"Критерий {cv.criterion_id}",
                "value": cv.value,
                "value_type": crit.value_type if crit else "boolean",
                "comment": cv.notes or "",
            })

        # Generate Excel
        excel_path = excel_report_service.generate_evaluation_report(
            evaluation_id=evaluation_id,
            evaluation_type_name=data.get("evaluation_type_name", "Оценка"),
            organization_name=data.get("organization_name", "Не указано"),
            evaluated_employee_name=data.get("evaluated_employee_name", "Не указано"),
            filled_by_employee_name=data.get("filled_by_employee_name", "Не указано"),
            evaluation_date=data.get("evaluation_date"),
            criteria=criteria_list,
            total_criteria=data.get("total_criteria", len(criteria_list)),
            passed_criteria=data.get("passed_criteria", 0),
            failed_criteria=data.get("failed_criteria", 0),
            score_percentage=data.get("score_percentage", 0.0),
            criterion_set_name=data.get("criterion_set_name"),
            boolean_criteria_count=(data.get("passed_criteria", 0) + data.get("failed_criteria", 0)),
        )

        # Send Excel
        bot = dialog_manager.middleware_data.get("bot")
        if not bot and dialog_manager.event:
            bot = getattr(dialog_manager.event, "bot", None)

        if bot and isinstance(bot, Bot) and callback.from_user:
            await broadcaster.send_document(
                bot,
                callback.from_user.id,
                excel_path,
                caption=f"📊 Excel отчет по оценке #{evaluation_id}",
            )

        dialog_manager.dialog_data["excel_generated"] = True
        await callback.answer("Excel отчет отправлен!")

    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)


async def on_done(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
):
    """Handle done button - return to greeting."""
    await dialog_manager.start(
        GreetingDialog.greeting,
        mode=StartMode.RESET_STACK,
    )
