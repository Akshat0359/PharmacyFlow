"""Local operator account provisioning. Passwords are prompted, never CLI arguments/logs."""

import argparse
import getpass
from pwdlib import PasswordHash
from sqlalchemy import select
from .db import session
from .models import User, Patient, uid


def create_account(username, password, tenant, role, patient_id=None):
    if not 1 <= len(username) <= 80 or len(password) < 14 or len(password) > 256:
        raise ValueError("Username required; individual passwords must contain 14–256 characters")
    if role not in {"patient", "staff", "pharmacist", "administrator"} or not tenant:
        raise ValueError("Valid tenant and role required")
    with session() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise ValueError("Username already exists")
        if role == "patient":
            patient = db.get(Patient, patient_id)
            if not patient or patient.tenant != tenant:
                raise ValueError("Patient must exist in the selected tenant")
        elif patient_id:
            raise ValueError("Only patient accounts bind a patient")
        user = User(
            id=uid(),
            username=username,
            password_hash=PasswordHash.recommended().hash(password),
            tenant=tenant,
            role=role,
            patient_id=patient_id,
            demo_account=0,
        )
        db.add(user)
        db.commit()
        return user.id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--role", required=True, choices=["patient", "staff", "pharmacist", "administrator"])
    parser.add_argument("--patient-id")
    args = parser.parse_args()
    password = getpass.getpass("Individual password (14+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords differ")
    create_account(args.username, password, args.tenant, args.role, args.patient_id)
    print("Individual account created. No password was logged.")


if __name__ == "__main__":
    main()
