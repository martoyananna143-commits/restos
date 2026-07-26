"""Universal assessment-template foundation models."""

from app.infra.database.models.assessment_template.assessment_template import (
    AssessmentMethodology,
    AssessmentTemplate,
    AssessmentTemplateItem,
    AssessmentTemplateItemOption,
    AssessmentTemplateSection,
    AssessmentTemplateVersion,
)

__all__ = [
    "AssessmentMethodology",
    "AssessmentTemplate",
    "AssessmentTemplateVersion",
    "AssessmentTemplateSection",
    "AssessmentTemplateItem",
    "AssessmentTemplateItemOption",
]
