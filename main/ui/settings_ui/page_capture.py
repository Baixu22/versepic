# -*- coding: utf-8 -*-
"""截图设置页 — Fluent Design"""
import importlib.util

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QStackedWidget
from core.ui_scale import dialog_scaled
from ui.fluent_lite import (
    SwitchSettingCard, SettingCard as FSettingCard,
    FluentIcon, ComboBox, CaptionLabel,
    PushButton, SegmentedWidget, SpinBox, LineEdit,
)
from settings import color_formats
from settings.tool_settings import SMART_SELECTION_MODES
from .components import SettingCardGroup
from .metadata_controls import add_metadata_controls
from .watermark_controls import add_watermark_controls


def create_capture_page(dialog) -> QWidget:
    """截图設定 ─ 交互行为 + 智能选区 + 放大镜 + 保存设置 + 钉图"""
    view = QWidget()
    view.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(view)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(dialog_scaled(16))
    dialog.capture_sections = SegmentedWidget(view)
    dialog.capture_stack = QStackedWidget(view)
    layout.addWidget(dialog.capture_sections, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addWidget(dialog.capture_stack, 1)

    # ── 截图交互 ──────────────────────────────────────
    grp_behavior = SettingCardGroup(dialog.tr("Capture Behavior"), view)

    double_click_card = SwitchSettingCard(
        FluentIcon.CAMERA,
        dialog.tr("Double-click to Copy and Close"),
        dialog.tr(
            "Double-click the selected screenshot to copy it to the clipboard and close the capture."
        ),
        parent=grp_behavior,
    )
    double_click_card.setChecked(
        dialog.config_manager.get_double_click_copy_close_enabled()
    )
    dialog.double_click_copy_close_toggle = double_click_card
    grp_behavior.addSettingCard(double_click_card)

    cursor_card = SwitchSettingCard(
        FluentIcon.CAMERA, dialog.tr("Include Mouse Pointer"),
        dialog.tr("Capture the real pointer at its current position. Applies to static captures, not GIF or scrolling capture."),
        parent=grp_behavior,
    )
    cursor_card.setChecked(dialog.config_manager.get_app_setting("screenshot_include_cursor", False))
    dialog.include_cursor_toggle = cursor_card
    grp_behavior.addSettingCard(cursor_card)

    cross_tool_card = SwitchSettingCard(
        FluentIcon.EDIT,
        dialog.tr("Enable Ctrl Cross-Tool Selection"),
        dialog.tr(
            "Hold Ctrl and click any editable annotation to adjust it without switching tools."
        ),
        parent=grp_behavior,
    )
    cross_tool_card.setChecked(
        dialog.config_manager.get_cross_tool_selection_enabled()
    )
    dialog.cross_tool_selection_toggle = cross_tool_card
    grp_behavior.addSettingCard(cross_tool_card)

    text_top_card = SwitchSettingCard(
        FluentIcon.FONT,
        dialog.tr("Keep Text Annotations on Top"),
        dialog.tr(
            "Keep text above other annotations, including ones drawn later."
        ),
        parent=grp_behavior,
    )
    text_top_card.setChecked(
        dialog.config_manager.get_text_always_on_top_enabled()
    )
    dialog.text_always_on_top_toggle = text_top_card
    grp_behavior.addSettingCard(text_top_card)

    # ── 智能选区 ──────────────────────────────────────
    grp_smart = SettingCardGroup(dialog.tr("Smart Selection"), view)

    # 三档做成一个下拉框而不是"总开关 + 下钻子开关"：配置本来就只有
    # off/window/element 三个值，拆成两个开关会多出"总开关关着、下钻开着"
    # 这个非法组合，只能再用 setEnabled 联动去遮。
    mode_card = FSettingCard(
        FluentIcon.CAMERA,
        dialog.tr("Detection Mode"),
        dialog.tr(
            "Snap the selection to the window or control under the cursor. "
            "Control detection reads the accessibility tree and takes longer on "
            "large windows."
        ),
        parent=grp_smart,
    )
    dialog.smart_mode_combo = ComboBox(mode_card)
    for label, mode in ((dialog.tr("Off"), "off"),
                        (dialog.tr("Window"), "window"),
                        (dialog.tr("Control"), "element")):
        dialog.smart_mode_combo.addItem(label, userData=mode)
    dialog.smart_mode_combo.setCurrentIndex(
        SMART_SELECTION_MODES.index(dialog.config_manager.get_smart_selection_mode())
    )
    mode_card.addControl(dialog.smart_mode_combo)
    grp_smart.addSettingCard(mode_card)

    smart_anim_card = SwitchSettingCard(
        FluentIcon.SYNC,
        dialog.tr("Selection Switch Animation"),
        dialog.tr("Slide the selection when it moves from one window or control to another."),
        parent=grp_smart,
    )
    smart_anim_card.setChecked(dialog.config_manager.get_smart_selection_animation())
    dialog.smart_animation_toggle = smart_anim_card
    grp_smart.addSettingCard(smart_anim_card)

    # ── 放大镜 ────────────────────────────────────────
    grp_magnifier = SettingCardGroup(dialog.tr("Magnifier"), view)

    magnifier_card = SwitchSettingCard(
        FluentIcon.SEARCH,
        dialog.tr("Show Magnifier"),
        dialog.tr("Follows the cursor while selecting, and picks the color under it."),
        parent=grp_magnifier,
    )
    magnifier_card.setChecked(dialog.config_manager.get_app_setting("magnifier_enabled"))
    dialog.magnifier_enabled_toggle = magnifier_card
    grp_magnifier.addSettingCard(magnifier_card)

    grid_card = SwitchSettingCard(
        FluentIcon.LAYOUT,
        dialog.tr("Pixel Grid"),
        dialog.tr("Outline each pixel in the magnified view. Hidden at low zoom, where the lines would cover the pixels."),
        parent=grp_magnifier,
    )
    grid_card.setChecked(dialog.config_manager.get_app_setting("magnifier_grid"))
    dialog.magnifier_grid_toggle = grid_card
    grp_magnifier.addSettingCard(grid_card)

    swatch_card = SwitchSettingCard(
        FluentIcon.BRUSH,
        dialog.tr("Color Swatch"),
        dialog.tr("Show the picked color in the top-right corner of the magnified view."),
        parent=grp_magnifier,
    )
    swatch_card.setChecked(dialog.config_manager.get_app_setting("magnifier_swatch"))
    dialog.magnifier_swatch_toggle = swatch_card
    grp_magnifier.addSettingCard(swatch_card)

    hint_card = SwitchSettingCard(
        FluentIcon.INFO,
        dialog.tr("Shortcut Hint"),
        dialog.tr("Show the color-copy shortcut under the readings. Off makes the magnifier shorter."),
        parent=grp_magnifier,
    )
    hint_card.setChecked(dialog.config_manager.get_app_setting("magnifier_hint"))
    dialog.magnifier_hint_toggle = hint_card
    grp_magnifier.addSettingCard(hint_card)

    # 格式可以勾选多条、还能自己加，一个下拉装不下，另开一个管理窗口。
    # 编辑结果先存在 dialog 上，点「应用」时才落盘。
    fmt_card = FSettingCard(
        FluentIcon.PALETTE,
        dialog.tr("Color Formats"),
        dialog.tr("Which formats the magnifier shows, and which one the copy shortcut uses."),
        parent=grp_magnifier,
    )
    dialog.magnifier_color_formats = color_formats.load(dialog.config_manager)
    manage_btn = PushButton(dialog.tr("Manage Color Formats"), fmt_card)
    manage_btn.clicked.connect(lambda: _manage_color_formats(dialog))
    dialog.magnifier_color_formats_btn = manage_btn
    fmt_card.addControl(manage_btn)
    grp_magnifier.addSettingCard(fmt_card)

    # ── 截图保存 ──────────────────────────────────────
    grp_save = SettingCardGroup(dialog.tr("Save Settings"), view)

    save_card = SwitchSettingCard(
        FluentIcon.SAVE,
        dialog.tr("Auto-save Screenshots"),
        dialog.tr("Automatically saves as file when capturing."),
        parent=grp_save,
    )
    save_card.setChecked(dialog.config_manager.get_screenshot_save_enabled())
    dialog.save_toggle = save_card
    grp_save.addSettingCard(save_card)

    # 写入文件路径到剪贴板（CF_HDROP）。是否生效取决于自动保存截图是否
    # 开启（没有落盘就没有路径可写），这个依赖在 ActionTools 里按需读取
    # 判断，不在 UI 上做联动禁用——开关各自独立存储，互不覆盖，重新打开
    # 自动保存时也不需要再点一次这个开关。
    file_ref_card = SwitchSettingCard(
        FluentIcon.COMMAND_PROMPT,
        dialog.tr("Write File Path to Clipboard"),
        dialog.tr(
            "Lets tools that only recognize a file path (e.g. some terminal apps) "
            "paste the screenshot too. Requires Auto-save Screenshots to be enabled."
        ),
        parent=grp_save,
    )
    file_ref_card.setChecked(dialog.config_manager.get_clipboard_file_reference_enabled())
    dialog.clipboard_file_reference_toggle = file_ref_card
    grp_save.addSettingCard(file_ref_card)

    # 保存路径。路径本身当作卡片描述，按钮走控件列，和同组其它卡片对齐。
    path_card = FSettingCard(
        FluentIcon.FOLDER,
        dialog.tr("Save Folder"),
        dialog.config_manager.get_screenshot_save_path(),
        parent=grp_save,
    )
    dialog.save_path_lbl = path_card.contentLabel

    btn_change = PushButton(dialog.tr("Change"), path_card)
    btn_change.clicked.connect(dialog._change_save_dir)
    btn_open = PushButton(dialog.tr("Open"), path_card)
    btn_open.clicked.connect(dialog._open_save_dir)
    path_card.addControl(btn_change)
    path_card.addControl(btn_open)
    grp_save.addSettingCard(path_card)

    # 保存格式
    fmt_card = FSettingCard(
        FluentIcon.DOCUMENT,
        dialog.tr("Save Format"),
        dialog.tr("File format for auto-saved screenshots.") + "\n"
        + dialog.tr("Transparent areas use white in JPG, BMP and PDF."),
        parent=grp_save,
    )
    dialog.screenshot_format_combo = ComboBox(fmt_card)
    dialog.screenshot_format_combo.addItem("PNG", userData="PNG")
    dialog.screenshot_format_combo.addItem("JPG", userData="JPG")
    dialog.screenshot_format_combo.addItem("BMP", userData="BMP")
    dialog.screenshot_format_combo.addItem("WebP", userData="WEBP")
    dialog.screenshot_format_combo.addItem("PDF", userData="PDF")
    _fmt_idx = {"PNG": 0, "JPG": 1, "BMP": 2, "WEBP": 3, "PDF": 4}.get(
        dialog.config_manager.get_screenshot_format().upper(), 0
    )
    dialog.screenshot_format_combo.setCurrentIndex(_fmt_idx)
    fmt_card.addControl(dialog.screenshot_format_combo)
    grp_save.addSettingCard(fmt_card)
    _add_output_controls(dialog, grp_save)
    add_watermark_controls(dialog, grp_save)
    add_metadata_controls(dialog, grp_save)

    quick_card = FSettingCard(
        FluentIcon.CAMERA, dialog.tr("Quick Capture Result"),
        dialog.tr("Copy also follows the auto-save setting. Ordinary screenshots are unchanged."),
        parent=grp_save,
    )
    dialog.quick_capture_result_combo = ComboBox(quick_card)
    dialog.quick_capture_result_combo.addItem(dialog.tr("Open in editor"), "edit")
    dialog.quick_capture_result_combo.addItem(dialog.tr("Copy directly"), "copy")
    index = dialog.quick_capture_result_combo.findData(
        dialog.config_manager.get_app_setting("quick_capture_result", "edit"))
    dialog.quick_capture_result_combo.setCurrentIndex(max(0, index))
    quick_card.addControl(dialog.quick_capture_result_combo)
    grp_save.addSettingCard(quick_card)

    # ── 钉图 ──────────────────────────────────────────
    # 自动开工具栏和自动 OCR 都是「钉完图之后自动做什么」，归在一处。
    grp_pin = SettingCardGroup(dialog.tr("Pin Settings"), view)

    pin_toolbar_card = SwitchSettingCard(
        FluentIcon.PIN,
        dialog.tr("Auto-show Drawing Tools on Pin"),
        dialog.tr("On: Shows toolbar when mouse enters pinned window.")
        + "\n"
        + dialog.tr("Off: Show via right-click toolbar button."),
        parent=grp_pin,
    )
    pin_toolbar_card.setChecked(dialog.config_manager.get_pin_auto_toolbar())
    dialog.pin_auto_toolbar_toggle = pin_toolbar_card
    grp_pin.addSettingCard(pin_toolbar_card)

    # OCR 可用性检测：走 ocr 模块的官方多引擎检测（含 ppocr_rust / windows_media_ocr），
    # 而不是只看 windows_media_ocr —— 否则装了 ppocr_rust 也会误报“无 OCR 版本”。
    try:
        from ocr import is_ocr_available
        ocr_available = bool(is_ocr_available())
    except Exception:
        # 兜底：ocr 模块不可导入时，退回到最基础的探测
        ocr_available = (
            importlib.util.find_spec("ppocr_rust") is not None
            or importlib.util.find_spec("windows_media_ocr") is not None
        )
    ocr_card = SwitchSettingCard(
        FluentIcon.FONT,
        dialog.tr("Automatically recognize text after pinning"),
        dialog.tr(
            "On very low-end computers, OCR after pinning may cause a brief stutter. "
            "Turn off automatic recognition if needed."
        ),
        parent=grp_pin,
    )
    ocr_card.setChecked(
        dialog.config_manager.get_ocr_enabled() if ocr_available else False
    )
    if not ocr_available:
        ocr_card.setEnabled(False)
        ocr_card.setChecked(False)
    dialog.ocr_enable_toggle = ocr_card
    grp_pin.addSettingCard(ocr_card)

    if not ocr_available:
        no_ocr_card = FSettingCard(
            FluentIcon.INFO,
            dialog.tr("No OCR Version / OCR module not found"),
            parent=grp_pin,
        )
        grp_pin.addSettingCard(no_ocr_card)

    # 保存提示紧邻保存设置，避免跨越整个页面才能找到。
    hint = CaptionLabel(
        dialog.tr("With auto-save off, the screenshot is still copied to the clipboard."),
        view,
    )
    sections = (
        ("general", dialog.tr("General"), (grp_behavior, grp_smart)),
        ("magnifier", dialog.tr("Magnifier"), (grp_magnifier,)),
        ("saving", dialog.tr("Saving and Pins"), (grp_save, hint, grp_pin)),
    )
    for key, title, widgets in sections:
        scroll = QScrollArea(dialog.capture_stack)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.setAccessibleName(title)
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, dialog_scaled(10), 0)
        section_layout.setSpacing(dialog_scaled(16))
        for widget in widgets:
            section_layout.addWidget(widget)
        section_layout.addStretch()
        scroll.setWidget(section)
        dialog.capture_stack.addWidget(scroll)
        dialog.capture_sections.addItem(key, title)
    section_keys = [key for key, _, _ in sections]
    dialog.capture_sections.currentItemChanged.connect(
        lambda key: dialog.capture_stack.setCurrentIndex(section_keys.index(key))
    )
    return view
 


