"""Reads photographed sheets with a LOCAL vision model served by Ollama.

Privacy: images are sent only to the Ollama server on this machine. A non-local
OLLAMA_HOST is refused unless SHEETCHECK_ALLOW_REMOTE=1 is set on purpose.

The model only transcribes text. It never calculates: all number/date parsing
and every check happens in Python (parsing.py / verification.py).
"""
from __future__ import annotations

import io
import json
import os
import re
from typing import Callable
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageOps

from .models import (
    F_AMOUNT,
    F_DATE,
    F_ROUNDING,
    F_SERIAL,
    F_STAMP,
    F_TAX,
    F_TOTAL,
    UNCLEAR,
    Reading,
    RowReading,
    SheetExtraction,
    SummaryExtraction,
)
from .parsing import normalize_digits

DEFAULT_HOST = "http://127.0.0.1:11434"
_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class ExtractionError(RuntimeError):
    """Raised with an Arabic message suitable for showing to the user."""


# --- local-only guard --------------------------------------------------------

def ollama_host() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip() or DEFAULT_HOST
    if "://" not in host:
        host = "http://" + host
    return host


def is_local_host(host: str) -> bool:
    name = (urlparse(host).hostname or "").lower()
    return name in _LOCAL_NAMES


def _client():
    import ollama

    host = ollama_host()
    if not is_local_host(host) and os.environ.get("SHEETCHECK_ALLOW_REMOTE") != "1":
        raise ExtractionError(
            f"عنوان Ollama ({host}) ليس على هذا الجهاز. تم إيقاف الاستخراج حفاظاً على "
            "خصوصية البيانات."
        )
    # 0.0.0.0 is a listen address, not something to connect to.
    host = host.replace("0.0.0.0", "127.0.0.1")
    return ollama.Client(host=host, timeout=1800)


def server_status(model: str) -> tuple[bool, bool, str]:
    """(server reachable, model installed, Arabic message)."""
    try:
        names = [m.model for m in _client().list().models]
    except ExtractionError as e:
        return False, False, str(e)
    except Exception:
        return False, False, "خادم Ollama لا يعمل. شغّل برنامج Ollama ثم أعد المحاولة."
    wanted = model if ":" in model else model + ":latest"
    if wanted not in names:
        return True, False, f"النموذج {model} غير منزّل. نفّذ: ollama pull {model}"
    return True, True, f"النموذج المحلي جاهز: {model}"


# --- image preparation ---------------------------------------------------------

