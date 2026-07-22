"""Analytics API router."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_employee
from app.api.deps import get_analytics_service
from app.api.schemas import (
    AverageScoresRequest,
    CriteriaStatisticsRequest,
    CustomQueryRequest,
)
from app.infra.database.models.employee.employee import Employee
from app.internal.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.post("/criteria-statistics", response_model=Dict[str, Any])
async def get_criteria_statistics(
    data: CriteriaStatisticsRequest,
    employee: Employee = Depends(get_current_employee),
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Get statistics by criteria.
    
    Requires employee access to the organization.
    
    Args:
        data: Criteria statistics request parameters.
        employee: Authenticated employee in organization.
        service: Analytics service dependency.
        
    Returns:
        Dictionary with criteria statistics.
        
    Raises:
        HTTPException: If access denied or request fails.
    """
    # Verify employee has access to this organization
    if employee.organization_id != data.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    try:
        statistics = await service.get_criteria_statistics(
            organization_id=data.organization_id,
            criterion_ids=data.criterion_ids,
            employee_ids=data.employee_ids,
            date_from=data.date_from,
            date_to=data.date_to,
            evaluation_type_id=data.evaluation_type_id,
        )
        return statistics
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get criteria statistics: {str(e)}",
        )


@router.post("/average-scores", response_model=Dict[str, Any])
async def get_average_scores(
    data: AverageScoresRequest,
    employee: Employee = Depends(get_current_employee),
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Get average scores.
    
    Requires employee access to the organization.
    
    Args:
        data: Average scores request parameters.
        employee: Authenticated employee in organization.
        service: Analytics service dependency.
        
    Returns:
        Dictionary with average scores.
        
    Raises:
        HTTPException: If access denied or request fails.
    """
    # Verify employee has access to this organization
    if employee.organization_id != data.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    try:
        # Validate group_by parameter
        valid_group_by = ["criterion", "employee", "date"]
        if data.group_by not in valid_group_by:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid group_by value. Must be one of: {', '.join(valid_group_by)}",
            )
        
        averages = await service.get_average_scores(
            organization_id=data.organization_id,
            criterion_ids=data.criterion_ids,
            employee_ids=data.employee_ids,
            date_from=data.date_from,
            date_to=data.date_to,
            group_by=data.group_by,
        )
        return averages
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get average scores: {str(e)}",
        )


@router.post("/custom-query", response_model=Dict[str, Any])
async def execute_custom_query(
    data: CustomQueryRequest,
    employee: Employee = Depends(get_current_employee),
    service: AnalyticsService = Depends(get_analytics_service),
):
    """Execute custom analytics query with flexible filters.
    
    Requires employee access to the organization.
    
    Args:
        data: Custom query request parameters.
        employee: Authenticated employee in organization.
        service: Analytics service dependency.
        
    Returns:
        Dictionary with query results.
        
    Raises:
        HTTPException: If access denied or request fails.
    """
    # Verify employee has access to this organization
    if employee.organization_id != data.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this organization",
        )
    
    try:
        results = await service.get_custom_query(
            organization_id=data.organization_id,
            filters=data.filters,
        )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute custom query: {str(e)}",
        )
