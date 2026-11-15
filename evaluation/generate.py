"""Deterministic held-out data generator. Development examples use different identities."""

import json
from pathlib import Path

CATEGORIES = [
    "normal",
    "blurry",
    "similar_names",
    "missing_fields",
    "conflicting",
    "interrupted_call",
    "duplicate",
    "stale_policy",
    "tool_failure",
    "prompt_injection",
    "exhausted_refills",
    "wrong_identity",
]


def main():
    rows = []
    for index in range(60):
        category = CATEGORIES[index % len(CATEGORIES)]
        fields = {
            "patient_name": f"Fictional Eval Person {index + 100}",
            "dob": f"198{index % 10}-0{index % 9 + 1}-12",
            "prescriber": f"Dr. Synthetic {index + 100}",
            "medication": f"EvalCompound {index % 5} (fictional)",
            "strength": f"{index % 5 + 1} demo-units",
            "directions": "Synthetic testing directions only",
            "quantity": str(20 + index % 10),
            "date": "2026-11-12",
            "refills": "2",
        }
        kind = (
            "intake"
            if category in {"blurry", "missing_fields", "conflicting", "prompt_injection"}
            else "refill"
        )
        expected = (
            "clarification"
            if category == "interrupted_call"
            else "escalated"
            if category in {"stale_policy", "exhausted_refills", "wrong_identity"}
            else "completed"
        )
        rows.append(
            {
                "id": f"heldout-{index + 1:03}",
                "category": category,
                "kind": kind,
                "fields": fields,
                "expected_state": expected,
                "query": "refill identity prescription"
                if kind == "refill"
                else "missing uncertain prescription pharmacist review",
                "relevant_policy": "refill-v1" if kind == "refill" else "review-v1",
            }
        )
    target = Path(__file__).parent / "heldout.json"
    target.write_text(
        json.dumps(
            {
                "version": "heldout-v1",
                "split": "held-out; not used by runtime fixture matching",
                "seed": 359,
                "scenarios": rows,
            },
            indent=2,
        )
    )
    print("Wrote 60 held-out synthetic scenarios.")


if __name__ == "__main__":
    main()
