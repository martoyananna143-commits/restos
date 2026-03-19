"""Pydantic schemas for API request/response models."""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ==================== Organization Schemas ====================

class OrganizationBase(BaseModel):
    """Base organization schema."""
    
    name: str = Field(..., description="Organization name")
    code: str = Field(..., description="Organization code")
    address: Optional[str] = Field(None, description="Organization address")
    phone: Optional[str] = Field(None, description="Organization phone")


class OrganizationCreate(OrganizationBase):
    """Schema for creating organization."""
    pass


class OrganizationUpdate(BaseModel):
    """Schema for updating organization."""
    
    name: Optional[str] = Field(None, description="Organization name")
    code: Optional[str] = Field(None, description="Organization code")
    address: Optional[str] = Field(None, description="Organization address")
    phone: Optional[str] = Field(None, description="Organization phone")


class OrganizationResponse(OrganizationBase):
    """Schema for organization response."""
    
    id: int = Field(..., description="Organization ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    class Config:
        from_attributes = True


# ==================== Employee Schemas ====================

class EmployeeBase(BaseModel):
    """Base employee schema."""
    
    full_name: str = Field(..., description="Employee full name")
    position: Optional[str] = Field(None, description="Employee position")
    phone: Optional[str] = Field(None, description="Employee phone")


class EmployeeCreate(EmployeeBase):
    """Schema for creating employee."""
    
    organization_id: int = Field(..., description="Organization ID")
    employee_type_id: int = Field(..., description="Employee type ID")
    telegram_id: Optional[int] = Field(None, description="Telegram user ID")


class EmployeeUpdate(BaseModel):
    """Schema for updating employee."""
    
    full_name: Optional[str] = Field(None, description="Employee full name")
    position: Optional[str] = Field(None, description="Employee position")
    phone: Optional[str] = Field(None, description="Employee phone")


class EmployeeResponse(EmployeeBase):
    """Schema for employee response."""
    
    id: int = Field(..., description="Employee ID")
    organization_id: int = Field(..., description="Organization ID")
    employee_type_id: int = Field(..., description="Employee type ID")
    telegram_id: Optional[int] = Field(None, description="Telegram user ID")
    deleted_at: Optional[datetime] = Field(None, description="Deletion timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    meta: Optional[Dict[str, Any]] = Field(None, description="Employee metadata")
    
    @field_validator('meta', mode='before')
    @classmethod
    def parse_meta(cls, v):
        """Parse meta field if it's a JSON string."""
        if v is None:
            return {}
        if isinstance(v, str):
            try:
                return json.loads(v) if v else {}
            except (json.JSONDecodeError, ValueError):
                return {}
        if isinstance(v, dict):
            return v
        return {}
    
    class Config:
        from_attributes = True


# ==================== Criterion Schemas ====================

class CriterionBase(BaseModel):
    """Base criterion schema."""
    
    name: str = Field(..., description="Criterion name")
    code: str = Field(..., description="Criterion code")
    description: Optional[str] = Field(None, description="Criterion description")
    value_type: str = Field("boolean", description="Value type: boolean, string, number")


class CriterionCreate(CriterionBase):
    """Schema for creating criterion."""
    
    organization_id: int = Field(..., description="Organization ID")
    sort_order: Optional[int] = Field(None, description="Sort order")


class CriterionUpdate(BaseModel):
    """Schema for updating criterion."""
    
    name: Optional[str] = Field(None, description="Criterion name")
    code: Optional[str] = Field(None, description="Criterion code")
    description: Optional[str] = Field(None, description="Criterion description")
    value_type: Optional[str] = Field(None, description="Value type: boolean, string, number")


class CriterionResponse(CriterionBase):
    """Schema for criterion response."""
    
    id: int = Field(..., description="Criterion ID")
    organization_id: int = Field(..., description="Organization ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    class Config:
        from_attributes = True


# ==================== Criterion Set Schemas ====================

class CriterionSetBase(BaseModel):
    """Base criterion set schema."""
    
    name: str = Field(..., description="Criterion set name")
    description: Optional[str] = Field(None, description="Criterion set description")
    is_default: bool = Field(False, description="Is default set")


class CriterionSetCreate(CriterionSetBase):
    """Schema for creating criterion set."""
    
    organization_id: int = Field(..., description="Organization ID")
    criterion_ids: List[int] = Field(..., description="List of criterion IDs")


class CriterionSetUpdate(BaseModel):
    """Schema for updating criterion set."""
    
    name: Optional[str] = Field(None, description="Criterion set name")
    description: Optional[str] = Field(None, description="Criterion set description")
    is_default: Optional[bool] = Field(None, description="Is default set")
    criterion_ids: Optional[List[int]] = Field(None, description="List of criterion IDs")


class CriterionSetResponse(CriterionSetBase):
    """Schema for criterion set response."""
    
    id: int = Field(..., description="Criterion set ID")
    organization_id: int = Field(..., description="Organization ID")
    criterion_ids: Optional[List[int]] = Field(None, description="List of criterion IDs")
    created_at: datetime = Field(..., description="Creation timestamp")
    deleted_at: Optional[datetime] = Field(None, description="Deletion timestamp")
    
    class Config:
        from_attributes = True


# ==================== Evaluation Schemas ====================

class EvaluationBase(BaseModel):
    """Base evaluation schema."""
    
    evaluation_date: datetime = Field(..., description="Evaluation date")


class EvaluationCreate(EvaluationBase):
    """Schema for creating evaluation."""
    
    filled_by_employee_id: int = Field(..., description="Employee who filled the evaluation")
    evaluated_employee_id: int = Field(..., description="Employee being evaluated")
    criterion_set_id: int = Field(..., description="Criterion set ID")
    criterion_values: Dict[int, Any] = Field(..., description="Criterion values: {criterion_id: value}")
    comments: Optional[Dict[int, str]] = Field(None, description="Comments: {criterion_id: comment}")


class EvaluationUpdate(BaseModel):
    """Schema for updating evaluation."""
    
    evaluation_date: Optional[datetime] = Field(None, description="Evaluation date")
    criterion_values: Optional[Dict[int, Any]] = Field(None, description="Criterion values")
    comments: Optional[Dict[int, str]] = Field(None, description="Comments")


class EvaluationResponse(EvaluationBase):
    """Schema for evaluation response."""
    
    id: int = Field(..., description="Evaluation ID")
    filled_by_employee_id: int = Field(..., description="Employee who filled the evaluation")
    evaluated_employee_id: int = Field(..., description="Employee being evaluated")
    criterion_set_id: int = Field(..., description="Criterion set ID")
    score_total: Optional[float] = Field(None, description="Total score")
    score_percentage: Optional[float] = Field(None, description="Score percentage")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    class Config:
        from_attributes = True


# ==================== Evaluation Type Schemas ====================

class EvaluationTypeBase(BaseModel):
    """Base evaluation type schema."""
    
    name: str = Field(..., description="Evaluation type name")
    code: str = Field(..., description="Evaluation type code")
    description: Optional[str] = Field(None, description="Evaluation type description")


class EvaluationTypeCreate(EvaluationTypeBase):
    """Schema for creating evaluation type."""
    
    organization_id: int = Field(..., description="Organization ID")


class EvaluationTypeUpdate(BaseModel):
    """Schema for updating evaluation type."""
    
    name: Optional[str] = Field(None, description="Evaluation type name")
    code: Optional[str] = Field(None, description="Evaluation type code")
    description: Optional[str] = Field(None, description="Evaluation type description")


class EvaluationTypeResponse(EvaluationTypeBase):
    """Schema for evaluation type response."""
    
    id: int = Field(..., description="Evaluation type ID")
    organization_id: Optional[int] = Field(None, description="Organization ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    class Config:
        from_attributes = True


# ==================== Analytics Schemas ====================

class AnalyticsFilters(BaseModel):
    """Schema for analytics filters."""
    
    criterion_ids: Optional[List[int]] = Field(None, description="List of criterion IDs")
    employee_ids: Optional[List[int]] = Field(None, description="List of employee IDs")
    date_from: Optional[datetime] = Field(None, description="Start date")
    date_to: Optional[datetime] = Field(None, description="End date")
    evaluation_type_id: Optional[int] = Field(None, description="Evaluation type ID")
    min_score: Optional[float] = Field(None, description="Minimum score")
    max_score: Optional[float] = Field(None, description="Maximum score")


class CriteriaStatisticsRequest(AnalyticsFilters):
    """Schema for criteria statistics request."""
    
    organization_id: int = Field(..., description="Organization ID")


class AverageScoresRequest(BaseModel):
    """Schema for average scores request."""
    
    organization_id: int = Field(..., description="Organization ID")
    criterion_ids: Optional[List[int]] = Field(None, description="List of criterion IDs")
    employee_ids: Optional[List[int]] = Field(None, description="List of employee IDs")
    date_from: Optional[datetime] = Field(None, description="Start date")
    date_to: Optional[datetime] = Field(None, description="End date")
    group_by: str = Field("criterion", description="Grouping: criterion, employee, date")


class CustomQueryRequest(BaseModel):
    """Schema for custom query request."""
    
    organization_id: int = Field(..., description="Organization ID")
    filters: Dict[str, Any] = Field(..., description="Filter parameters")


# ==================== Invitation Schemas ====================

class InvitationCreate(BaseModel):
    """Schema for creating invitation."""
    
    inviter_telegram_id: int = Field(..., description="Telegram ID of inviter")
    organization_id: int = Field(..., description="Organization ID")
    ttl: int = Field(604800, description="Time to live in seconds (default 7 days)")


class InvitationResponse(BaseModel):
    """Schema for invitation response."""
    
    code: str = Field(..., description="Invitation code")
    inviter_telegram_id: int = Field(..., description="Telegram ID of inviter")
    organization_id: int = Field(..., description="Organization ID")
    used: bool = Field(..., description="Whether invitation is used")


# ==================== User Schemas ====================

class UserBase(BaseModel):
    """Base user schema."""
    
    telegram_id: int = Field(..., description="Telegram user ID")
    username: Optional[str] = Field(None, description="Telegram username")
    first_name: Optional[str] = Field(None, description="First name")
    last_name: Optional[str] = Field(None, description="Last name")


class UserCreate(UserBase):
    """Schema for creating user."""
    
    chat_id: int = Field(..., description="Chat ID")
    is_verified: bool = Field(False, description="Is user verified")
    is_active: bool = Field(True, description="Is user active")


class UserResponse(UserBase):
    """Schema for user response."""
    
    id: int = Field(..., description="User ID")
    chat_id: int = Field(..., description="Chat ID")
    is_verified: bool = Field(..., description="Is user verified")
    is_active: bool = Field(..., description="Is user active")
    created_at: datetime = Field(..., description="Creation timestamp")
    
    class Config:
        from_attributes = True


# ==================== General Schemas ====================

class MessageResponse(BaseModel):
    """Generic message response."""
    
    message: str = Field(..., description="Response message")
    success: bool = Field(True, description="Operation success status")


class ErrorResponse(BaseModel):
    """Error response schema."""
    
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Error details")
