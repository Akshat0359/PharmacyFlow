"""Persistent spend reservations and non-sensitive usage ledger."""

from alembic import op
from pharmacyflow.models import Budget, ProviderUsage

revision = "003"
down_revision = "002"


def upgrade():
    Budget.__table__.create(op.get_bind(), checkfirst=True)
    ProviderUsage.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Preserve usage evidence; restore a verified backup for rollback")
