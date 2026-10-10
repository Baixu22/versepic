"""Detect candidate text lines and flatten solid redactions into fresh pixels."""

from dataclasses import asdict, dataclass
from datetime import date
import json
import math
import os
import re
import unicodedata

from PySide6.QtCore import QRectF, QSettings
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

EMAIL = re.compile(r"[\w.+-]+\s*@\s*[\w-]+(?:\s*\.\s*[\w-]+)+", re.UNICODE)
PHONE = re.compile(r"(?<!\d)(?:\+?86[ -]?)?1[3-9](?:[ -]?\d){9}(?!\d)|"
                   r"(?<!\d)(?:\+\d{1,3}[ -]?)?\(?\d{3,4}\)?[ -]\d{3,4}[ -]\d{4}(?!\d)")


# Format/checksum candidates only; neither validates account ownership or identity.
NUMBER = re.compile(r"(?<![A-Za-z0-9])[0-9OoIl|Xx](?:[ \t-]*[0-9OoIl|Xx])*(?![A-Za-z0-9])")
PROVINCES = frozenset("11 12 13 14 15 21 22 23 31 32 33 34 35 36 37 41 42 43 44 45 46 50 51 52 53 54 61 62 63 64 65 71 81 82".split())


@dataclass(frozen=True)
class RedactionRules:
    phones: bool = True
    emails: bool = True
    china_ids: bool = False
    bank_cards: bool = False
    ocr_lookalikes: bool = False

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("Invalid redaction rules")
        if any(type(flag) is not bool for flag in value.values()):
            raise ValueError("Redaction flags must be booleans")
        return cls(**value)


def valid_china_id(value):
    if not re.fullmatch(r"[1-9][0-9]{16}[0-9X]", value) or value[:2] not in PROVINCES:
        return False
    if value[14:17] == "000":
        return False
    try:
        birth = date(int(value[6:10]), int(value[10:12]), int(value[12:14]))
        if not date(1900, 1, 1) <= birth <= date.today():
            return False
    except ValueError:
        return False
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    return "10X98765432"[sum(int(n) * weight for n, weight in zip(value[:17], weights, strict=True)) % 11] == value[-1]


def valid_bank_card(value):
    if not re.fullmatch(r"[1-9][0-9]{12,18}", value) or len(set(value)) == 1:
        return False
    digits = [int(n) for n in value[::-1]]
    return sum(n if i % 2 == 0 else n * 2 - (9 if n >= 5 else 0) for i, n in enumerate(digits)) % 10 == 0


def numeric_candidates(text, *, lookalikes=False):
    for match in NUMBER.finditer(unicodedata.normalize("NFKC", text)):
        value = re.sub(r"[ \t-]", "", match.group()).upper()
        if not 13 <= len(value) <= 19:
            continue
        if lookalikes:
            # Do not turn arbitrary words into numbers. Only long mostly-digit
            # runs allow the limited O/o->0 and I/l/|->1 OCR substitutions.
            if sum(c in "0123456789" for c in value) < 10:
                continue
            value = value.translate(str.maketrans({"O": "0", "I": "1", "L": "1", "|": "1"}))
        yield value


class RedactionPresetStore:
    """Explicitly saved rule flags only, never OCR text, keywords or image data."""
    KEY = "redaction_rule_presets"
    MAX_PRESETS = 20

    def __init__(self, config):
        self.config = config

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 40 or any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("Use 1 to 40 visible characters for a preset name")
        return value.strip()

    def load(self):
        raw = self.config.get_app_setting(self.KEY, "[]")
        if not isinstance(raw, str) or len(raw) > 16000:
            raise ValueError("Invalid redaction preset data")
        records = json.loads(raw)
        if not isinstance(records, list) or len(records) > self.MAX_PRESETS:
            raise ValueError("Invalid redaction preset collection")
        names = set()
        for record in records:
            if not isinstance(record, dict) or set(record) != {"version", "name", "rules"} or type(record["version"]) is not int or record["version"] != 1:
                raise ValueError("Unsupported redaction preset")
            name = self.name(record["name"])
            if name != record["name"] or name.casefold() in names:
                raise ValueError("Duplicate redaction preset name")
            names.add(name.casefold())
            RedactionRules.parse(record["rules"])
        return records

    def _write(self, records):
        old = self.config.get_app_setting(self.KEY, "[]")
        self.config.set_app_setting(self.KEY, json.dumps(records, ensure_ascii=False))
        self.config.qsettings.sync()
        if self.config.qsettings.status() != QSettings.Status.NoError:
            self.config.set_app_setting(self.KEY, old)
            self.config.qsettings.sync()
            raise OSError("Could not save redaction presets")

    def save(self, name, rules):
        name = self.name(name)
        records = self.load()
        if len(records) >= self.MAX_PRESETS:
            raise ValueError("At most 20 presets are supported")
        if any(r["name"].casefold() == name.casefold() for r in records):
            raise ValueError("A preset with this name already exists")
        data = asdict(rules)
        RedactionRules.parse(data)
        self._write(records + [{"version": 1, "name": name, "rules": data}])
        return name

    def delete(self, name):
        records = self.load()
        remaining = [r for r in records if r["name"] != name]
        if len(remaining) == len(records):
            raise ValueError("Preset no longer exists")
        self._write(remaining)


def save_redacted_image(image, rectangles, filename, config):
    """Export new files only, at preview resolution, with no editable source layer."""
    from core.image_output import ImageOutputOptions
    from core.save import SaveService
    extension = os.path.splitext(filename)[1].lower()
    if extension not in (".png", ".jpg", ".jpeg", ".pdf"):
        raise ValueError("Choose PNG, JPEG or PDF")
    rectangles = list(rectangles)
    if not rectangles:
        raise ValueError("Review and select at least one covered area")
    flattened = redact_image(image, rectangles)
    if flattened.isNull():
        raise ValueError("Could not allocate redacted image")
    # Never overwrite the source/history (or another existing user file). Reserve
    # with O_EXCL, then reuse the service's failure-placeholder/atomic-save logic.
    service = SaveService(config)
    descriptor = os.open(filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    service._reserved_paths.add(os.path.abspath(filename))
    return service.save_qimage_to_path(flattened, filename,
        output_options=ImageOutputOptions(size_mode="original", quality=95))


def sensitive_lines(result, image_rect, *, phones=True, emails=True, china_ids=False, bank_cards=False, ocr_lookalikes=False, keywords=()):
    """ponytail: line OCR has no reliable glyph boxes; use full lines until glyph boxes are available."""
    keywords = [word.strip().casefold() for word in keywords if word.strip()]
    found = []
    blocks = result.get("data", []) if isinstance(result, dict) else []
    if not isinstance(blocks, (list, tuple)):
        return found
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = block.get("text", "")
        if not isinstance(text, str):
            continue
        normalized = unicodedata.normalize("NFKC", text)
        numbers = list(numeric_candidates(text, lookalikes=ocr_lookalikes)) if china_ids or bank_cards else []
        if not ((phones and PHONE.search(normalized)) or (emails and EMAIL.search(normalized))
                or (china_ids and any(valid_china_id(n) for n in numbers))
                or (bank_cards and any(valid_bank_card(n) for n in numbers))
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
    if output.isNull():
        raise ValueError("Could not allocate redaction image")
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    painter.drawImage(output.rect(), image)
    for rectangle in rectangles:
        rect = QRectF(rectangle).toAlignedRect().intersected(output.rect())
        painter.fillRect(rect, Qt.GlobalColor.black)
    painter.end()
    return output
