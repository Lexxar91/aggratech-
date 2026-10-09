"""Учётные записи, профили, закрытые контакты и справочники этапа 2."""

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

revision = "0002_auth_profiles"
down_revision = "0001_background_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Применяет неизменяемую PostgreSQL-схему и начальные справочники."""
    op.execute("""
CREATE TABLE auth_rate_buckets (
    key VARCHAR(64) NOT NULL, 
    count INTEGER NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_auth_rate_buckets PRIMARY KEY (key)
)
""")
    op.execute("""
CREATE TABLE grades (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(128) NOT NULL, 
    sort_order INTEGER NOT NULL, 
    active BOOLEAN NOT NULL, 
    CONSTRAINT pk_grades PRIMARY KEY (id), 
    CONSTRAINT uq_grades_code UNIQUE (code)
)
""")
    op.execute("""
CREATE TABLE specializations (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(128) NOT NULL, 
    active BOOLEAN NOT NULL, 
    CONSTRAINT pk_specializations PRIMARY KEY (id), 
    CONSTRAINT uq_specializations_code UNIQUE (code)
)
""")
    op.execute("""
CREATE TABLE technologies (
    id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(128) NOT NULL, 
    active BOOLEAN NOT NULL, 
    CONSTRAINT pk_technologies PRIMARY KEY (id), 
    CONSTRAINT uq_technologies_code UNIQUE (code)
)
""")
    op.execute("""
CREATE TABLE users (
    id UUID NOT NULL, 
    email_normalized VARCHAR(254) NOT NULL, 
    password_hash VARCHAR(512) NOT NULL, 
    role VARCHAR(16) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    email_verified_at TIMESTAMP WITH TIME ZONE, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_users PRIMARY KEY (id), 
    CONSTRAINT ck_users_role CHECK (role IN ('candidate','employer','staff')), 
    CONSTRAINT ck_users_status CHECK (status IN ('active','disabled')), 
    CONSTRAINT uq_users_email_normalized UNIQUE (email_normalized)
)
""")
    op.execute("""
CREATE TABLE auth_action_tokens (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    purpose VARCHAR(32) NOT NULL, 
    token_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    used_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_auth_action_tokens PRIMARY KEY (id), 
        CONSTRAINT ck_auth_action_tokens_purpose CHECK (purpose IN
    ('verify_email','password_reset')),
        CONSTRAINT fk_auth_action_tokens_user_id_users FOREIGN KEY(user_id)
    REFERENCES users (id),
    CONSTRAINT uq_auth_action_tokens_token_hash UNIQUE (token_hash)
)
""")
    op.execute(
        "CREATE INDEX ix_auth_action_tokens_user_id ON auth_action_tokens (user_id)"
    )
    op.execute("""
CREATE TABLE auth_sessions (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    refresh_token_hash VARCHAR(64) NOT NULL, 
    csrf_hash VARCHAR(64) NOT NULL, 
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITH TIME ZONE, 
    rotation_version INTEGER NOT NULL, 
    CONSTRAINT pk_auth_sessions PRIMARY KEY (id), 
    CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) REFERENCES
    users (id),
    CONSTRAINT uq_auth_sessions_refresh_token_hash UNIQUE (refresh_token_hash)
)
""")
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id)")
    op.execute("""
CREATE TABLE candidate_profiles (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    display_name VARCHAR(120) NOT NULL, 
    summary TEXT NOT NULL, 
    experience TEXT NOT NULL, 
    salary_min NUMERIC(12, 2), 
    salary_max NUMERIC(12, 2), 
    salary_basis VARCHAR(16) NOT NULL, 
    available_from DATE, 
    preferences_confirmed_at TIMESTAMP WITH TIME ZONE, 
    privacy JSONB NOT NULL, 
    work_preferences JSONB NOT NULL, 
    consent_version VARCHAR(32), 
    consented_at TIMESTAMP WITH TIME ZONE, 
    version INTEGER NOT NULL, 
    CONSTRAINT pk_candidate_profiles PRIMARY KEY (id), 
        CONSTRAINT ck_candidate_profiles_salary_range CHECK ((salary_min IS NULL AND
    salary_max IS NULL) OR (salary_min IS NOT NULL AND salary_max IS NOT NULL AND
    salary_min >= 0 AND salary_max >= salary_min)),
    CONSTRAINT uq_candidate_profiles_user_id UNIQUE (user_id), 
        CONSTRAINT fk_candidate_profiles_user_id_users FOREIGN KEY(user_id)
    REFERENCES users (id)
)
""")
    op.execute("""
CREATE TABLE categories (
    id UUID NOT NULL, 
    specialization_id UUID NOT NULL, 
    grade_id UUID NOT NULL, 
    CONSTRAINT pk_categories PRIMARY KEY (id), 
    CONSTRAINT uq_categories_specialization_id UNIQUE (specialization_id,
    grade_id),
        CONSTRAINT fk_categories_specialization_id_specializations FOREIGN
    KEY(specialization_id) REFERENCES specializations (id),
    CONSTRAINT fk_categories_grade_id_grades FOREIGN KEY(grade_id) REFERENCES
    grades (id)
)
""")
    op.execute("""
CREATE TABLE employer_profiles (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    company_name VARCHAR(160) NOT NULL, 
    description TEXT NOT NULL, 
    industry VARCHAR(120) NOT NULL, 
    representative_contact VARCHAR(254) NOT NULL, 
    status VARCHAR(16) NOT NULL, 
    version INTEGER NOT NULL, 
    CONSTRAINT pk_employer_profiles PRIMARY KEY (id), 
    CONSTRAINT uq_employer_profiles_user_id UNIQUE (user_id), 
        CONSTRAINT fk_employer_profiles_user_id_users FOREIGN KEY(user_id)
    REFERENCES users (id)
)
""")
    op.execute("""
CREATE TABLE skills (
    id UUID NOT NULL, 
    specialization_id UUID NOT NULL, 
    code VARCHAR(64) NOT NULL, 
    name VARCHAR(128) NOT NULL, 
    active BOOLEAN NOT NULL, 
    CONSTRAINT pk_skills PRIMARY KEY (id), 
        CONSTRAINT fk_skills_specialization_id_specializations FOREIGN
    KEY(specialization_id) REFERENCES specializations (id),
    CONSTRAINT uq_skills_code UNIQUE (code)
)
""")
    op.execute("""
CREATE TABLE user_identities (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    issuer VARCHAR(255) NOT NULL, 
    subject VARCHAR(254) NOT NULL, 
    linked_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_user_identities PRIMARY KEY (id), 
    CONSTRAINT uq_user_identities_issuer UNIQUE (issuer, subject), 
    CONSTRAINT fk_user_identities_user_id_users FOREIGN KEY(user_id) REFERENCES
    users (id)
)
""")
    op.execute("CREATE INDEX ix_user_identities_user_id ON user_identities (user_id)")
    op.execute("""
CREATE TABLE candidate_contacts (
    candidate_id UUID NOT NULL, 
    email VARCHAR(254) NOT NULL, 
    phone VARCHAR(32) NOT NULL, 
    messengers JSONB NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_candidate_contacts PRIMARY KEY (candidate_id), 
        CONSTRAINT fk_candidate_contacts_candidate_id_candidate_profiles FOREIGN
    KEY(candidate_id) REFERENCES candidate_profiles (id)
)
""")
    op.execute("""
CREATE TABLE candidate_employer_blocks (
    candidate_id UUID NOT NULL, 
    employer_id UUID NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_candidate_employer_blocks PRIMARY KEY (candidate_id,
    employer_id),
        CONSTRAINT fk_candidate_employer_blocks_candidate_id_candidate_profiles
    FOREIGN KEY(candidate_id) REFERENCES candidate_profiles (id),
        CONSTRAINT fk_candidate_employer_blocks_employer_id_employer_profiles
    FOREIGN KEY(employer_id) REFERENCES employer_profiles (id)
)
""")
    op.execute("""
CREATE TABLE candidate_technologies (
    candidate_id UUID NOT NULL, 
    technology_id UUID NOT NULL, 
    declared BOOLEAN NOT NULL, 
    CONSTRAINT pk_candidate_technologies PRIMARY KEY (candidate_id, technology_id), 
        CONSTRAINT fk_candidate_technologies_candidate_id_candidate_profiles FOREIGN
    KEY(candidate_id) REFERENCES candidate_profiles (id),
        CONSTRAINT fk_candidate_technologies_technology_id_technologies FOREIGN
    KEY(technology_id) REFERENCES technologies (id)
)
""")
    op.execute("""
CREATE TABLE used_refresh_tokens (
    token_hash VARCHAR(64) NOT NULL, 
    session_id UUID NOT NULL, 
    CONSTRAINT pk_used_refresh_tokens PRIMARY KEY (token_hash), 
        CONSTRAINT fk_used_refresh_tokens_session_id_auth_sessions FOREIGN
    KEY(session_id) REFERENCES auth_sessions (id)
)
""")
    op.execute(
        "CREATE INDEX ix_used_refresh_tokens_session_id ON "
        "used_refresh_tokens (session_id)"
    )
    seed_catalogs()


