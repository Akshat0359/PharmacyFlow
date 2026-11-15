from pwdlib import PasswordHash
from sqlalchemy import text
from .config import settings
from .db import session, engine
from .models import Base, User, Patient, Prescription
from .retrieval import seed_policies


def seed():
    settings().validate_runtime()
    # Mock app has its own database and migration lifecycle.
    Base.metadata.tables["mock_requests"].create(engine(settings().mock_database_url), checkfirst=True)
    with engine(settings().mock_database_url).begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_mock_pending_action ON mock_requests (tenant, action_hash)"
            )
        )
    with session() as db:
        for tenant, prefix in [("demo", ""), ("other", "other-")]:
            for suffix, name, dob, code in [
                ("001", "Avery Morgan", "1988-04-12", "246810"),
                ("002", "Avery Morgann", "1991-07-23", "135790"),
            ]:
                pid = prefix + "pat-" + suffix
                if not db.get(Patient, pid):
                    db.add(Patient(id=pid, tenant=tenant, name=name, dob=dob, verification_code=code))
                    db.add(
                        Prescription(
                            id=prefix + "rx-" + suffix,
                            tenant=tenant,
                            patient_id=pid,
                            medication="DemoMed (fictional)",
                            strength="10 demo-units",
                            refills=2 if suffix == "001" else 0,
                        )
                    )
            for role in ["patient", "staff", "pharmacist", "administrator"]:
                if not settings().demo_mode:
                    continue
                user_id = prefix + role
                if not db.get(User, user_id):
                    db.add(
                        User(
                            id=user_id,
                            tenant=tenant,
                            username=user_id,
                            password_hash=PasswordHash.recommended().hash(settings().demo_password),
                            role=role,
                            demo_account=1,
                            patient_id=prefix + "pat-001" if role == "patient" else None,
                        )
                    )
            seed_policies(db, tenant)
        db.commit()


if __name__ == "__main__":
    seed()
    print("Seeded fictional patients, prescriptions, roles and versioned SOPs.")
