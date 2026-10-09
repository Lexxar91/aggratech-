"""Потребности, снимки выдачи и ФСП mock этапа 5."""

from alembic import op

revision = "0004_matching"
down_revision = "0003_assessment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создаёт фиксированную схему без fixture-профилей."""
    op.execute("""CREATE TABLE employer_needs (
        id UUID PRIMARY KEY, employer_id UUID NOT NULL REFERENCES employer_profiles(id),
        version INTEGER NOT NULL CHECK(version > 0), definition JSONB NOT NULL)""")
    op.execute("""CREATE TABLE employer_need_versions (
        need_id UUID REFERENCES employer_needs(id), version INTEGER NOT NULL,
        definition JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(need_id,version))""")
    op.execute("""CREATE TABLE matching_snapshots (
        id UUID PRIMARY KEY, need_id UUID NOT NULL REFERENCES employer_needs(id),
        need_version INTEGER NOT NULL, created_at TIMESTAMPTZ NOT NULL,
        algorithm_version VARCHAR(64) NOT NULL, catalog_version VARCHAR(64) NOT NULL,
        definition JSONB NOT NULL, ranking JSONB NOT NULL)""")
    op.execute("""CREATE TABLE candidate_need_marks (
        need_id UUID REFERENCES employer_needs(id),
        candidate_id UUID REFERENCES candidate_profiles(id),
        saved BOOLEAN NOT NULL, hidden BOOLEAN NOT NULL, reason VARCHAR(500) NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(need_id,candidate_id))""")
    op.execute("""CREATE TABLE fsp_links (
        candidate_id UUID PRIMARY KEY REFERENCES candidate_profiles(id),
        external_id VARCHAR(128) NOT NULL UNIQUE, source VARCHAR(32) NOT NULL,
        status VARCHAR(32) NOT NULL, achievements JSONB NOT NULL,
        linked_at TIMESTAMPTZ NOT NULL, synced_at TIMESTAMPTZ)""")


def downgrade() -> None:
    """Удаляет только таблицы этапа 5."""
    for table in (
        "fsp_links",
        "candidate_need_marks",
        "matching_snapshots",
        "employer_need_versions",
        "employer_needs",
    ):
        op.drop_table(table)
