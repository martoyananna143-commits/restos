"""Handlers for help dialog."""

import logging

from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import Button
from dependency_injector.wiring import Provide, inject

from app.internal import Container
from app.internal.usecases.organization_service import OrganizationService
from app.tgbot.dialogs.help.states import HelpDialog
from app.tgbot.dialogs.organization.states import OrganizationDialog

logger = logging.getLogger(__name__)


async def on_start_tutorial(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Start the tutorial from step 1."""
    await dialog_manager.switch_to(HelpDialog.step_1_welcome)


async def on_next_step(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate to next tutorial step."""

    current_state = dialog_manager.current_context().state if dialog_manager.current_context() else None

    # Define the flow of tutorial steps
    step_flow = {
        HelpDialog.step_1_welcome: HelpDialog.step_2_organization,
        HelpDialog.step_2_organization: HelpDialog.step_3_employees,
        HelpDialog.step_3_employees: HelpDialog.step_4_criteria,
        HelpDialog.step_4_criteria: HelpDialog.step_5_sets,
        HelpDialog.step_5_sets: HelpDialog.step_6_evaluation,
        HelpDialog.step_6_evaluation: HelpDialog.step_7_analytics,
        HelpDialog.step_7_analytics: HelpDialog.step_8_advanced,
        HelpDialog.step_8_advanced: HelpDialog.final_step,
    }

    next_state = step_flow.get(current_state) if current_state else None
    if next_state:
        await dialog_manager.switch_to(next_state)


async def on_prev_step(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate to previous tutorial step."""

    current_state = dialog_manager.current_context().state if dialog_manager.current_context() else None

    # Define reverse flow of tutorial steps
    reverse_flow = {
        HelpDialog.step_2_organization: HelpDialog.step_1_welcome,
        HelpDialog.step_3_employees: HelpDialog.step_2_organization,
        HelpDialog.step_4_criteria: HelpDialog.step_3_employees,
        HelpDialog.step_5_sets: HelpDialog.step_4_criteria,
        HelpDialog.step_6_evaluation: HelpDialog.step_5_sets,
        HelpDialog.step_7_analytics: HelpDialog.step_6_evaluation,
        HelpDialog.step_8_advanced: HelpDialog.step_7_analytics,
        HelpDialog.final_step: HelpDialog.step_8_advanced,
    }

    prev_state = reverse_flow.get(current_state) if current_state else None
    if prev_state:
        await dialog_manager.switch_to(prev_state)


# Individual handlers for each step navigation
async def on_step_1_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 1 to step 2."""
    await dialog_manager.switch_to(HelpDialog.step_2_organization)


async def on_step_2_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 2 to step 3."""
    await dialog_manager.switch_to(HelpDialog.step_3_employees)


async def on_step_2_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 2 to step 1."""
    await dialog_manager.switch_to(HelpDialog.step_1_welcome)


async def on_step_3_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 3 to step 4."""
    await dialog_manager.switch_to(HelpDialog.step_4_criteria)


async def on_step_3_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 3 to step 2."""
    await dialog_manager.switch_to(HelpDialog.step_2_organization)


async def on_step_4_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 4 to step 5."""
    await dialog_manager.switch_to(HelpDialog.step_5_sets)


async def on_step_4_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 4 to step 3."""
    await dialog_manager.switch_to(HelpDialog.step_3_employees)


async def on_step_5_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 5 to step 6."""
    await dialog_manager.switch_to(HelpDialog.step_6_evaluation)


async def on_step_5_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 5 to step 4."""
    await dialog_manager.switch_to(HelpDialog.step_4_criteria)


async def on_step_6_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 6 to step 7."""
    await dialog_manager.switch_to(HelpDialog.step_7_analytics)


async def on_step_6_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 6 to step 5."""
    await dialog_manager.switch_to(HelpDialog.step_5_sets)


async def on_step_7_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 7 to step 8."""
    await dialog_manager.switch_to(HelpDialog.step_8_advanced)


async def on_step_7_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 7 to step 6."""
    await dialog_manager.switch_to(HelpDialog.step_6_evaluation)


async def on_step_8_next(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 8 to final step."""
    await dialog_manager.switch_to(HelpDialog.final_step)


async def on_step_8_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from step 8 to step 7."""
    await dialog_manager.switch_to(HelpDialog.step_7_analytics)


async def on_final_prev(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Navigate from final step to step 8."""
    await dialog_manager.switch_to(HelpDialog.step_8_advanced)


async def on_back_to_help_main(
    callback: CallbackQuery, button: Button, dialog_manager: DialogManager
):
    """Go back to main help menu."""
    await dialog_manager.switch_to(HelpDialog.main_help)


@inject
async def on_cancel_help(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Handle cancel button in help dialog - check if user needs to create organization."""
    # Get telegram_id from callback first, then from dialog_manager.event, then from user_data
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id
    elif dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    else:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")
    
    if telegram_id:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if not organization:
            # User doesn't have organization, redirect to organization creation
            await dialog_manager.done()
            await dialog_manager.start(OrganizationDialog.check_organization)
            return
    
    # User has organization, just close help dialog
    await dialog_manager.done()


@inject
async def on_finish_tutorial(
    callback: CallbackQuery,
    button: Button,
    dialog_manager: DialogManager,
    organization_service: OrganizationService = Provide[Container.organization_service],
):
    """Finish tutorial and check if user needs to create organization."""
    await callback.answer("🎉 Поздравляем! Вы прошли обучение!")
    
    # Get telegram_id from callback first, then from dialog_manager.event, then from user_data
    telegram_id = None
    if callback.from_user:
        telegram_id = callback.from_user.id
    elif dialog_manager.event and hasattr(dialog_manager.event, "from_user") and dialog_manager.event.from_user:
        telegram_id = dialog_manager.event.from_user.id
    else:
        user_data = dialog_manager.middleware_data.get("user_data", {})
        telegram_id = user_data.get("telegram_id")
    
    if telegram_id:
        organization = await organization_service.get_by_user_telegram_id(telegram_id)
        if not organization:
            # User doesn't have organization, redirect to organization creation
            await dialog_manager.done()
            await dialog_manager.start(OrganizationDialog.check_organization)
            return
    
    # User has organization, just close help dialog
    await dialog_manager.done()
