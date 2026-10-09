"""Регистрация моделей для единой схемы Alembic."""

from app.assessment.models import (
    AssessmentAnswer,
    AssessmentAppeal,
    AssessmentCycle,
    AssessmentPublication,
    AssessmentSurvey,
    FamilyExposure,
)
from app.auth.models import (
    AuthActionToken,
    AuthRateBucket,
    AuthSession,
    UsedRefreshToken,
    User,
    UserIdentity,
)
from app.candidate_profile.models import (
    CandidateContact,
    CandidateEmployerBlock,
    CandidateProfile,
    CandidateTechnology,
)
from app.catalog.models import Category, Grade, Skill, Specialization, Technology
from app.employer.models import EmployerProfile
from app.notifications.models import AuditEvent, BackgroundJob

__all__ = [
    "AssessmentAnswer",
    "AssessmentAppeal",
    "AssessmentCycle",
    "AssessmentPublication",
    "AssessmentSurvey",
    "FamilyExposure",
    "AuthActionToken",
    "AuthRateBucket",
    "AuthSession",
    "UsedRefreshToken",
    "User",
    "UserIdentity",
    "CandidateContact",
    "CandidateEmployerBlock",
    "CandidateProfile",
    "CandidateTechnology",
    "Category",
    "Grade",
    "Skill",
    "Specialization",
    "Technology",
    "EmployerProfile",
    "AuditEvent",
    "BackgroundJob",
]