def seed_catalogs() -> None:
    """Начальные значения не являются присвоенными категориями кандидатов."""
    connection = op.get_bind()

    def identifier(code: str) -> str:
        return str(uuid5(NAMESPACE_URL, "aggratech:" + code))

    specialization = identifier("backend")
    connection.execute(
        sa.text(
            "INSERT INTO specializations (id,code,name,active) VALUES "
            "(:id,'backend','Backend',true)"
        ),
        {"id": specialization},
    )
    for order, code in enumerate(("junior", "middle")):
        grade = identifier(code)
        connection.execute(
            sa.text(
                "INSERT INTO grades (id,code,name,sort_order,active) VALUES "
                "(:id,:code,:name,:order,true)"
            ),
            {"id": grade, "code": code, "name": code.title(), "order": order},
        )
        connection.execute(
            sa.text(
                "INSERT INTO categories (id,specialization_id,grade_id) VALUES "
                "(:id,:spec,:grade)"
            ),
            {
                "id": identifier("backend-" + code),
                "spec": specialization,
                "grade": grade,
            },
        )
    for code, name in (
        ("language_algorithms", "Язык и алгоритмы"),
        ("sql_data", "SQL и данные"),
        ("http_api", "HTTP и API"),
        ("debug_reliability", "Отладка и надёжность"),
        ("security_validation", "Безопасность и валидация"),
    ):
        connection.execute(
            sa.text(
                "INSERT INTO skills (id,specialization_id,code,name,active) VALUES "
                "(:id,:spec,:code,:name,true)"
            ),
            {
                "id": identifier(code),
                "spec": specialization,
                "code": code,
                "name": name,
            },
        )
    for code, name in (
        ("python", "Python"),
        ("sql", "SQL"),
        ("postgresql", "PostgreSQL"),
        ("fastapi", "FastAPI"),
        ("docker", "Docker"),
    ):
        connection.execute(
            sa.text(
                "INSERT INTO technologies (id,code,name,active) VALUES "
                "(:id,:code,:name,true)"
            ),
            {"id": identifier("technology-" + code), "code": code, "name": name},
        )


def downgrade() -> None:
    """Удаляет только таблицы этапа 2 в порядке зависимостей."""
    op.drop_table("used_refresh_tokens")
    op.drop_table("candidate_technologies")
    op.drop_table("candidate_employer_blocks")
    op.drop_table("candidate_contacts")
    op.drop_table("user_identities")
    op.drop_table("skills")
    op.drop_table("employer_profiles")
    op.drop_table("categories")
    op.drop_table("candidate_profiles")
    op.drop_table("auth_sessions")
    op.drop_table("auth_action_tokens")
    op.drop_table("users")
    op.drop_table("technologies")
    op.drop_table("specializations")
    op.drop_table("grades")
    op.drop_table("auth_rate_buckets")
