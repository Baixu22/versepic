"""CSV transfer settings, with actions beside the options they affect."""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy
from ui.fluent_lite import BodyLabel, CaptionLabel, ComboBox, Button
from ui.outline_icons import Icon
from ..layout_scale import field_group_gap, scale_ui


def build_import_export_form(dialog):
    def heading(title, description):
        label = BodyLabel(dialog.tr(title))
        label.setProperty("headingSize", 14)
        dialog.detail_layout.addWidget(label)
        caption = CaptionLabel(dialog.tr(description))
        caption.setWordWrap(True)
        dialog.detail_layout.addWidget(caption)

    heading("Export", "Export all saved content to CSV file")
    dialog.detail_layout.addSpacing(scale_ui(8))
    row = QHBoxLayout()
    row.setSpacing(scale_ui(10))
    encoding_label = CaptionLabel(dialog.tr("Encoding:"))
    encoding_label.setWordWrap(False)
    encoding_label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
    row.addWidget(encoding_label)
    dialog.export_encoding_combo = ComboBox()
    dialog.export_encoding_combo.setAccessibleName(dialog.tr("Encoding:"))
    for name, encoding in (("UTF-8 (BOM)", "utf-8-sig"), ("UTF-8", "utf-8"), ("Shift_JIS", "shift_jis"), ("GBK", "gbk")):
        dialog.export_encoding_combo.addItem(name, userData=encoding)
    row.addWidget(dialog.export_encoding_combo)
    export = Button(dialog.tr("📤 Export to CSV").removeprefix("📤").strip(), variant="outline", icon=Icon.UPLOAD)
    export.clicked.connect(dialog._export_to_csv)
    row.addWidget(export)
    row.addStretch()
    dialog.detail_layout.addLayout(row)
    dialog.detail_layout.addSpacing(field_group_gap())
    dialog.import_export_separator = QFrame()
    dialog.import_export_separator.setFixedHeight(1)
    dialog.detail_layout.addWidget(dialog.import_export_separator)
    dialog.detail_layout.addSpacing(field_group_gap())
    heading("Import", "Import content from CSV file (Group, Content, Title)")
    dialog.detail_layout.addSpacing(scale_ui(8))
    row = QHBoxLayout()
    import_button = Button(dialog.tr("📥 Import from CSV").removeprefix("📥").strip(), variant="outline", icon=Icon.DOWNLOAD)
    import_button.clicked.connect(dialog._import_from_csv)
    row.addWidget(import_button)
    row.addStretch()
    dialog.detail_layout.addLayout(row)
    dialog.detail_layout.addSpacing(field_group_gap() * 2)
    heading("CSV Format", "Column 1: Group Name")
    dialog.detail_layout.addWidget(CaptionLabel(dialog.tr("Column 2: Content")))
    dialog.detail_layout.addWidget(CaptionLabel(dialog.tr("Column 3: Title (optional)")))
