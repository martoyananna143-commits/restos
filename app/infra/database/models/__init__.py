"""Database models package."""

from app.infra.database.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.infra.database.models.account import (
    Account,
    AccountDevice,
    AccountIdentity,
    AccountSession,
)
from app.infra.database.models.account_legal_acceptance import AccountLegalAcceptance
from app.infra.database.models.account_webauthn_challenge import (
    AccountWebAuthnChallenge,
)
from app.infra.database.models.access_profile import (
    AccessProfile,
    AccessProfilePermission,
)
from app.infra.database.models.assessment_template import (
    AssessmentMethodology,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
)
from app.infra.database.models.assessment_attempt import (
    AssessmentAssignment,
    AssessmentAttempt,
    AssessmentAttemptAnswer,
)
from app.infra.database.models.assessment_metric import (
    AssessmentAggregationPolicy,
    AssessmentItemMetricMapping,
    AssessmentMetricDefinition,
    AssessmentMetricObservation,
    AssessmentProductMeasurement,
    AssessmentProductMeasurementItem,
    AssessmentScoringPolicy,
    AssessmentTemplateImportSource,
)
from app.infra.database.models.employee import Employee, EmployeeType
from app.infra.database.models.employee_assignment import (
    AssignmentScopeVenue,
    AssignmentVenue,
    EmployeeAssignment,
)
from app.infra.database.models.employee_profile import (
    EmployeeBirthDateAudit,
    EmployeeProfile,
)
from app.infra.database.models.device_registration_challenge import (
    DeviceRegistrationChallenge,
)
from app.infra.database.models.invitation_v1 import (
    Invitation,
    InvitationScopeVenue,
    InvitationVenue,
)
from app.infra.database.models.company import Company
from app.infra.database.models.evaluation import (
    Category,
    Criterion,
    CriterionValue,
    Evaluation,
    EvaluationType,
)
from app.infra.database.models.organization import Organization
from app.infra.database.models.position import Position
from app.infra.database.models.phone_verification_challenge import (
    PhoneVerificationChallenge,
)
from app.infra.database.models.organization_workflow import (
    GroupInvitation,
    GroupInvitationRegistration,
    Task,
    TaskAssignment,
    TaskEvent,
    TaskPhoto,
)
from app.infra.database.models.user import User
from app.infra.database.models.venue import Venue

__all__ = [
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    "Account",
    "AccountIdentity",
    "AccountDevice",
    "AccountSession",
    "AccountLegalAcceptance",
    "AccountWebAuthnChallenge",
    "AccessProfile",
    "AccessProfilePermission",
    "AssessmentMethodology",
    "AssessmentTemplate",
    "AssessmentTemplateVersion",
    "AssessmentTemplateSection",
    "AssessmentTemplateItem",
    "AssessmentTemplateItemOption",
    "AssessmentAssignment",
    "AssessmentAttempt",
    "AssessmentAttemptAnswer",
    "AssessmentMetricDefinition",
    "AssessmentScoringPolicy",
    "AssessmentItemMetricMapping",
    "AssessmentMetricObservation",
    "AssessmentAggregationPolicy",
    "AssessmentTemplateImportSource",
    "AssessmentProductMeasurement",
    "AssessmentProductMeasurementItem",
    "Company",
    "Venue",
    "Position",
    "EmployeeProfile",
    "EmployeeBirthDateAudit",
    "DeviceRegistrationChallenge",
    "EmployeeAssignment",
    "AssignmentVenue",
    "AssignmentScopeVenue",
    "Invitation",
    "InvitationVenue",
    "InvitationScopeVenue",
    "PhoneVerificationChallenge",
    "GroupInvitation",
    "GroupInvitationRegistration",
    "Task",
    "TaskAssignment",
    "TaskPhoto",
    "TaskEvent",
    "Organization",
    "EmployeeType",
    "Employee",
    "EvaluationType",
    "Category",
    "Criterion",
    "CriterionValue",
    "Evaluation",
    "User",
]
