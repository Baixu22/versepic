"""Immutable image-output options and safe, finite filename templates."""
from dataclasses import dataclass, field
from datetime import datetime
import os
import re
from string import Formatter


FIELDS = frozenset({"date", "time", "timestamp", "index", "project", "prefix", "suffix"})
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_DEVICE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)


def validate_filename_template(template):
    if not isinstance(template, str) or len(template) > 128:
        raise ValueError("Filename template must be at most 128 characters")
    for _literal, name, spec, conversion in Formatter().parse(template):
        if name is not None and (name not in FIELDS or spec or conversion):
            raise ValueError("Unsupported filename placeholder or formatting")
    return template


def safe_filename_part(text):
    text = _INVALID.sub("_", str(text)).strip(" .")[:120].rstrip(" .")
    if not text:
        return "screenshot"
    return "_" + text if _DEVICE.match(text) else text


def _int(value, default, low, high):
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return default
    try:
        return max(low, min(high, int(value)))
    except ValueError:
        return default


@dataclass(frozen=True)
class ImageOutputOptions:
    directory: str = ""
    quality: int = 85
    size_mode: str = "original"
    width: int = 1600
    template: str = ""
    project: str = ""
    date_folders: bool = False
    moment: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_config(cls, config):
        def get(key, default):
            try:
                return config.get_app_setting(key, default)
            except (TypeError, ValueError):
                return default
        try:
            quality = config.get_screenshot_quality()
        except (TypeError, ValueError):
            quality = 85
        mode = get("screenshot_size_mode", "original")
        if mode not in ("original", "half", "width"):
            mode = "original"
        template = get("screenshot_name_template", "")
        try:
            validate_filename_template(template)
        except (ValueError, TypeError):
            template = ""
        project = get("screenshot_project_name", "")
        directory = config.get_screenshot_save_path()
        return cls(
            directory=directory if isinstance(directory, str) else os.path.expanduser("~/Pictures"),
            quality=_int(quality, 85, 1, 100),
            size_mode=mode, width=_int(get("screenshot_output_width", 1600), 1600, 1, 16384),
            template=template, project=project if isinstance(project, str) else "",
            date_folders=get("screenshot_date_folders", False) is True,
        )

    def output_size(self, width, height):
        if width < 1 or height < 1:
            raise ValueError("Empty source image")
        if self.size_mode == "half":
            size = (max(1, (width + 1) // 2), max(1, (height + 1) // 2))
        elif self.size_mode == "width":
            size = (self.width, max(1, round(height * self.width / width)))
        else:
            return width, height
        if size[0] * size[1] > 100_000_000:
            raise ValueError("Resized output exceeds 100 megapixels")
        return size

    @property
    def uses_index(self):
        return any(name == "index" for _, name, _, _ in Formatter().parse(self.template))

    def filename(self, prefix, suffix, extension, index=1):
        values = {"date": self.moment.strftime("%Y-%m-%d"), "time": self.moment.strftime("%H%M%S"),
                  "timestamp": self.moment.strftime("%Y%m%d_%H%M%S"), "index": f"{index:03d}",
                  "project": self.project, "prefix": prefix, "suffix": suffix}
        raw = self.template.format_map(values) if self.template else "_".join(
            part for part in (prefix, suffix, values["timestamp"]) if part)
        return safe_filename_part(raw) + "." + extension.lower()
