"""Turns uploaded files into page images: a photo stays as it is, a PDF becomes one image per page.

PDFs are rendered on this computer with PDFium (the engine inside Chrome), so nothing is sent
anywhere and no extra program has to be installed.
"""
from __future__ import annotations

import io

from PIL import Image

MAX_PAGES = 60          # a batch is a summary page and some sheets; more is almost surely a mistake
DPI = 200               # ordinary scan quality: digits are sharp, pages stay small
TARGET_SIDE = 2400      # never larger than this on the long side, the same limit as photos


class DocumentError(ValueError):
    pass


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(b"%PDF")


def pdf_pages(data: bytes, target_side: int = TARGET_SIDE, max_pages: int = MAX_PAGES,
              dpi: int = DPI) -> list[bytes]:
    """Each page of the PDF as PNG bytes at `dpi`, the long side at most target_side pixels."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:  # damaged file, or password protected
        raise DocumentError("تعذّر فتح ملف PDF (قد يكون تالفاً أو محمياً بكلمة سر).") from e
    try:
        if len(pdf) == 0:
            raise DocumentError("ملف PDF لا يحتوي على صفحات.")
        if len(pdf) > max_pages:
            raise DocumentError(f"ملف PDF فيه {len(pdf)} صفحة، والحد {max_pages}. قسّمه إلى دفعات.")
        pages = []
        for page in pdf:
            width, height = page.get_size()            # in points (1/72 inch)
            scale = min(dpi / 72, target_side / max(width, height, 1))
            img = page.render(scale=scale).to_pil().convert("RGB")
            out = io.BytesIO()
            img.save(out, format="PNG")
            pages.append(out.getvalue())
            page.close()
        return pages
    finally:
        pdf.close()


def check(data: bytes) -> str:
    """'pdf' or 'image' if the bytes are usable, else raises DocumentError."""
    if is_pdf(data):
        pdf_pages_count(data)
        return "pdf"
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
    except Exception as e:
        raise DocumentError("الملف ليس صورة ولا ملف PDF صالحاً.") from e
    return "image"


def pdf_pages_count(data: bytes) -> int:
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:
        raise DocumentError("تعذّر فتح ملف PDF (قد يكون تالفاً أو محمياً بكلمة سر).") from e
    try:
        n = len(pdf)
    finally:
        pdf.close()
    if n == 0:
        raise DocumentError("ملف PDF لا يحتوي على صفحات.")
    return n


def expand(label: str, data: bytes) -> list[tuple[str, bytes]]:
    """[(label, image bytes)] — one entry for a photo, one per page for a PDF."""
    if not is_pdf(data):
        return [(label, data)]
    pages = pdf_pages(data)
    if len(pages) == 1:
        return [(label, pages[0])]
    return [(f"{label} · صفحة {i}", page) for i, page in enumerate(pages, start=1)]
