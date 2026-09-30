from pathlib import Path
import xml.etree.ElementTree as ET

from PySide6.QtTest import QTest
from ui.outline_icons import PATHS, outline_icon
from ui.fluent_lite.navigation import NavigationItemButton


def test_lucide_assets_render(qapp):
    assets = Path(__file__).parents[2] / "svg" / "lucide"
    assert (assets / "LICENSE").is_file()
    assert len(list(assets.glob("*.svg"))) == len(PATHS)
    for svg in assets.glob("*.svg"):
        assert ET.parse(svg).getroot().get("viewBox") == "0 0 24 24"
    for name in PATHS:
        assert not outline_icon(name).pixmap(24, 24).isNull()


def test_selection_motion_reverses_and_respects_reduced_motion(qapp, qtbot):
    button = NavigationItemButton("Group")
    qtbot.addWidget(button)
    button.setCheckable(True)
    button.show()
    previous = qapp.property("uiReducedMotion")
    try:
        qapp.setProperty("uiReducedMotion", False)
        button.setChecked(True)
        QTest.qWait(40)
        button.setChecked(False)
        qtbot.waitUntil(lambda: button._selection_animator.value() == 0.0)
        qapp.setProperty("uiReducedMotion", True)
        button.setChecked(True)
        assert button._selection_animator.value() == 1.0
    finally:
        qapp.setProperty("uiReducedMotion", previous)
