"""PDF input: every page becomes an image the model can read."""
import io

import pytest
from PIL import Image

from sheetcheck import documents, inbox


def make_pdf(pages: int) -> bytes:
    images = [Image.new("RGB", (595, 842), (255, 255, 255 - 20 * i)) for i in range(pages)]
    out = io.BytesIO()
    images[0].save(out, format="PDF", save_all=True, append_images=images[1:], resolution=72)
    return out.getvalue()


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(out, format="JPEG")
    return out.getvalue()


def test_pdf_pages_become_images():
    pages = documents.expand("دفعة.pdf", make_pdf(3))
    assert [label for label, _ in pages] == ["دفعة.pdf · صفحة 1", "دفعة.pdf · صفحة 2",
                                              "دفعة.pdf · صفحة 3"]
    img = Image.open(io.BytesIO(pages[0][1]))
    assert img.size == pytest.approx((1654, 2339), abs=2)     # A4 at 200 dpi


def test_big_pages_are_capped_and_model_images_fit():
    from sheetcheck import extraction as ex

    big = Image.new("RGB", (4000, 3000), "white")
    out = io.BytesIO()
    big.save(out, format="PDF", resolution=72)                 # a 4000 x 3000 point page
    img = Image.open(io.BytesIO(documents.pdf_pages(out.getvalue())[0]))
    assert max(img.size) == pytest.approx(documents.TARGET_SIDE, abs=2)
    sent = Image.open(io.BytesIO(ex.to_jpeg(Image.new("RGB", (2400, 1656), "white"))))
    assert sent.width * sent.height <= ex.MODEL_MAX_PIXELS


def test_single_page_pdf_keeps_its_name_and_photo_passes_through():
    assert [label for label, _ in documents.expand("a.pdf", make_pdf(1))] == ["a.pdf"]
    data = jpeg()
    assert documents.expand("photo.jpg", data) == [("photo.jpg", data)]


def test_broken_pdf_is_reported():
    with pytest.raises(documents.DocumentError):
        documents.expand("bad.pdf", b"%PDF-1.4 not really")
    with pytest.raises(documents.DocumentError):
        documents.check(b"neither image nor pdf")


def test_phone_inbox_accepts_pdf(tmp_path):
    path = inbox.save(tmp_path, inbox.SHEETS, make_pdf(2))
    assert path.suffix == ".pdf"
    assert documents.is_pdf(inbox.sheets(tmp_path)[0])
    with pytest.raises(ValueError):
        inbox.save(tmp_path, inbox.SHEETS, b"junk")
