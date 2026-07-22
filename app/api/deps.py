"""FastAPI dependencies for dependency injection."""

from typing import AsyncGenerator

from dependency_injector.wiring import Provide, inject
from fastapi import Depends

from app.internal import Container
from app.internal.services.ai_assistant_service import AIAssistantService
from app.internal.services.analytics_service import AnalyticsService
from app.internal.services.criterion_service import CriterionService
from app.internal.services.criterion_set_service import CriterionSetService
from app.internal.services.employee_service import EmployeeService
from app.internal.services.evaluation_service import EvaluationService
from app.internal.services.evaluation_type_service import EvaluationTypeService
from app.internal.services.invitation_service import InvitationService
from app.internal.services.organization_service import OrganizationService
from app.internal.services.user_service import UserService
from app.internal.services.excel_report_service import ExcelReportService
from app.internal.services.google_criterion_sync_service import GoogleCriterionSyncService
from app.internal.services.google_drive_service import GoogleDriveService
from app.internal.services.google_sheet_service import GoogleSheetService
from app.internal.services.pdf_report_service import PDFReportService
from app.infra.database.repository.criterion_value.criterion_value_asyncpg import (
    CriterionValueRepositoryAsyncpg,
)


@inject
async def get_organization_service(
    service: OrganizationService = Depends(Provide[Container.organization_service]),
) -> OrganizationService:
    """Get organization service dependency.
    
    Args:
        service: Injected organization service.
    
    Returns:
        OrganizationService instance.
    """
    return service


@inject
async def get_employee_service(
    service: EmployeeService = Depends(Provide[Container.employee_service]),
) -> EmployeeService:
    """Get employee service dependency.
    
    Args:
        service: Injected employee service.
    
    Returns:
        EmployeeService instance.
    """
    return service


@inject
async def get_criterion_service(
    service: CriterionService = Depends(Provide[Container.criterion_service]),
) -> CriterionService:
    """Get criterion service dependency.
    
    Args:
        service: Injected criterion service.
    
    Returns:
        CriterionService instance.
    """
    return service


@inject
async def get_criterion_set_service(
    service: CriterionSetService = Depends(Provide[Container.criterion_set_service]),
) -> CriterionSetService:
    """Get criterion set service dependency.
    
    Args:
        service: Injected criterion set service.
    
    Returns:
        CriterionSetService instance.
    """
    return service


@inject
async def get_evaluation_service(
    service: EvaluationService = Depends(Provide[Container.evaluation_service]),
) -> EvaluationService:
    """Get evaluation service dependency.
    
    Args:
        service: Injected evaluation service.
    
    Returns:
        EvaluationService instance.
    """
    return service


@inject
async def get_evaluation_type_service(
    service: EvaluationTypeService = Depends(Provide[Container.evaluation_type_service]),
) -> EvaluationTypeService:
    """Get evaluation type service dependency.
    
    Args:
        service: Injected evaluation type service.
    
    Returns:
        EvaluationTypeService instance.
    """
    return service


@inject
async def get_analytics_service(
    service: AnalyticsService = Depends(Provide[Container.analytics_service]),
) -> AnalyticsService:
    """Get analytics service dependency.
    
    Args:
        service: Injected analytics service.
    
    Returns:
        AnalyticsService instance.
    """
    return service


@inject
async def get_invitation_service(
    service: InvitationService = Depends(Provide[Container.invitation_service]),
) -> InvitationService:
    """Get invitation service dependency.
    
    Args:
        service: Injected invitation service.
    
    Returns:
        InvitationService instance.
    """
    return service


@inject
async def get_user_service(
    service: UserService = Depends(Provide[Container.user_service]),
) -> UserService:
    """Get user service dependency.
    
    Args:
        service: Injected user service.
    
    Returns:
        UserService instance.
    """
    return service


@inject
async def get_excel_report_service(
    service: ExcelReportService = Depends(Provide[Container.excel_report_service]),
) -> ExcelReportService:
    """Get Excel report service dependency.
    
    Args:
        service: Injected Excel report service.
    
    Returns:
        ExcelReportService instance.
    """
    return service


@inject
async def get_pdf_report_service(
    service: PDFReportService = Depends(Provide[Container.pdf_report_service]),
) -> PDFReportService:
    """Get PDF report service dependency.
    
    Args:
        service: Injected PDF report service.
    
    Returns:
        PDFReportService instance.
    """
    return service


@inject
async def get_criterion_value_repository(
    repo: CriterionValueRepositoryAsyncpg = Depends(Provide[Container.criterion_value_repository]),
) -> CriterionValueRepositoryAsyncpg:
    """Get criterion value repository dependency.
    
    Args:
        repo: Injected criterion value repository.
    
    Returns:
        CriterionValueRepositoryAsyncpg instance.
    """
    return repo


@inject
async def get_ai_assistant_service(
    service: AIAssistantService = Depends(Provide[Container.ai_assistant_service]),
) -> AIAssistantService:
    """Get AI assistant service dependency.

    Args:
        service: Injected AI assistant service.

    Returns:
        AIAssistantService instance.
    """
    return service


@inject
async def get_google_sheet_service(
    service: GoogleSheetService = Depends(Provide[Container.google_sheet_service]),
) -> GoogleSheetService:
    return service


@inject
async def get_google_drive_service(
    service: GoogleDriveService = Depends(Provide[Container.google_drive_service]),
) -> GoogleDriveService:
    return service


@inject
async def get_google_criterion_sync_service(
    service: GoogleCriterionSyncService = Depends(Provide[Container.google_criterion_sync_service]),
) -> GoogleCriterionSyncService:
    return service
