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
from app.candidate_profile.access import ContactGrant
from app.candidate_profile.models import (
    CandidateContact,
    CandidateEmployerBlock,
    CandidateProfile,
    CandidateTechnology,
)
from app.catalog.models import Category, Grade, Skill, Specialization, Technology
from app.employer.models import EmployerProfile
from app.fsp.models import FspLink
from app.invitations.models import Invitation
from app.matching.models import (
    CandidateNeedMark,
    EmployerNeed,
    MatchingSnapshot,
    NeedVersion,
)
from app.notifications.models import AuditEvent, BackgroundJob
from app.vacancies.models import Application, Vacancy

__all__ = [
    "Application",
    "Vacancy",
    "Invitation",
    "ContactGrant",
    "CandidateNeedMark",
    "EmployerNeed",
    "MatchingSnapshot",
    "NeedVersion",
    "FspLink",
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
