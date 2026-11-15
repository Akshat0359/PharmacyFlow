"""Content-only document preparation; no fixture identities or expected answers."""

import io
import pymupdf as fitz
from PIL import Image, ImageOps


def document_pages(data: bytes, kind: str):
    """Bound raster allocation; honor PDF rotation and camera EXIF orientation."""
    if kind == "pdf":
        with fitz.open(stream=data, filetype="pdf") as doc:
            result = []
            for page in doc:
                scale = min(1.5, 2200 / max(page.rect.width, page.rect.height))
                raster = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                result.append(
                    {
                        "page": page.number + 1,
                        "text": page.get_text(sort=True),
                        "png": raster.tobytes("png"),
                        "rotation": page.rotation,
                    }
                )
            return result
    with Image.open(io.BytesIO(data)) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
        im.thumbnail((2200, 2200))
        output = io.BytesIO()
        im.save(output, format="PNG")
        return [{"page": 1, "text": "", "png": output.getvalue(), "rotation": 0}]


def add_pdf_boxes(extraction, data):
    """Only attach boxes computed from PDF text, never invented model coordinates."""
    with fitz.open(stream=data, filetype="pdf") as doc:
        for field in extraction.fields.values():
            for evidence in field.evidence:
                if 1 <= evidence.page <= len(doc):
                    hits = doc[evidence.page - 1].search_for(evidence.text)
                    if hits:
                        evidence.bbox = list(hits[0])
    return extraction
