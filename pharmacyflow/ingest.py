"""Ingest a reviewed, versioned policy release. Arbitrary retrieved text cannot register trust."""

import argparse
from .db import session
from .retrieval import seed_policies


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--version", required=True, help="Reviewed fixtures/policies/vN.json release")
    args = parser.parse_args()
    with session() as db:
        seed_policies(db, args.tenant, args.version)
        db.commit()
    print("Trusted policy release ingested. Existing versions preserved.")


if __name__ == "__main__":
    main()
