"""Регистрация моделей для единой схемы Alembic."""

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
