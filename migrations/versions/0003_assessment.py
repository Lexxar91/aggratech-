"""Сохраняемые циклы assessment, показы и публикации этапа 4."""

from alembic import op

revision = "0003_assessment"
down_revision = "0002_auth_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт фиксированную схему assessment."""
    op.execute("""
CREATE TABLE assessment_cycles (
    id UUID NOT NULL,
    user_id UUID NOT NULL,
    mode VARCHAR(16) NOT NULL,
    grade VARCHAR(16) NOT NULL,
    form VARCHAR(1) NOT NULL,
    state VARCHAR(32) NOT NULL,
    outcome VARCHAR(32) NOT NULL,
    review_state VARCHAR(16) NOT NULL,
    terminal_reason VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    a_deadline TIMESTAMP WITH TIME ZONE NOT NULL,
    a_submitted_at TIMESTAMP WITH TIME ZONE,
    b_start_deadline TIMESTAMP WITH TIME ZONE,
    b_started_at TIMESTAMP WITH TIME ZONE,
    b_deadline TIMESTAMP WITH TIME ZONE,
    b_submitted_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    technical_exempt BOOLEAN NOT NULL,
    seed INTEGER NOT NULL,
    methodology VARCHAR(64) NOT NULL,
    evaluator_hash VARCHAR(64) NOT NULL,
    bank_hash VARCHAR(64) NOT NULL,
    admission JSONB NOT NULL,
    materials JSONB NOT NULL,
    result JSONB NOT NULL,
    CONSTRAINT pk_assessment_cycles PRIMARY KEY (id),
    CONSTRAINT ck_assessment_cycles_mode CHECK (mode IN ('demo','credit')),
    CONSTRAINT ck_assessment_cycles_grade CHECK (grade IN ('junior','middle')),
    CONSTRAINT ck_assessment_cycles_form CHECK (form IN ('X','Y')),
    CONSTRAINT fk_assessment_cycles_user_id_users FOREIGN KEY(user_id) REFERENCES
    users (id)
)
""")
    op.execute("""
CREATE INDEX ix_assessment_cycles_user_created ON assessment_cycles (user_id,
    created_at)
""")
    op.execute("""
CREATE UNIQUE INDEX uq_assessment_active_user ON assessment_cycles (user_id) WHERE
    state IN ('A','B_ready','B','grading','technical_error')
""")
    op.execute("""
CREATE TABLE assessment_surveys (
    user_id UUID NOT NULL,
    answers JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_assessment_surveys PRIMARY KEY (user_id),
    CONSTRAINT fk_assessment_surveys_user_id_users FOREIGN KEY(user_id) REFERENCES
    users (id)
)
""")
    op.execute("""
CREATE TABLE assessment_answers (
    cycle_id UUID NOT NULL,
    family VARCHAR(4) NOT NULL,
    phase VARCHAR(1) NOT NULL,
    parameter_index INTEGER NOT NULL,
    step VARCHAR(16) NOT NULL,
    revision INTEGER NOT NULL,
    draft JSONB NOT NULL,
    base JSONB,
    transfer JSONB,
    finalized_at TIMESTAMP WITH TIME ZONE,
    grade_generation INTEGER NOT NULL,
    grading_status VARCHAR(24) NOT NULL,
    scores JSONB NOT NULL,
    grading_detail JSONB NOT NULL,
    CONSTRAINT pk_assessment_answers PRIMARY KEY (cycle_id, family),
    CONSTRAINT fk_assessment_answers_cycle_id_assessment_cycles FOREIGN
    KEY(cycle_id) REFERENCES assessment_cycles (id)
)
""")
    op.execute("""
CREATE TABLE assessment_appeals (
    id UUID NOT NULL,
    cycle_id UUID NOT NULL,
    user_id UUID NOT NULL,
    message TEXT NOT NULL,
    state VARCHAR(16) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution TEXT,
    reviewer VARCHAR(128),
    CONSTRAINT pk_assessment_appeals PRIMARY KEY (id),
    CONSTRAINT fk_assessment_appeals_cycle_id_assessment_cycles FOREIGN
    KEY(cycle_id) REFERENCES assessment_cycles (id),
    CONSTRAINT fk_assessment_appeals_user_id_users FOREIGN KEY(user_id) REFERENCES
    users (id)
)
""")
    op.execute("""
CREATE TABLE assessment_exposures (
    user_id UUID NOT NULL,
    family VARCHAR(4) NOT NULL,
    cycle_id UUID NOT NULL,
    shown_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_assessment_exposures PRIMARY KEY (user_id, family),
    CONSTRAINT fk_assessment_exposures_user_id_users FOREIGN KEY(user_id) REFERENCES
    users (id),
    CONSTRAINT fk_assessment_exposures_cycle_id_assessment_cycles FOREIGN
    KEY(cycle_id) REFERENCES assessment_cycles (id)
)
""")
    op.execute("""
CREATE TABLE assessment_publications (
    user_id UUID NOT NULL,
    mode VARCHAR(16) NOT NULL,
    cycle_id UUID NOT NULL,
    grade VARCHAR(16) NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_assessment_publications PRIMARY KEY (user_id, mode),
    CONSTRAINT fk_assessment_publications_user_id_users FOREIGN KEY(user_id)
    REFERENCES users (id),
    CONSTRAINT fk_assessment_publications_cycle_id_assessment_cycles FOREIGN
    KEY(cycle_id) REFERENCES assessment_cycles (id)
)
""")


def downgrade() -> None:
    """Удаляет только таблицы этого этапа."""
    op.drop_table("assessment_publications")
    op.drop_table("assessment_exposures")
    op.drop_table("assessment_appeals")
    op.drop_table("assessment_answers")
    op.drop_table("assessment_surveys")
    op.drop_table("assessment_cycles")