def load_image(data: bytes, max_side: int = 2400) -> Image.Image:
    """Fix phone rotation, limit the size, boost contrast."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return ImageOps.autocontrast(img, cutoff=1)


# The model turns every 32x32 pixels into one token, and the image, the prompt and the
# answer must share num_ctx (4096). 2.2 million pixels (~2150 tokens) leaves room for the
# rest; a short wide page sent whole at 2400 px did not fit.
MODEL_MAX_PIXELS = 2_200_000


def to_jpeg(img: Image.Image, max_pixels: int = MODEL_MAX_PIXELS) -> bytes:
    if img.width * img.height > max_pixels:
        factor = (max_pixels / (img.width * img.height)) ** 0.5
        img = img.resize((max(1, int(img.width * factor)), max(1, int(img.height * factor))),
                         Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def prepare_image(data: bytes, max_side: int = 1600) -> bytes:
    """Whole photo, cleaned up, as JPEG bytes."""
    return to_jpeg(load_image(data, max_side))


def split_strips(img: Image.Image, ratio: float) -> list[Image.Image]:
    """Cuts the page into horizontal strips about width/ratio tall.

    The model squeezes every image into the same small budget, so a whole page
    leaves each digit only a few pixels. A strip of a few rows keeps them large.
    Each cut is placed on the pixel row with the least ink near the ideal position,
    so it falls between two written lines instead of through one.
    """
    width, height = img.size
    if ratio <= 0:
        return [img]
    target = max(width / ratio, 1)
    count = max(round(height / target), 1)
    if count == 1:
        return [img]

    gray = np.asarray(img.convert("L"), dtype=np.int16)
    paper = np.percentile(gray, 90)
    ink = (gray < paper * 0.6).sum(axis=1).astype(float)
    ink = np.convolve(ink, np.ones(5) / 5, mode="same")

    step = height / count
    cuts = [0]
    for k in range(1, count):
        centre = int(k * step)
        low = max(cuts[-1] + int(step * 0.5), centre - int(step * 0.3))
        high = min(height - 1, centre + int(step * 0.3))
        if high <= low:
            cuts.append(centre)
            continue
        # least ink first, then closest to the ideal position
        best = min(range(low, high), key=lambda y: (round(ink[y]), abs(y - centre)))
        cuts.append(int(best))
    cuts.append(height)
    pad = 4
    return [
        img.crop((0, max(top - pad, 0), width, min(bottom + pad, height)))
        for top, bottom in zip(cuts, cuts[1:])
    ]


# --- prompts and schemas ---------------------------------------------------------

_COMMON_RULES = """Rules:
- Transcribe exactly what is written. Do NOT calculate, correct, complete or guess missing values.
- Copy every digit exactly as it is written. Do not skip, add or guess a digit, and do not
  convert between digit styles: if the page uses Arabic-Indic digits (٠١٢٣٤٥٦٧٨٩) keep them.
  In Arabic-Indic handwriting the zero ٠ is a small dot and ٥ is a small circle: count every dot.
- If a cell is empty, return "" for it.
- If any value is hard to read (smudged, overwritten, cut off, ambiguous digit), still give your
  best reading, and add an entry to "unclear" naming the field, a short reason in Arabic, and the
  other possible readings in "alternatives".
- Output JSON only."""

SHEET_PROMPT = """This is a phone photo of one handwritten Arabic ledger sheet (كشف).
Read EVERY row of the table from top to bottom. Do not skip rows and do not invent rows.
For each row return:
- "serial": the serial number (التسلسل / الرقم المتسلسل). If the Arabic letter م is written
  next to it (a repeated serial), keep it attached, e.g. "1255م".
- "amount": the amount of money (المبلغ).
- "date": the date (التاريخ) as written, day/month/year. If the cell has a ditto mark or is
  blank because it repeats the row above, return "".
Also return "sheet_number": the sheet/page number written on the sheet (رقم الورقة / الصفحة), or ""
if none, and "sheet_date": a date written once in the header for the whole sheet, or "".
Ignore totals rows, signatures and any other columns.

""" + _COMMON_RULES

STRIP_PROMPT = """This image is one horizontal strip cut from a phone photo of a handwritten Arabic
ledger sheet (كشف). {columns}
Read every complete table row in this strip from top to bottom. Do not skip rows and do not invent rows.
Skip the header row, totals rows, signatures and anything that is not a table row. If the strip
contains no table rows, return an empty "rows" list.
For each row return:
- "serial": the serial number (التسلسل / الرقم المتسلسل). If the Arabic letter م is written
  next to it (a repeated serial), keep it attached, e.g. "1255م".
- "amount": the amount of money (المبلغ).
- "date": the date (التاريخ) as written, day/month/year. If the cell has a ditto mark or is
  blank because it repeats the row above, return "".

""" + _COMMON_RULES

LAYOUT_PROMPT = """This is a phone photo of one Arabic ledger sheet (كشف) containing a table.
Return:
- "columns": the texts of the table's column headers, listed from right to left, exactly as
  written. Return an empty list if the table has no header row.
- "sheet_number": the sheet/page number written on the sheet (رقم الورقة / الصفحة), or "".
- "sheet_date": a date written once at the top for the whole sheet, or "".
Output JSON only."""

SUMMARY_PROMPT = """This is a phone photo (or one horizontal strip of a photo) of a handwritten Arabic
summary page (صفحة الخلاصة). Return "" for any value that does not appear in this image.
Return these values as written:
- "total": number 1, the total (المجموع / الإجمالي).
- "tax": number 2, the tax (الضريبة).
- "rounding": number 3, the rounding difference (فرق التقريب / فرق التدوير). Return "" if it is
  not written as a separate number.
