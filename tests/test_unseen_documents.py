from types import SimpleNamespace
import pymupdf as fitz
import pytest
from pharmacyflow.providers import Provider, parse_text
from pharmacyflow.documents import document_pages
from pharmacyflow.config import settings
from pharmacyflow.db import session
from test_workflow import draft


def unseen_pdf():
    with fitz.open() as doc:
        p = doc.new_page()
        p.insert_text((72, 72), "patient_name: Robin Unseen\nstrength: 17 fictional units")
        p.set_rotation(90)
        doc.new_page()  # unreadable scan/page must not invalidate the readable page's evidence
        return doc.tobytes()


def test_unseen_mixed_rotated_pdf_live_content_contract(environment, monkeypatch):
    settings().provider_mode = "live"
    captured = []
    result = parse_text(["patient_name: Robin Unseen\nstrength: 17 fictional units", ""])
    result.mode = "live"

    def create(**args):
        captured.append(args)
        return SimpleNamespace(
            output_text=result.model_dump_json(), usage=SimpleNamespace(input_tokens=90, output_tokens=50)
        )

    monkeypatch.setattr(
        Provider, "client", lambda self: SimpleNamespace(responses=SimpleNamespace(create=create))
    )
    raw = unseen_pdf()
    pages = document_pages(raw, "pdf")
    assert len(pages) == 2 and pages[0]["rotation"] == 90
    extracted = Provider().extract(raw, "application/pdf")
    assert extracted.fields["strength"].value == "17 fictional units"
    assert extracted.fields["strength"].evidence[0].bbox
    assert extracted.fields["strength"].issue is None
    assert "model_confidence_uncalibrated" in extracted.warnings
    content = captured[0]["input"][0]["content"]
    assert "Robin Unseen" in content[0]["text"] and len(content) == 4
    assert captured[0]["text"]["format"]["strict"] is True
    assert "tools" not in captured[0]


def test_upload_fingerprint_context_and_tenant(client, auth):
    raw = unseen_pdf()

    def upload(role, key, context="default"):
        return client.post(
            "/api/intakes",
            headers=auth(role),
            data={"request_key": key, "document_context": context},
            files={"file": ("unseen.pdf", raw, "application/pdf")},
        )

    first = upload("staff", "first-upload").json()
    assert upload("pharmacist", "repeat-upload").json()["id"] == first["id"]
    assert upload("staff", "another-context", "new-encounter").json()["id"] != first["id"]
    assert upload("other-staff", "other-upload").json()["id"] != first["id"]


def test_correction_history_records_reviewer_and_values(client, auth):
    with session() as db:
        c = draft()
        db.add(c)
        db.commit()
        cid = c.id
    r = client.patch(
        f"/api/cases/{cid}/fields",
        headers=auth("pharmacist"),
        json={"fields": {"quantity": "37"}, "revision": 0},
    )
    assert r.status_code == 200
    history = r.json()["payload"]["correction_history"]
    assert history[0]["before"] == "demo" and history[0]["after"] == "37"
    assert history[0]["reviewer"] == "pharmacist" and r.json()["payload"]["approval"] is None


def test_silent_live_transcription_requires_text_fallback(environment, monkeypatch):
    settings().provider_mode = "live"
    monkeypatch.setattr(
        Provider,
        "client",
        lambda self: SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=lambda **kw: SimpleNamespace(text="  "))
            )
        ),
    )
    with pytest.raises(ValueError, match="No speech"):
        Provider().transcribe(b"audio", "recording.webm")
