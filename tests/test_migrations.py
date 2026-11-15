"""Exercise the additive migrations against a real old SQLite schema and preserved rows."""

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text, inspect


def test_upgrade_existing_database_preserves_records(environment):
    from pharmacyflow.config import settings
    from pharmacyflow.db import engine

    url = "sqlite:///" + str(environment / "legacy.db")
    old = create_engine(url)
    with old.begin() as db:
        db.execute(
            text(
                "CREATE TABLE users (id TEXT PRIMARY KEY, tenant TEXT, username TEXT UNIQUE, password_hash TEXT, role TEXT, patient_id TEXT)"
            )
        )
        db.execute(text("INSERT INTO users VALUES ('staff','demo','staff','existing-hash','staff',NULL)"))
        db.execute(
            text("CREATE TABLE cases (id TEXT PRIMARY KEY, tenant TEXT, request_key TEXT, payload JSON)")
        )
        db.execute(text("INSERT INTO cases VALUES ('preserved','demo','existing-key','{}')"))
        db.execute(text("CREATE TABLE policies (id TEXT PRIMARY KEY, text TEXT)"))
        db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        db.execute(text("INSERT INTO alembic_version VALUES ('001')"))
    settings().database_url = url
    engine.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    command.upgrade(Config("alembic.ini"), "head")
    with old.connect() as db:
        assert db.execute(text("SELECT id FROM cases")).scalar() == "preserved"
        assert db.execute(text("SELECT password_hash FROM users")).scalar() == "existing-hash"
        assert db.execute(text("SELECT demo_account FROM users")).scalar() == 1
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "004"
    assert {"provider_usage", "provider_budgets"} <= set(inspect(old).get_table_names())
