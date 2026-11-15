from pharmacyflow.db import session
from pharmacyflow.models import Evaluation


def test_calibration_waits_for_labels_and_pairs_exact_samples(client, auth):
    # Artificial test labels in an isolated temporary DB; not human benchmark evidence.
    with session() as db:
        e = Evaluation(
            tenant="demo",
            report={
                "rows": [
                    {
                        "scenario_id": "heldout-001",
                        "sample_id": "heldout-001:single:trial-0",
                        "judge_score": 4,
                    },
                    {
                        "scenario_id": "heldout-001",
                        "sample_id": "heldout-001:multi:trial-0",
                        "judge_score": 2,
                    },
                ]
            },
        )
        db.add(e)
        db.commit()
        eid = e.id
    h = auth("pharmacist")
    assert client.get(f"/api/evaluations/{eid}/agreement", headers=h).json()["calibration"] == "pending"
    result = client.post(
        f"/api/evaluations/{eid}/labels",
        headers=h,
        json={"scenario_id": "heldout-001:single:trial-0", "score": 4, "note": "Synthetic test-only label"},
    )
    assert result.status_code == 200
    agreement = client.get(f"/api/evaluations/{eid}/agreement", headers=h).json()
    assert agreement["paired_labels"] == 1 and agreement["exact_agreement"] == 1
    assert (
        client.get(f"/api/evaluations/{eid}/agreement", headers=auth("other-pharmacist")).status_code == 404
    )
