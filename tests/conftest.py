import pytest
from pwdlib import PasswordHash
from fastapi.testclient import TestClient

HASH = PasswordHash.recommended().hash("test-password-123")


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRET", "s" * 48)
    monkeypatch.setenv("DEMO_PASSWORD", "test-password-123")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "app.db"))
    monkeypatch.setenv("MOCK_DATABASE_URL", "sqlite:///" + str(tmp_path / "mock.db"))
    monkeypatch.setenv("CHECKPOINT_URL", "sqlite:///" + str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROVIDER_MODE", "fixture")
    from pharmacyflow.config import settings
    from pharmacyflow.db import engine, session
    from pharmacyflow.models import Base, User, Patient, Prescription
    from pharmacyflow.retrieval import seed_policies

    settings.cache_clear()
    engine.cache_clear()
    Base.metadata.create_all(engine())
    Base.metadata.tables["mock_requests"].create(engine(settings().mock_database_url))
    with session() as db:
        for tenant, prefix in [("demo", ""), ("other", "other-")]:
            for i, name in [(1, "Avery Morgan"), (2, "Avery Morgann")]:
                db.add(
                    Patient(
                        id=prefix + f"pat-{i:03}",
                        tenant=tenant,
                        name=name,
                        dob="1988-04-12",
                        verification_code="246810",
                    )
                )
                db.add(
                    Prescription(
                        id=prefix + f"rx-{i:03}",
                        tenant=tenant,
                        patient_id=prefix + f"pat-{i:03}",
                        medication="DemoMed (fictional)",
                        strength="10 demo-units",
                        refills=2 if i == 1 else 0,
                    )
                )
            for role in ["patient", "staff", "pharmacist", "administrator"]:
                db.add(
                    User(
                        id=prefix + role,
                        username=prefix + role,
                        tenant=tenant,
                        role=role,
                        password_hash=HASH,
                        patient_id=prefix + "pat-001" if role == "patient" else None,
                    )
                )
            seed_policies(db, tenant)
        db.commit()
    yield tmp_path
    engine().dispose()
    engine(settings().mock_database_url).dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def client(environment):
    from pharmacyflow.api import app, login_attempts

    login_attempts.clear()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth(client):
    def headers(role="patient"):
        r = client.post("/api/login", json={"username": role, "password": "test-password-123"})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    return headers


@pytest.fixture
def refill(client, auth):
    def create(**kwargs):
        import uuid

        r = client.post(
            "/api/refills",
            headers=auth(),
            json={"message": "refill please", "request_key": str(uuid.uuid4()), **kwargs},
        )
        assert r.status_code == 201, r.text
        return r.json()

    return create
