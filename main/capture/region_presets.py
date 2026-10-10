"""User-saved screen regions in existing settings; never store screenshot pixels."""
import ctypes
import json
from math import isfinite
import uuid

from PySide6.QtCore import QRect, QSettings
from PySide6.QtGui import QGuiApplication


class PresetLayoutChanged(ValueError):
    pass


def current_screen_layout():
    import win32api
    layout = []
    for screen in QGuiApplication.screens():
        rect = screen.geometry()
        dpi = [round(screen.logicalDotsPerInchX()), round(screen.logicalDotsPerInchY())]
        try:
            monitor = win32api.MonitorFromPoint((rect.center().x(), rect.center().y()))
            x, y = ctypes.c_uint(), ctypes.c_uint()
            get_dpi = ctypes.windll.shcore.GetDpiForMonitor
            get_dpi.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
            get_dpi.restype = ctypes.c_long
            if get_dpi(int(monitor), 0, ctypes.byref(x), ctypes.byref(y)) == 0:
                dpi = [x.value, y.value]
        except Exception:
            # Qt DPI is the fallback when this Windows query is unavailable.
            pass
        layout.append({"name": screen.name(), "rect": [rect.x(), rect.y(), rect.width(), rect.height()],
                       "dpi": dpi, "primary": screen is QGuiApplication.primaryScreen()})
    return normalize_layout(layout)


def _rect(values):
    if (not isinstance(values, (list, tuple)) or len(values) != 4
            or any(type(v) is not int or abs(v) > 1_000_000 for v in values)
            or values[2] < 8 or values[3] < 8):
        raise ValueError("Invalid saved region")
    return QRect(*values)


def normalize_layout(layout):
    if not isinstance(layout, list) or not layout or len(layout) > 64:
        raise ValueError("Invalid screen layout")
    result = []
    for screen in layout:
        if not isinstance(screen, dict) or not isinstance(screen.get("name"), str):
            raise ValueError("Invalid screen descriptor")
        _rect(screen.get("rect"))
        dpi = screen.get("dpi")
        if (not isinstance(dpi, (list, tuple)) or len(dpi) != 2
                or any(not isinstance(v, (int, float)) or not isfinite(v) or not 24 <= v <= 960 for v in dpi)):
            raise ValueError("Invalid screen scale")
        result.append({"name": screen["name"][:128], "rect": list(screen["rect"]),
                       "dpi": [round(v) for v in dpi], "primary": bool(screen.get("primary", False))})
    return sorted(result, key=lambda s: (s["name"], *s["rect"]))


class RegionPresetStore:
    KEY = "capture_region_presets"

    def __init__(self, config):
        self.config = config

    def load(self):
        try:
            records = json.loads(self.config.get_app_setting(self.KEY, "[]"))
        except (ValueError, TypeError) as exc:
            raise ValueError("Saved region data is invalid; it was not changed") from exc
        if not isinstance(records, list) or len(records) > 100:
            raise ValueError("Invalid saved region collection")
        ids, names = set(), set()
        for record in records:
            if not isinstance(record, dict) or record.get("version") != 1:
                raise ValueError("Unsupported saved region version")
            name = self._name(record.get("name"))
            identifier = record.get("id")
            if not isinstance(identifier, str) or not identifier or identifier in ids or name.casefold() in names:
                raise ValueError("Duplicate or invalid saved region")
            ids.add(identifier)
            names.add(name.casefold())
            _rect(record.get("rect"))
            record["layout"] = normalize_layout(record.get("layout"))
        return records

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64 or any(ord(c) < 32 for c in value):
            raise ValueError("A preset name must contain 1 to 64 visible characters")
        return value.strip()

    def _write(self, records):
        previous = self.config.get_app_setting(self.KEY, "[]")
        self.config.set_app_setting(self.KEY, json.dumps(records, ensure_ascii=False))
        self.config.qsettings.sync()
        if self.config.qsettings.status() != QSettings.Status.NoError:
            self.config.set_app_setting(self.KEY, previous)
            self.config.qsettings.sync()
            raise OSError("Saved region settings could not be written")

    def save(self, name, rect, layout, *, identifier=None, locked=False):
        records = self.load()
        name = self._name(name)
        if any(r["name"].casefold() == name.casefold() and r["id"] != identifier for r in records):
            raise ValueError("A preset with this name already exists")
        if identifier is not None and not any(r["id"] == identifier for r in records):
            raise ValueError("Preset no longer exists")
        if identifier is None and len(records) >= 100:
            raise ValueError("At most 100 saved regions are supported")
        values = [rect.x(), rect.y(), rect.width(), rect.height()]
        _rect(values)
        layout = normalize_layout(layout)
        desktop = QRect()
        for screen in layout:
            desktop = desktop.united(_rect(screen["rect"]))
        if not desktop.contains(rect):
            raise ValueError("Saved region lies outside the current screen layout")
        identifier = identifier or uuid.uuid4().hex
        record = {"version": 1, "id": identifier, "name": name, "rect": values,
                  "layout": normalize_layout(layout), "locked": bool(locked)}
        records = [record if r["id"] == identifier else r for r in records] if any(r["id"] == identifier for r in records) else records + [record]
        self._write(records)
        return identifier

    def rename(self, identifier, name):
        record = self.get(identifier)
        return self.save(name, _rect(record["rect"]), record["layout"], identifier=identifier, locked=record.get("locked", False))

    def delete(self, identifier):
        records = self.load()
        retained = [r for r in records if r["id"] != identifier]
        if len(retained) == len(records):
            return False
        self._write(retained)
        return True

    def get(self, identifier):
        for record in self.load():
            if record["id"] == identifier:
                return record
        raise ValueError("Preset no longer exists")

    def resolve(self, identifier, layout, bounds):
        record = self.get(identifier)
        rect = _rect(record["rect"])
        if record["layout"] != normalize_layout(layout) or not bounds.contains(rect):
            raise PresetLayoutChanged("Screen layout or scaling changed; review the region before using it")
        return rect, record.get("locked", False)
