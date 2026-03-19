"""FastAPI dependencies for dependency injection."""

from typing import AsyncGenerator

from dependency_injector.wiring import Provide, inject
from fastapi import Depends

from app.internal import Container
from app.internal.usecases.analytics_service import AnalyticsService
from app.internal.usecases.criterion_service import CriterionService
from app.internal.usecases.criterion_set_service import CriterionSetService
from app.internal.usecases.employee_service import EmployeeService
from app.internal.usecases.evaluation_service import EvaluationService
from app.internal.usecases.evaluation_type_service import EvaluationTypeService
from app.internal.usecases.invitation_service import InvitationService
from app.internal.usecases.organization_service import OrganizationService
from app.internal.usecases.user_service import UserService
from app.internal.usecases.excel_report_service import ExcelReportService
from app.internal.usecases.pdf_report_service import PDFReportService
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
