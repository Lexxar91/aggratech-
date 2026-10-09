"""Приглашения и контактные разрешения; вакансии не вводятся."""

from alembic import op

revision = "0005_invitations"
down_revision = "0004_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Закрепляет сроки, допустимые переходы, согласие и неизменность в PostgreSQL."""
    op.execute("""CREATE TABLE invitations (
        id UUID PRIMARY KEY,
        employer_id UUID NOT NULL REFERENCES employer_profiles(id),
        candidate_id UUID NOT NULL REFERENCES candidate_profiles(id),
        need_id UUID NOT NULL REFERENCES employer_needs(id),
        idempotency_key VARCHAR(128) NOT NULL, request_hash VARCHAR(64) NOT NULL,
        salary_from NUMERIC(12,2) NOT NULL, salary_to NUMERIC(12,2) NOT NULL,
        offer_snapshot JSONB NOT NULL, status VARCHAR(16) NOT NULL,
        sent_at TIMESTAMPTZ NOT NULL, viewed_at TIMESTAMPTZ,
        expires_at TIMESTAMPTZ NOT NULL, decided_at TIMESTAMPTZ,
        UNIQUE(employer_id,idempotency_key),
        CHECK(status IN ('sent','viewed','accepted','rejected','expired','withdrawn')),
        CHECK(salary_from > 0 AND salary_to >= salary_from 
            AND salary_to < 'Infinity'::numeric),
        CHECK(expires_at = sent_at + interval '7 days'))""")
    op.execute("""CREATE UNIQUE INDEX uq_invitations_active ON invitations
        (employer_id,need_id,candidate_id) 
        WHERE status IN ('sent','viewed','accepted')""")
    op.execute(
        "CREATE INDEX ix_invitations_due ON invitations(expires_at) "
        "WHERE status IN ('sent','viewed')"
    )
    op.execute("""CREATE TABLE contact_grants (
        id UUID PRIMARY KEY,
        candidate_id UUID NOT NULL REFERENCES candidate_profiles(id),
        employer_id UUID NOT NULL REFERENCES employer_profiles(id),
        invitation_id UUID NOT NULL UNIQUE REFERENCES invitations(id),
        allowed_fields JSONB NOT NULL, consent_version VARCHAR(32) NOT NULL,
        granted_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
        CHECK(consent_version = 'contacts-v1'),
        CHECK(jsonb_typeof(allowed_fields) = 'array'
            AND jsonb_array_length(allowed_fields) BETWEEN 1 AND 3),
        CHECK(allowed_fields <@ '["email","phone","messengers"]'::jsonb))""")
    op.execute("""CREATE FUNCTION protect_invitation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NOT EXISTS(SELECT 1 FROM employer_needs WHERE id = NEW.need_id
              AND employer_id = NEW.employer_id)
            THEN RAISE EXCEPTION 'invitation_owner_mismatch'; END IF;
          ELSE
            IF (to_jsonb(OLD) - ARRAY['status','viewed_at','decided_at'])
              IS DISTINCT FROM
               (to_jsonb(NEW) - ARRAY['status','viewed_at','decided_at'])
            THEN RAISE EXCEPTION 'immutable_invitation'; END IF;
            IF OLD.status <> NEW.status AND NOT (
              (OLD.status = 'sent' AND NEW.status IN
                ('viewed','accepted','rejected','expired','withdrawn')) OR
              (OLD.status = 'viewed' AND NEW.status IN
                ('accepted','rejected','expired','withdrawn')))
            THEN RAISE EXCEPTION 'invalid_invitation_transition'; END IF;
          END IF;
          RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER protect_invitation BEFORE INSERT OR UPDATE ON invitations "
        "FOR EACH ROW EXECUTE FUNCTION protect_invitation()"
    )
    op.execute("""CREATE FUNCTION protect_contact_grant() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' THEN
            IF (to_jsonb(OLD) - 'revoked_at') IS DISTINCT FROM 
              (to_jsonb(NEW) - 'revoked_at') OR
              (OLD.revoked_at IS NOT NULL AND NEW.revoked_at
                IS DISTINCT FROM OLD.revoked_at)
            THEN RAISE EXCEPTION 'immutable_contact_grant'; END IF;
          ELSE
            IF NOT EXISTS(SELECT 1 FROM invitations WHERE id = NEW.invitation_id
              AND status = 'accepted'
              AND candidate_id = NEW.candidate_id AND employer_id = NEW.employer_id)
            THEN RAISE EXCEPTION 'invalid_contact_source'; END IF;
          END IF;
          RETURN NEW;
        END $$""")
    op.execute(
        "CREATE TRIGGER protect_contact_grant BEFORE INSERT OR UPDATE "
        "ON contact_grants FOR EACH ROW EXECUTE FUNCTION protect_contact_grant()"
    )


def downgrade() -> None:
    """Удаляет только этап 6."""
    op.drop_table("contact_grants")
    op.drop_table("invitations")
    op.execute("DROP FUNCTION protect_contact_grant()")
    op.execute("DROP FUNCTION protect_invitation()")
