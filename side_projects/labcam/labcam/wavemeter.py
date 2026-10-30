"""The wavemeter's display: wavelength (nm) or frequency (GHz), and power, read with Tesseract OCR.

The display is small in the frame (digits about 13 px tall) and Tesseract confuses its 8, 6, 5, 3 and 2 and
sometimes drops the decimal point. So:
- each field is its own instrument (`field` "main" for the wavelength or frequency, "power" for the power),
  whose four corners follow the text; the engine cuts it out straightened and 3x oversampled;
- each frame is read several ways (two enlargements, three small turns around `tilt`), and only the digits
  are kept: the decimal point goes where the display's format puts it (`format`, e.g. "####.###");
- every digit position is voted on over those reads and the last `vote` frames. A position whose winner has
  less than `agree` of the votes shows as "?", and the reading is then `unknown`, not a guess.
"""

from __future__ import annotations

import collections
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np


from .config import Instrument
from .detectors import Detector, Image, Reading

log = logging.getLogger("labcam.wavemeter")

def _find_tesseract() -> str | None:
    """`LABCAM_TESSERACT`, else on PATH, else Windows' usual install folders."""
    named = os.environ.get("LABCAM_TESSERACT")
    if named:
        return named if Path(named).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    for folder in (os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "") + "\\Programs"):
        candidate = Path(folder) / "Tesseract-OCR" / "tesseract.exe"
        if folder and candidate.is_file():
            return str(candidate)
    return None


TESSERACT = _find_tesseract()

# Formats by unit: # is a digit. The unit decides between them where the OCR caught it (G, H or z → GHz).
FORMATS = {"nm": "####.###", "GHz": "######.##", "power": "###.##"}


def digits_for(text: str, fmt: str) -> str | None:
    """The digit string of `text` if it has exactly as many digits as `fmt`."""
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) == fmt.count("#") else None


def with_point(digits: str, fmt: str) -> str:
    """Digits (or "?") placed into `fmt`."""
    out, i = [], 0
    for ch in fmt:
        if ch == "#":
            out.append(digits[i])
            i += 1
        else:
            out.append(ch)
    return "".join(out)


def prepare(roi: Image, scale: float, angle: float) -> Image:
    """Green display text on dark glass → dark text on white, enlarged and turned by `angle` degrees."""
    green = roi[:, :, 1].astype(np.float32)
    big = cv2.resize(green, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if angle:
        turn = cv2.getRotationMatrix2D((big.shape[1] / 2, big.shape[0] / 2), angle, 1.0)
        big = cv2.warpAffine(big, turn, (big.shape[1], big.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    span = max(float(big.max() - big.min()), 1e-6)
    norm = (255 - (big - big.min()) * (255 / span)).astype(np.uint8)
    return cv2.copyMakeBorder(norm, 20, 20, 20, 20, cv2.BORDER_REPLICATE)


def ocr(image: Image, allowed: str) -> str:
    if TESSERACT is None:
        return ""
    ok, png = cv2.imencode(".png", image)
    if not ok:
        return ""
    result = subprocess.run(
        [TESSERACT, "stdin", "stdout", "--psm", "7", "-c", f"tessedit_char_whitelist={allowed}"],
        input=png.tobytes(),
        capture_output=True,
        timeout=10,
    )
    return " ".join(result.stdout.decode("utf-8", "replace").split())


def vote(reads: list[str]) -> tuple[str, list[float]]:
    """Per position, the most common digit and its share of the votes."""
    winners, shares = [], []
    for position in zip(*reads):
        digit, count = collections.Counter(position).most_common(1)[0]
        winners.append(digit)
        shares.append(count / len(reads))
    return "".join(winners), shares


class Wavemeter(Detector):
    oversample = 3.0

    def __init__(self, inst: Instrument) -> None:
        super().__init__(inst)
        self.power = inst.options.get("field", "main") == "power"
        self.frames: collections.deque[tuple[str, list[str]]] = collections.deque(maxlen=int(inst.option("vote", 5)))

    def reset(self) -> None:
        self.frames.clear()

    def _unit(self, texts: list[str]) -> str:
        if self.power:
            return str(self.inst.options.get("unit", "µW"))
        return "GHz" if re.search(r"[GHz]", "".join(texts)) else "nm"

    def update(self, roi: Image) -> Reading:
        if TESSERACT is None:
            return Reading("unknown", "no tesseract", note="install tesseract to read the wavemeter")
        tilt = self.inst.option("tilt", 0.0)
        allowed = "0123456789.uWmn" if self.power else "0123456789.nmGHz"
        # roi is already 3x; 4/3 and 8/3 make 4x and 8x of the camera's pixels.
        texts = [ocr(prepare(roi, s, tilt + a), allowed) for s in (4 / 3, 8 / 3) for a in (-1.5, 0.0, 1.5)]
        unit = self._unit(texts)
        fmt = str(self.inst.options.get("format", FORMATS["power" if self.power else unit]))
        reads = [d for d in (digits_for(t, fmt) for t in texts) if d is not None]
        log.debug("%s OCR %s -> %s", self.inst.name, texts, reads)
        raw = " | ".join(texts)
        if reads:
            self.frames.append((unit, reads))
        # Votes from the recent frames read in the same unit as the newest.
        current = self.frames[-1][0] if self.frames else unit
        fmt = str(self.inst.options.get("format", FORMATS["power" if self.power else current]))
        pool = [r for u, rs in self.frames if u == current for r in rs if len(r) == fmt.count("#")]
        if not pool:
            return Reading("unknown", "unreadable", {"raw": raw}, 0.0, f"no read had the {fmt} format")
        winner, shares = vote(pool)
        agree = self.inst.option("agree", 0.6)
        shown = with_point("".join(d if s >= agree else "?" for d, s in zip(winner, shares)), fmt)
        values: dict[str, float | str | None] = {
            "shown": shown,
            "per_digit": " ".join(f"{s:.0%}" for s in shares),
            "reads": len(pool),
            "raw": raw,
        }
        if "?" not in shown:
            key = "power" if self.power else ("frequency" if current == "GHz" else "wavelength")
            values[key] = float(shown)
        status = "ok" if "?" not in shown and reads else "unknown"
        note = ""
        if "?" in shown:
            note = "some digits unsure: the reads disagree"
        elif not reads:
            note = "this frame unreadable; showing the recent vote"
        return Reading(status, f"{shown} {current}", values, min(shares), note)
