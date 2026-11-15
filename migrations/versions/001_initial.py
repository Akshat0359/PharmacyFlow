"""Initial application tables and PostgreSQL hybrid policy index."""

from alembic import op
from pharmacyflow.models import Base

revision = "001"
down_revision = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            "ALTER TABLE policies ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
        )
        op.execute("ALTER TABLE policies ADD COLUMN vector_embedding vector(64)")
        op.execute("CREATE INDEX ix_policy_fts ON policies USING gin(search_vector)")
        op.execute("CREATE INDEX ix_policy_vector ON policies USING hnsw(vector_embedding vector_cosine_ops)")


def downgrade():
    Base.metadata.drop_all(op.get_bind())
