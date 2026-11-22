"""Photos (or PDFs) sent from the phone page wait here until the computer uses them.

The phone and the computer are two separate browser sessions, so the phone page
drops its photos into data/inbox/ and the computer's input page picks them up.
Files never leave this machine and are deleted once the batch is read.
"""
from __future__ import annotations

import io
import socket
import time
from pathlib import Path

from PIL import Image

from . import documents

SUMMARY, SHEETS = "summary", "sheets"
_EXT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "BMP": ".bmp", "MPO": ".jpg", "PDF": ".pdf"}


def save(folder: Path, kind: str, data: bytes) -> Path:
    """Stores one photo or PDF. Raises ValueError if the bytes are neither."""
    if kind not in (SUMMARY, SHEETS):
        raise ValueError("unknown kind")
    if documents.check(data) == "pdf":
        fmt = "PDF"
    else:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
    target = folder / kind
    target.mkdir(parents=True, exist_ok=True)
    if kind == SUMMARY:                      # only one summary page per batch
        for old in target.iterdir():
            old.unlink()
    # The name is generated here; nothing from the phone ends up in a path.
    path = target / f"{time.time_ns()}{_EXT.get(fmt, '.jpg')}"
    path.write_bytes(data)
    return path


def _files(folder: Path, kind: str) -> list[Path]:
    target = folder / kind
    return sorted(p for p in target.iterdir() if p.is_file()) if target.exists() else []


def summary(folder: Path) -> bytes | None:
    files = _files(folder, SUMMARY)
    return files[-1].read_bytes() if files else None


def sheets(folder: Path) -> list[bytes]:
    """Sheet photos in the order they were sent."""
    return [p.read_bytes() for p in _files(folder, SHEETS)]


def counts(folder: Path) -> tuple[int, int]:
    return len(_files(folder, SUMMARY)), len(_files(folder, SHEETS))


def clear(folder: Path) -> None:
    for kind in (SUMMARY, SHEETS):
        for path in _files(folder, kind):
            path.unlink()


def lan_ip() -> str | None:
    """This computer's address on the local network (no data is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))       # documentation address; UDP connect sends nothing
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    return None if ip.startswith("127.") else ip


def qr_png(url: str) -> bytes:
    import segno

    out = io.BytesIO()
    segno.make(url, error="m").save(out, kind="png", scale=7, border=2)
    return out.getvalue()
