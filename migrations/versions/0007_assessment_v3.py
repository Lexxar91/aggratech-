"""Раздельные PY/SQL-ответы при общей истории семейств; прежние записи сохраняются."""

from alembic import op

revision = "0007_assessment_v3"
down_revision = "0006_vacancies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Расширяет идентификатор без изменения данных и результатов старых циклов."""
    op.execute("ALTER TABLE assessment_answers ALTER COLUMN family TYPE VARCHAR(32)")


def downgrade() -> None:
    """Не обрезает идентификаторы v3 при ошибочном откате."""
    op.execute("ALTER TABLE assessment_answers ALTER COLUMN family TYPE VARCHAR(4)")
