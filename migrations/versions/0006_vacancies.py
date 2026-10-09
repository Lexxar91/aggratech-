"""Вакансии, неизменяемые отклики и независимые источники контактного согласия."""

from alembic import op

revision = "0006_vacancies"
down_revision = "0005_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Сохраняет приглашения и усиливает инварианты обоих источников в PostgreSQL."""
    op.execute("""CREATE TABLE vacancies (
      id UUID PRIMARY KEY, employer_id UUID NOT NULL REFERENCES employer_profiles(id),
      need_id UUID REFERENCES employer_needs(id), title VARCHAR(160) NOT NULL,
      description TEXT NOT NULL, salary_from NUMERIC(12,2) NOT NULL,
      salary_to NUMERIC(12,2) NOT NULL, currency VARCHAR(3) NOT NULL,
      salary_basis VARCHAR(8) NOT NULL, conditions JSONB NOT NULL,
      status VARCHAR(16) NOT NULL, published_at TIMESTAMPTZ NOT NULL,
      closed_at TIMESTAMPTZ, version INTEGER NOT NULL,
      CHECK(status IN ('published','closed')),
      CHECK(salary_from > 0 AND salary_to >= salary_from
        AND salary_to < 'Infinity'::numeric),
      CHECK(currency = 'RUB' AND salary_basis = 'gross'), CHECK(version >= 1),
      CHECK((status = 'closed') = (closed_at IS NOT NULL)))""")
    op.execute(
        "CREATE INDEX ix_vacancies_employer_status ON "
        "vacancies(employer_id,status,published_at)"
    )
    op.execute("""CREATE TABLE applications (
      id UUID PRIMARY KEY, vacancy_id UUID NOT NULL REFERENCES vacancies(id),
      candidate_id UUID NOT NULL REFERENCES candidate_profiles(id),
      employer_id UUID NOT NULL REFERENCES employer_profiles(id),
      vacancy_snapshot JSONB NOT NULL, message TEXT NOT NULL,
      status VARCHAR(16) NOT NULL, submitted_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL, version INTEGER NOT NULL,
      UNIQUE(vacancy_id,candidate_id), CHECK(version >= 1),
      CHECK(status IN ('submitted','viewed','accepted','rejected','withdrawn')))""")
    op.execute(
        "CREATE INDEX ix_applications_vacancy_status ON "
        "applications(vacancy_id,status,submitted_at)"
    )
    op.execute("ALTER TABLE contact_grants ALTER COLUMN invitation_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE contact_grants ADD application_id UUID UNIQUE "
        "REFERENCES applications(id)"
    )
    op.execute(
        "ALTER TABLE contact_grants ADD CONSTRAINT "
        "contact_grants_one_source "
        "CHECK(num_nonnulls(invitation_id,application_id) = 1)"
    )
    op.execute("""CREATE FUNCTION protect_vacancy() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.need_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM employer_needs
          WHERE id = NEW.need_id AND employer_id = NEW.employer_id)
        THEN RAISE EXCEPTION 'vacancy_owner_mismatch'; END IF;
        IF TG_OP = 'UPDATE' THEN
          IF OLD.status = 'closed' OR NEW.employer_id <> OLD.employer_id
            OR NEW.id <> OLD.id OR NEW.published_at <> OLD.published_at
            OR NEW.version <> OLD.version + 1
          THEN RAISE EXCEPTION 'invalid_vacancy_change'; END IF;
        END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER protect_vacancy BEFORE INSERT OR UPDATE ON "
        "vacancies FOR EACH ROW EXECUTE FUNCTION protect_vacancy()"
    )
    op.execute("""CREATE FUNCTION protect_application() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'INSERT' THEN
          PERFORM 1 FROM vacancies WHERE id = NEW.vacancy_id
            AND employer_id = NEW.employer_id AND status = 'published' FOR UPDATE;
          IF NOT FOUND OR NEW.status <> 'submitted'
          THEN RAISE EXCEPTION 'invalid_application_source'; END IF;
        ELSE
          IF (to_jsonb(OLD) - ARRAY['status','updated_at','version'])
            IS DISTINCT FROM (to_jsonb(NEW) - ARRAY['status','updated_at','version'])
            OR NEW.version <> OLD.version + 1
          THEN RAISE EXCEPTION 'immutable_application'; END IF;
          IF NOT ((OLD.status IN ('submitted','viewed','accepted','rejected')
            AND NEW.status = 'withdrawn') OR
            (OLD.status = 'submitted' AND NEW.status IN
('viewed','accepted','rejected')) OR
            (OLD.status = 'viewed' AND NEW.status IN ('accepted','rejected')))
          THEN RAISE EXCEPTION 'invalid_application_transition'; END IF;
        END IF; RETURN NEW; END $$""")
    op.execute(
        "CREATE TRIGGER protect_application BEFORE INSERT OR UPDATE ON "
        "applications FOR EACH ROW EXECUTE FUNCTION protect_application()"
    )
    op.execute("""CREATE OR REPLACE FUNCTION protect_contact_grant() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'UPDATE' THEN
          IF (to_jsonb(OLD) - 'revoked_at') IS DISTINCT FROM
            (to_jsonb(NEW) - 'revoked_at') OR
            (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM
OLD.revoked_at)
          THEN RAISE EXCEPTION 'immutable_contact_grant'; END IF;
        ELSE
          IF NEW.invitation_id IS NOT NULL THEN
            IF NOT EXISTS(SELECT 1 FROM invitations WHERE id = NEW.invitation_id
              AND status = 'accepted' AND candidate_id = NEW.candidate_id
              AND employer_id = NEW.employer_id)
            THEN RAISE EXCEPTION 'invalid_contact_source'; END IF;
          ELSE
            IF NOT EXISTS(SELECT 1 FROM applications WHERE id = NEW.application_id
              AND status = 'submitted' AND candidate_id = NEW.candidate_id
              AND employer_id = NEW.employer_id)
            THEN RAISE EXCEPTION 'invalid_contact_source'; END IF;
          END IF;
        END IF; RETURN NEW; END $$""")


def downgrade() -> None:
    """Откатывает только этап 8; его отклики и их согласия удаляются вместе."""
    op.execute("DELETE FROM contact_grants WHERE application_id IS NOT NULL")
    op.execute("ALTER TABLE contact_grants DROP CONSTRAINT contact_grants_one_source")
    op.execute("ALTER TABLE contact_grants DROP COLUMN application_id")
    op.execute("ALTER TABLE contact_grants ALTER COLUMN invitation_id SET NOT NULL")
    op.execute("""CREATE OR REPLACE FUNCTION protect_contact_grant() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'UPDATE' THEN
          IF (to_jsonb(OLD) - 'revoked_at') IS DISTINCT FROM
            (to_jsonb(NEW) - 'revoked_at') OR (OLD.revoked_at IS NOT NULL
              AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
          THEN RAISE EXCEPTION 'immutable_contact_grant'; END IF;
        ELSE
          IF NOT EXISTS(SELECT 1 FROM invitations WHERE id = NEW.invitation_id
            AND status = 'accepted' AND candidate_id = NEW.candidate_id
            AND employer_id = NEW.employer_id)
          THEN RAISE EXCEPTION 'invalid_contact_source'; END IF;
        END IF; RETURN NEW; END $$""")
    op.drop_table("applications")
    op.drop_table("vacancies")
    op.execute("DROP FUNCTION protect_application()")
    op.execute("DROP FUNCTION protect_vacancy()")
