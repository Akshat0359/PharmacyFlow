"""Shared request counters, additive migration."""

from alembic import op
from pharmacyflow.models import RateWindow

revision = "004"
down_revision = "003"


def upgrade():
    RateWindow.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Forward-only; restore a verified backup")
