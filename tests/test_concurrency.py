import pytest
from sqlalchemy.orm.exc import StaleDataError
from pharmacyflow.db import session
from pharmacyflow.models import Case


def test_stale_writer_cannot_overwrite_cancellation(environment):
    with session() as db:
        c = Case(
            tenant="demo",
            created_by="staff",
            kind="intake",
            state="review",
            request_key="concurrent",
            payload={},
        )
        db.add(c)
        db.commit()
        cid = c.id
    with session() as first, session() as second:
        older = first.get(Case, cid)
        newer = second.get(Case, cid)
        newer.state = "cancelled"
        newer.revision += 1
        second.commit()
        older.state = "execution"
        older.revision += 1
        with pytest.raises(StaleDataError):
            first.commit()
    with session() as db:
        assert db.get(Case, cid).state == "cancelled"
