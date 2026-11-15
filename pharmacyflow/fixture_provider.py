"""Explicit TEST adapter. Known-hash scan answers are never used by live extraction."""

import hashlib
import json
from pathlib import Path
import pymupdf as fitz
from .models import Extraction, ExtractedField, FIELD_NAMES


def extract_fixture(data, kind):
    from .providers import parse_text, validate_source_evidence

    manifest_path = Path(__file__).resolve().parents[1] / "fixtures/documents/manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    match = manifest.get(hashlib.sha256(data).hexdigest())
    if match:
        result = parse_text(match["pages"])
        if match.get("blurry"):
            result.fields["strength"].confidence = 0.4
            result.fields["strength"].issue = "blurry_fixture"
        return validate_source_evidence(result, match["pages"])
    if kind == "pdf":
        with fitz.open(stream=data, filetype="pdf") as doc:
            return parse_text([page.get_text() for page in doc])
    return Extraction(
        fields={
            k: ExtractedField(value=None, confidence=0, issue="fixture_has_no_ocr_for_unknown_image")
            for k in FIELD_NAMES
        },
        warnings=["unknown_image_requires_manual_review"],
        mode="fixture",
    )
