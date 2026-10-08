"""Detect candidate text lines and flatten solid redactions into fresh pixels."""

import math
import re

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

EMAIL = re.compile(r"[\w.+-]+\s*@\s*[\w-]+(?:\s*\.\s*[\w-]+)+", re.UNICODE)
PHONE = re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)|"
                   r"(?<!\d)(?:\+\d{1,3}[ -]?)?\(?\d{3,4}\)?[ -]\d{3,4}[ -]\d{4}(?!\d)")


def sensitive_lines(result, image_rect, *, phones=True, emails=True, keywords=()):
    """ponytail: line OCR has no reliable glyph boxes; use full lines until glyph boxes are available."""
    keywords = [word.strip().casefold() for word in keywords if word.strip()]
    found = []
    for block in result.get("data", []):
        text = block.get("text", "")
        if not ((phones and PHONE.search(text)) or (emails and EMAIL.search(text))
                or any(word in text.casefold() for word in keywords)):
            continue
        box = block.get("box", [])
        try:
            xs, ys = zip(*box)
            if len(box) < 4 or not all(math.isfinite(float(v)) for v in (*xs, *ys)):
                continue
            rect = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        except (TypeError, ValueError):
            continue
        rect = rect.adjusted(-3, -3, 3, 3).intersected(QRectF(image_rect)).toAlignedRect()
        if not rect.isEmpty():
            found.append((text, rect))
    return found


def redact_image(image, rectangles):
    # Fresh image drops source metadata; no editable overlay or original pixels are exported.
    output = QImage(image.size(), QImage.Format.Format_ARGB32)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painter.drawImage(output.rect(), image)
    for rectangle in rectangles:
        rect = QRectF(rectangle).toAlignedRect().intersected(output.rect())
        painter.fillRect(rect, Qt.GlobalColor.black)
    painter.end()
    return output