- "stamp": the stamp value (الطابع).

""" + _COMMON_RULES


def _unclear_schema(fields: list[str]) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "field": {"type": "string", "enum": fields},
                "reason": {"type": "string"},
                "alternatives": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["field", "reason", "alternatives"],
        },
    }


SHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "sheet_number": {"type": "string"},
        "sheet_date": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "serial": {"type": "string"},
                    "amount": {"type": "string"},
                    "date": {"type": "string"},
                    "unclear": _unclear_schema([F_SERIAL, F_AMOUNT, F_DATE]),
                },
                "required": ["serial", "amount", "date", "unclear"],
            },
        },
    },
    "required": ["sheet_number", "sheet_date", "rows"],
}

LAYOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "columns": {"type": "array", "items": {"type": "string"}},
        "sheet_number": {"type": "string"},
        "sheet_date": {"type": "string"},
    },
    "required": ["columns", "sheet_number", "sheet_date"],
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "total": {"type": "string"},
        "tax": {"type": "string"},
        "rounding": {"type": "string"},
        "stamp": {"type": "string"},
        "unclear": _unclear_schema([F_TOTAL, F_TAX, F_ROUNDING, F_STAMP]),
    },
    "required": ["total", "tax", "rounding", "stamp", "unclear"],
}


# --- model call ------------------------------------------------------------------

def _ask(
    image: bytes,
    prompt: str,
    schema: dict,
    model: str,
    num_ctx: int,
    temperature: float = 0.0,
    on_progress: Callable[[int], None] | None = None,
) -> dict:
    client = _client()
    kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": prompt, "images": [image]}],
        format=schema,
        options={"temperature": temperature, "num_ctx": num_ctx, "num_predict": 2500},
        keep_alive="30m",
        stream=True,
    )
    import ollama

    def run(extra: dict) -> tuple[str, str]:
        text, reason = "", ""
        for chunk in client.chat(**kwargs, **extra):
            text += chunk.message.content or ""
            reason = getattr(chunk, "done_reason", "") or reason
            if on_progress:
                on_progress(len(text))
        return text, reason

    try:
        try:
            # Reasoning variants would spend minutes "thinking" on a CPU; switch it off.
            text, reason = run({"think": False})
        except ollama.ResponseError as e:
            if "think" not in str(e).lower():
                raise
            text, reason = run({})
    except ollama.ResponseError as e:
        if e.status_code == 404:
            raise ExtractionError(
                f"النموذج {model} غير منزّل. نفّذ: ollama pull {model}"
            ) from e
        raise ExtractionError(f"خطأ من Ollama: {e}") from e
    except ExtractionError:
        raise
    except Exception as e:
        raise ExtractionError(
            "تعذّر الاتصال بخادم Ollama المحلي. تأكد أن برنامج Ollama يعمل."
        ) from e

    if reason == "length":
        raise ExtractionError(
            "الورقة طويلة جداً والقراءة انقطعت قبل نهايتها. صوّر الورقة على جزأين."
        )
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ExtractionError("النموذج أعاد رداً غير صالح. أعد المحاولة أو صوّر الورقة من جديد.") from e


# --- raw JSON -> readings -----------------------------------------------------------

def _clean(value) -> str:
    text = str(value or "").strip()
    if re.search(r"[٠-٩۰-۹]", text):
        # Next to Arabic-Indic digits a run of dots is a run of zeros (٠ is written as a dot).
        text = re.sub(r"[.·•]{2,}", lambda m: "٠" * len(m.group()), text)
    return normalize_digits(text).strip()


def _reading(text, field: str, unclear: list) -> Reading:
    r = Reading(text=_clean(text))
    for item in unclear or []:
        if isinstance(item, dict) and item.get("field") == field:
            r.confidence = UNCLEAR
            r.reason = str(item.get("reason") or "").strip()
            alts = [_clean(a) for a in item.get("alternatives") or []]
            r.alternatives = [a for a in dict.fromkeys(alts) if a and a != r.text]
    return r


def rows_from_json(data: dict) -> list[RowReading]:
    rows = []
    for raw in data.get("rows") or []:
        if not isinstance(raw, dict):
            continue
        unclear = raw.get("unclear")
        row = RowReading(
            serial=_reading(raw.get("serial"), F_SERIAL, unclear),
            amount=_reading(raw.get("amount"), F_AMOUNT, unclear),
            date=_reading(raw.get("date"), F_DATE, unclear),
        )
        if row.serial.text or row.amount.text:      # drop empty lines of the table
            rows.append(row)
    return rows


def build_sheet(rows: list[RowReading], sheet_number="", sheet_date="") -> SheetExtraction:
    sheet = SheetExtraction(sheet_number=Reading(text=_clean(sheet_number)))
    last_date = _clean(sheet_date)
    for row in rows:
        # A blank / ditto date repeats the one above (or the sheet header date).
        if row.date.text:
            last_date = row.date.text
        elif last_date:
            row.date.text = last_date
        sheet.rows.append(row)
    return sheet


def sheet_from_json(data: dict) -> SheetExtraction:
    return build_sheet(rows_from_json(data), data.get("sheet_number"), data.get("sheet_date"))


def join_strips(parts: list[list[RowReading]]) -> list[RowReading]:
    """Rows of consecutive strips; a row seen at the end of one strip and the start of the next is kept once."""
    rows: list[RowReading] = []
    for part in parts:
        if rows and part and (
            (part[0].serial.text, part[0].amount.text) == (rows[-1].serial.text, rows[-1].amount.text)
        ):
            part = part[1:]
        rows.extend(part)
    return rows


def summary_from_json(data: dict) -> SummaryExtraction:
    unclear = data.get("unclear")
    return SummaryExtraction(
        total=_reading(data.get("total"), F_TOTAL, unclear),
        tax=_reading(data.get("tax"), F_TAX, unclear),
        rounding=_reading(data.get("rounding"), F_ROUNDING, unclear),
        stamp=_reading(data.get("stamp"), F_STAMP, unclear),
    )


# --- double reading ----------------------------------------------------------------

def _cross_check(a: Reading, b: Reading) -> None:
    """Two independent readings that disagree make the value unclear."""
    if a.text == b.text:
        return
    a.confidence = UNCLEAR
    if not a.reason:
        a.reason = "اختلفت القراءتان"
    if b.text and b.text not in a.alternatives:
        a.alternatives.append(b.text)


def merge_sheets(first: SheetExtraction, second: SheetExtraction) -> SheetExtraction:
    """Keep the first reading; flag every value the second reading disagrees on."""
    _cross_check(first.sheet_number, second.sheet_number)
    if len(first.rows) != len(second.rows):
        note = f"عدد الأسطر اختلف بين القراءتين ({len(first.rows)} مقابل {len(second.rows)})"
        for row in first.rows:
            row.serial.confidence = UNCLEAR
            row.serial.reason = row.serial.reason or note
        return first
    for a, b in zip(first.rows, second.rows):
        _cross_check(a.serial, b.serial)
        _cross_check(a.amount, b.amount)
        _cross_check(a.date, b.date)
    return first


def merge_summaries(first: SummaryExtraction, second: SummaryExtraction) -> SummaryExtraction:
    for name in ("total", "tax", "rounding", "stamp"):
        _cross_check(getattr(first, name), getattr(second, name))
    return first


# --- public API -----------------------------------------------------------------------

Step = Callable[[int, int], None]


def _with_hint(prompt: str, hint: str) -> str:
    hint = (hint or "").strip()
    return f"{prompt}\n\nExtra description of this document from the user:\n{hint}" if hint else prompt


def _columns_sentence(columns) -> str:
    columns = [str(c).strip() for c in columns or [] if str(c).strip()]
    if not columns:
        return ("The header row is not visible in this strip: recognise the columns by their content "
                "(the serial grows by one from row to row, the date has day/month/year).")
    return ("The table's columns, from right to left, are: " + " | ".join(columns) +
            ". Use the column positions to find the serial number, the amount and the date.")


def _read_sheet_once(img: Image.Image, cfg: dict, temperature: float,
                     on_progress, on_step: Step | None) -> SheetExtraction:
    model, num_ctx = cfg["model"], int(cfg.get("num_ctx", 4096))
    hint = cfg.get("sheet_hint", "")
    strips = split_strips(img, float(cfg.get("strip_ratio", 0) or 0))
    if len(strips) == 1:
        if on_step:
            on_step(1, 1)
        data = _ask(to_jpeg(img), _with_hint(SHEET_PROMPT, hint), SHEET_SCHEMA, model, num_ctx,
                    temperature, on_progress)
        return sheet_from_json(data)

    total = len(strips) + 1
    if on_step:
        on_step(1, total)
    small = img.copy()
    small.thumbnail((1600, 1600), Image.LANCZOS)
    layout = _ask(to_jpeg(small), LAYOUT_PROMPT, LAYOUT_SCHEMA, model, num_ctx, 0.0, on_progress)
    prompt = _with_hint(
        STRIP_PROMPT.format(columns=_columns_sentence(layout.get("columns"))), hint)
    parts = []
    for i, strip in enumerate(strips, start=2):
        if on_step:
            on_step(i, total)
        data = _ask(to_jpeg(strip), prompt, SHEET_SCHEMA, model, num_ctx, temperature, on_progress)
        parts.append(rows_from_json(data))
    return build_sheet(join_strips(parts), layout.get("sheet_number"), layout.get("sheet_date"))


def extract_sheet(
    image: bytes,
    cfg: dict,
    double_read: bool = False,
    on_progress: Callable[[int], None] | None = None,
    on_step: Step | None = None,
) -> SheetExtraction:
    """`cfg` is the "extraction" section of config.yaml. `on_step(i, n)` reports model calls."""
    img = load_image(image, int(cfg.get("max_image_side", 2400)))
    sheet = _read_sheet_once(img, cfg, 0.0, on_progress, on_step)
    if double_read:
        sheet = merge_sheets(sheet, _read_sheet_once(img, cfg, 0.5, on_progress, on_step))
    return sheet


def _read_summary_once(img: Image.Image, cfg: dict, temperature: float,
                       on_progress, on_step: Step | None) -> SummaryExtraction:
    prompt = _with_hint(SUMMARY_PROMPT, cfg.get("summary_hint", ""))
    strips = split_strips(img, float(cfg.get("summary_strip_ratio", 0) or 0))
    merged = SummaryExtraction()
    for i, strip in enumerate(strips, start=1):
        if on_step:
            on_step(i, len(strips))
        data = _ask(to_jpeg(strip), prompt, SUMMARY_SCHEMA, cfg["model"],
                    int(cfg.get("num_ctx", 4096)), temperature, on_progress)
        part = summary_from_json(data)
        for name in ("total", "tax", "rounding", "stamp"):
            # Each value is taken from the first strip in which it appears.
            if not getattr(merged, name).text and getattr(part, name).text:
                setattr(merged, name, getattr(part, name))
    return merged


def extract_summary(
    image: bytes,
    cfg: dict,
    double_read: bool = False,
    on_progress: Callable[[int], None] | None = None,
    on_step: Step | None = None,
) -> SummaryExtraction:
    img = load_image(image, int(cfg.get("max_image_side", 2400)))
    summary = _read_summary_once(img, cfg, 0.0, on_progress, on_step)
    if double_read:
        summary = merge_summaries(summary, _read_summary_once(img, cfg, 0.5, on_progress, on_step))
    return summary