def _manage_color_formats(dialog):
    """打开颜色格式管理窗口，确定后把结果留在 dialog 上等「应用」。"""
    from .color_format_dialog import ColorFormatDialog

    editor = ColorFormatDialog(dialog.magnifier_color_formats, dialog)
    if editor.exec():
        dialog.magnifier_color_formats = editor.entries()


def _add_output_controls(dialog, group):
    from dataclasses import replace
    from datetime import datetime
    from core.image_output import ImageOutputOptions, validate_filename_template
    options = ImageOutputOptions.from_config(dialog.config_manager)

    def card(title, description=""):
        result = FSettingCard(FluentIcon.DOCUMENT, dialog.tr(title), dialog.tr(description) if description else "", parent=group)
        group.addSettingCard(result)
        return result

    size = card("Saved Image Size", "These settings affect saved files; clipboard images keep their original size.")
    dialog.output_size_combo = ComboBox(size)
    for value, label in (("original", "Original size"), ("half", "50% size"), ("width", "Specified width")):
        dialog.output_size_combo.addItem(dialog.tr(label), value)
    dialog.output_size_combo.setCurrentIndex(max(0, dialog.output_size_combo.findData(options.size_mode)))
    dialog.output_width_spin = SpinBox(size)
    dialog.output_width_spin.setRange(1, 16384)
    dialog.output_width_spin.setSuffix(" px")
    dialog.output_width_spin.setValue(options.width)
    size_controls = QWidget(size)
    size_controls_layout = QVBoxLayout(size_controls)
    size_controls_layout.setContentsMargins(0, 0, 0, 0)
    size_controls_layout.setSpacing(dialog_scaled(6))
    size_controls_layout.addWidget(dialog.output_size_combo)
    size_controls_layout.addWidget(dialog.output_width_spin)
    size.addControl(size_controls)
    dialog.output_width_spin.setEnabled(options.size_mode == "width")
    dialog.output_size_combo.currentIndexChanged.connect(
        lambda: dialog.output_width_spin.setEnabled(dialog.output_size_combo.currentData() == "width"))

    quality = card("Image Quality", "Applies to JPG and WebP only. PNG and BMP remain lossless.")
    dialog.output_quality_spin = SpinBox(quality)
    dialog.output_quality_spin.setRange(1, 100)
    dialog.output_quality_spin.setValue(options.quality)
    quality.addControl(dialog.output_quality_spin)

    presets = card("Output Presets")
    for label, fmt, mode, width, quality_value in (("Original PNG", "PNG", "original", 1600, 85),
                                                 ("Share WebP", "WEBP", "half", 1280, 80)):
        button = PushButton(dialog.tr(label), presets)
        def apply_preset(checked=False, f=fmt, m=mode, w=width, q=quality_value):
            dialog.screenshot_format_combo.setCurrentIndex(dialog.screenshot_format_combo.findData(f))
            dialog.output_size_combo.setCurrentIndex(dialog.output_size_combo.findData(m))
            dialog.output_width_spin.setValue(w)
            dialog.output_quality_spin.setValue(q)
        button.clicked.connect(apply_preset)
        presets.addControl(button)

    naming = card("Automatic File Names", "Leave empty for the original naming. Fields: {date}, {time}, {timestamp}, {index}, {project}, {prefix}, {suffix}.")
    dialog.output_template_edit = LineEdit(naming)
    dialog.output_template_edit.setMaxLength(128)
    dialog.output_template_edit.setText(dialog.config_manager.get_app_setting("screenshot_name_template", ""))
    naming.addControl(dialog.output_template_edit)
    project = card("Project Name", "Optional text for the {project} field. Window titles are never added automatically.")
    dialog.output_project_edit = LineEdit(project)
    dialog.output_project_edit.setMaxLength(64)
    dialog.output_project_edit.setText(options.project)
    project.addControl(dialog.output_project_edit)
    folders = SwitchSettingCard(FluentIcon.FOLDER, dialog.tr("Date Subfolders"),
                                dialog.tr("Place automatically named images in a YYYY-MM-DD folder."), parent=group)
    folders.setChecked(options.date_folders)
    dialog.output_date_toggle = folders
    group.addSettingCard(folders)
    preview = card("File Name Preview", "Example for a normal screenshot; capture time and collisions determine the final name.")
    dialog.output_name_preview = CaptionLabel(preview)
    preview.addControl(dialog.output_name_preview)

    def update_preview():
        try:
            template = validate_filename_template(dialog.output_template_edit.text())
            sample = replace(options, template=template, project=dialog.output_project_edit.text(), moment=datetime.now())
            text = sample.filename("", "", dialog.screenshot_format_combo.currentData())
            if dialog.output_date_toggle.isChecked():
                text = sample.moment.strftime("%Y-%m-%d/") + text
            dialog.output_name_preview.setText(text)
        except ValueError:
            dialog.output_name_preview.setText(dialog.tr("Invalid template: use only the listed fields, without formatting."))
    dialog.output_template_edit.textChanged.connect(update_preview)
    dialog.output_project_edit.textChanged.connect(update_preview)
    dialog.output_date_toggle.checkedChanged.connect(update_preview)
    dialog.screenshot_format_combo.currentIndexChanged.connect(update_preview)
    update_preview()
