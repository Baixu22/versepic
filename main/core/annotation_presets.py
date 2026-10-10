"""常用标注样式预设（TF-0039）：按工具保存命名样式组合。

只存"每个工具真正生效的字段"白名单，读取时逐项校验：过期、越界、类型不对的
字段被丢掉或夹回范围，不会把坏配置写进工具设置。预设作为一条 JSON 存在应用
设置里，重启后仍在；应用预设写的是"新建该工具时的默认值"。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from PySide6.QtGui import QColor, QUndoCommand

SETTING_KEY = "annotation_presets"
MAX_PRESETS = 60
MAX_NAME_CHARS = 40

TOOL_FIELDS = {
    "pen": ("color", "stroke_width", "opacity", "line_style"),
    "highlighter": ("color", "stroke_width", "opacity", "draw_mode", "line_style"),
    "rect": ("color", "stroke_width", "opacity", "line_style", "corner_radius"),
    "ellipse": ("color", "stroke_width", "opacity", "line_style"),
    "arrow": ("color", "stroke_width", "opacity", "arrow_style"),
    "number": ("color", "stroke_width", "opacity", "style"),
    "callout": ("color", "stroke_width", "opacity", "arrow_style"),
    "magnify": ("color", "stroke_width", "opacity"),
    "mosaic": ("color", "stroke_width", "opacity", "block_size", "draw_mode", "style"),
    "text": (
        "color", "font_size", "font_family", "font_bold", "font_italic", "font_underline",
        "background_enabled", "background_color", "background_opacity",
        "outline_enabled", "outline_color", "outline_width",
        "shadow_enabled", "shadow_color",
    ),
}
COLOR_FIELDS = frozenset({"color", "background_color", "outline_color", "shadow_color"})
BOOL_FIELDS = frozenset({
    "font_bold", "font_italic", "font_underline",
    "background_enabled", "outline_enabled", "shadow_enabled",
})
NUMBER_RANGES = {
    "stroke_width": (1.0, 2048.0),
    "corner_radius": (0.0, 10000.0),
    "font_size": (6.0, 400.0),
    "background_opacity": (0.0, 255.0),
    "outline_width": (0.0, 10.0),
    "block_size": (2.0, 1024.0),
    "opacity": (0.0, 1.0),
}
ENUM_FIELDS = {
    "line_style": ("solid", "dashed", "dashed_dense"),
    "draw_mode": ("freehand", "rect"),
    "style": ("pixelate", "blur", "solid", "hollow_bg", "hollow_all", "no_circle"),
    "arrow_style": (
        "single", "double", "hollow", "line", "line_double",
        "triangle", "triangle_double", "bar", "bar_arrow",
    ),
}


@dataclass
class Preset:
    name: str
    tool_id: str
    values: dict = field(default_factory=dict)


def normalize_value(key, value):
    """把单个字段收敛成合法值；无法收敛时返回 sentinel 表示丢弃。"""
    if key in COLOR_FIELDS:
        color = QColor(value) if not isinstance(value, QColor) else QColor(value)
        if not color.isValid():
            return _DROP
        return color.name() if color.alpha() == 255 else color.name(QColor.NameFormat.HexArgb)
    if key in BOOL_FIELDS:
        return bool(value)
    if key in ENUM_FIELDS:
        return value if value in ENUM_FIELDS[key] else _DROP
    if key in NUMBER_RANGES:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return _DROP
        low, high = NUMBER_RANGES[key]
        return min(high, max(low, number))
    if key == "font_family":
        text = "" if value is None else str(value)
        return text[:128]
    return _DROP


class _Drop:
    __slots__ = ()


_DROP = _Drop()


def sanitize_values(tool_id, raw) -> dict:
    allowed = TOOL_FIELDS.get(tool_id)
    if not allowed or not isinstance(raw, dict):
        return {}
    values = {}
    for key in allowed:
        if key not in raw:
            continue
        normalized = normalize_value(key, raw[key])
        if normalized is not _DROP:
            values[key] = normalized
    return values


def sanitize_preset(raw):
    if not isinstance(raw, dict):
        return None
    tool_id = raw.get("tool_id")
    name = str(raw.get("name", "") or "").strip()[:MAX_NAME_CHARS]
    if tool_id not in TOOL_FIELDS or not name:
        return None
    values = sanitize_values(tool_id, raw.get("values"))
    if not values:
        return None
    return Preset(name=name, tool_id=tool_id, values=values)


def load_presets(manager) -> list:
    raw = ""
    try:
        raw = manager.get_app_setting(SETTING_KEY, "") if manager else ""
    except Exception:
        raw = ""
    try:
        stored = json.loads(raw) if raw else []
    except ValueError:
        stored = []
    presets = []
    seen = set()
    for entry in stored if isinstance(stored, list) else []:
        preset = sanitize_preset(entry)
        if preset is None:
            continue
        key = (preset.tool_id, preset.name)
        if key in seen:
            continue
        seen.add(key)
        presets.append(preset)
        if len(presets) >= MAX_PRESETS:
            break
    return presets


def save_presets(manager, presets) -> list:
    cleaned = []
    seen = set()
    for preset in presets or ():
        entry = sanitize_preset({"name": preset.name, "tool_id": preset.tool_id, "values": preset.values})
        if entry is None:
            continue
        key = (entry.tool_id, entry.name)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(entry)
        if len(cleaned) >= MAX_PRESETS:
            break
    try:
        manager.set_app_setting(SETTING_KEY, json.dumps([
            {"name": p.name, "tool_id": p.tool_id, "values": p.values} for p in cleaned
        ], ensure_ascii=False))
    except Exception:
        return load_presets(manager)
    return cleaned


def find_preset(manager, tool_id, name):
    for preset in load_presets(manager):
        if preset.tool_id == tool_id and preset.name == name:
            return preset
    return None


def upsert_preset(manager, name, tool_id, values):
    name = str(name or "").strip()[:MAX_NAME_CHARS]
    entry = sanitize_preset({"name": name, "tool_id": tool_id, "values": values})
    if entry is None:
        return None
    presets = [p for p in load_presets(manager) if not (p.tool_id == tool_id and p.name == name)]
    presets.append(entry)
    save_presets(manager, presets)
    return entry


def rename_preset(manager, tool_id, name, new_name) -> bool:
    new_name = str(new_name or "").strip()[:MAX_NAME_CHARS]
    if not new_name or new_name == name:
        return False
    presets = load_presets(manager)
    target = None
    for preset in presets:
        if preset.tool_id == tool_id and preset.name == name:
            target = preset
            break
    if target is None:
        return False
    if any(p.tool_id == tool_id and p.name == new_name for p in presets):
        return False
    target.name = new_name
    save_presets(manager, presets)
    return True


def delete_preset(manager, tool_id, name) -> bool:
    presets = load_presets(manager)
    remaining = [p for p in presets if not (p.tool_id == tool_id and p.name == name)]
    if len(remaining) == len(presets):
        return False
    save_presets(manager, remaining)
    return True


def capture_tool_values(manager, tool_id) -> dict:
    """把某个工具当前的默认值抓成一份预设值（只取白名单字段）。"""
    if manager is None or tool_id not in TOOL_FIELDS:
        return {}
    try:
        settings = manager.get_tool_settings(tool_id)
        raw = settings.to_dict() if hasattr(settings, "to_dict") else dict(settings)
    except Exception:
        return {}
    return sanitize_values(tool_id, raw)


def apply_to_tool_defaults(manager, preset) -> bool:
    """应用预设 = 改写该工具的新建默认值（不动画布上已有的图元）。"""
    if manager is None or preset is None:
        return False
    values = sanitize_values(preset.tool_id, preset.values)
    if not values:
        return False
    try:
        manager.update_settings(preset.tool_id, **values)
    except Exception:
        return False
    return True

# ---------------------------------------------------------------------------
# 应用到画布上的图元（可撤销）
# ---------------------------------------------------------------------------


def capture_item_style(item) -> dict:
    """抓一个图元当前可被预设表达的样式字段（颜色/线宽/透明度/样式）。"""
    from PySide6.QtGui import QColor

    values = {}
    color = getattr(item, "color", None)
    if isinstance(color, QColor) and color.isValid():
        values["color"] = color.name() if color.alpha() == 255 else color.name(QColor.NameFormat.HexArgb)
    width = getattr(item, "base_width", None)
    if width is None and hasattr(item, "pen") and hasattr(item.pen(), "widthF"):
        width = item.pen().widthF()
    if width is not None:
        values["stroke_width"] = float(width)
    opacity = None
    if hasattr(item, "get_visual_opacity"):
        try:
            opacity = item.get_visual_opacity()
        except Exception:
            opacity = None
    if opacity is not None:
        values["opacity"] = float(opacity)
    arrow_style = getattr(item, "_arrow_style", None)
    if arrow_style:
        values["arrow_style"] = arrow_style
    if hasattr(item, "style") and isinstance(item.style, str):
        values["style"] = item.style
    return values


def apply_item_style(item, values) -> bool:
    """把预设值应用到单个图元；只走图元已有的 setter，返回是否真的改了。"""
    from PySide6.QtGui import QColor, QPen

    from canvas.items import ArrowItem, NumberItem, TextItem

    changed = False
    if isinstance(item, ArrowItem):
        if "color" in values:
            item.color = QColor(values["color"])
            changed = True
        if "stroke_width" in values:
            item.set_stroke_width(float(values["stroke_width"]))
            changed = True
        if "arrow_style" in values:
            item._arrow_style = ArrowItem.normalize_style(values["arrow_style"])
            changed = True
        if changed:
            item.update_geometry()
    elif isinstance(item, NumberItem):
        if "color" in values:
            item.color = QColor(values["color"])
            changed = True
        if "stroke_width" in values:
            item.set_stroke_width(float(values["stroke_width"]))
            changed = True
        if "style" in values:
            item.set_style(values["style"])
            changed = True
    elif isinstance(item, TextItem):
        if "color" in values:
            item.setDefaultTextColor(QColor(values["color"]))
            changed = True
        if "font_size" in values:
            item.set_font_point_size(float(values["font_size"]))
            changed = True
        if "background_enabled" in values:
            color = QColor(values.get("background_color", item.background_color))
            alpha = int(values.get("background_opacity", item.background_color.alpha()))
            item.set_background(bool(values["background_enabled"]), color, alpha)
            changed = True
        if "outline_enabled" in values:
            color = QColor(values.get("outline_color", item.outline_color))
            item.set_outline(bool(values["outline_enabled"]), color, values.get("outline_width"))
            changed = True
        if "shadow_enabled" in values:
            color = QColor(values.get("shadow_color", item.shadow_color))
            item.set_shadow(bool(values["shadow_enabled"]), color)
            changed = True
    elif hasattr(item, "pen") and hasattr(item, "setPen"):
        pen = QPen(item.pen())
        if "color" in values:
            pen.setColor(QColor(values["color"]))
            changed = True
        if "stroke_width" in values:
            pen.setWidthF(max(1.0, float(values["stroke_width"])))
            changed = True
        if changed:
            item.setPen(pen)
    if "opacity" in values and hasattr(item, "set_visual_opacity"):
        item.set_visual_opacity(float(values["opacity"]))
        changed = True
    if changed and hasattr(item, "update"):
        item.update()
    return changed


def preset_items_for(item):
    """组合标注的两半一起改；其它图元就是它自己。"""
    try:
        from canvas.items.callout_link import expand_with_partners

        return expand_with_partners([item])
    except Exception:
        return [item]


def apply_preset_to_item(preset, item, undo_stack=None) -> bool:
    """把预设应用到画布上的图元（组合标注连带另一半），推一条可撤销命令。"""
    if preset is None or item is None:
        return False
    values = sanitize_values(preset.tool_id, preset.values)
    if not values:
        return False
    command = PresetApplyCommand(preset_items_for(item), values)
    if not command.changed:
        return False
    if undo_stack is not None:
        undo_stack.push(command)
    else:
        command.redo()
    return True


class PresetApplyCommand(QUndoCommand):
    """把预设值应用到一组图元；撤销时恢复应用前的快照。"""

    def __init__(self, items, values, text: str = "Apply Annotation Preset"):
        super().__init__(text)
        self.items = list(items)
        self.values = dict(values)
        self.before = [capture_item_style(entry) for entry in self.items]
        self.changed = False
        for entry in self.items:
            if apply_item_style(entry, self.values):
                self.changed = True
        self.after = [capture_item_style(entry) for entry in self.items]

    def undo(self):
        for entry, state in zip(self.items, self.before):
            apply_item_style(entry, state)

    def redo(self):
        for entry, state in zip(self.items, self.after):
            apply_item_style(entry, state)
