"""应用主程序 - 系统托盘集成和全局快捷键管理

负责一次性初始化和管理应用的生命周期，包括系统托盘图标、快捷键钩子、
多窗口实例管理和启动流程。
"""

import sys
import os

# Explicit package diagnostics must run before normal imports/bootstrap so they
# cannot touch personal settings, clipboard data, hotkeys or the running instance.
if __name__ == "__main__" and "--verify-mp4-export" in sys.argv[1:]:
    if len(sys.argv) != 3 or sys.argv[1] != "--verify-mp4-export":
        sys.exit(2)
    from gif.mp4_diagnostics import run as verify_mp4_export
    sys.exit(verify_mp4_export(sys.argv[2]))

from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QFont
from PySide6.QtCore import QObject, Qt, Signal, Slot
from ui.dialogs import show_warning_dialog, show_error_dialog

from core.shortcut_manager import HotkeySystem
from settings import get_tool_settings_manager
from ui.tray_menu import create_tray_menu
from core.logger import (
    setup_logger, get_logger, T,
    log_debug, log_info, log_warning, log_exception
)

# ── 全局版本号 ────────────────────────────────────────────
APP_VERSION = "2.1.3"


def create_fallback_app_icon():
    """绘制占位托盘图标，保证图标资源缺失时托盘依然可见、可点。

    刻意不依赖任何资源文件或主题管理器——走到这里说明资源已经出问题了，
    兜底路径本身不能再有失败的可能。配色沿用应用默认主题色。
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#40E0D0")))
    painter.drawRoundedRect(4, 4, 56, 56, 12, 12)

    font = QFont()
    font.setPixelSize(38)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#10322E"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "J")
    painter.end()

    return QIcon(pixmap)


def create_app_icon():
    """创建应用程序图标 - 加载 SVG，资源不可用时回退到占位图标。

    必须始终返回有效的 QIcon：托盘是本应用唯一的常驻入口，而
    QSystemTrayIcon.setIcon() 不接受 None——返回 None 会让启动直接抛 TypeError，
    用户看到的现象是"双击没有任何反应"。
    """
    from core.resource_manager import ResourceManager
    icon_path = ResourceManager.get_resource_path("svg/versepic.png")

    if os.path.exists(icon_path):
        # 先渲染再判空：文件存在但 SVG 损坏时 pixmap 为空，
        # 直接使用会得到一个完全透明的托盘图标，和缺失一样不可用。
        icon_pixmap = QIcon(icon_path).pixmap(64, 64)
        if not icon_pixmap.isNull():
            # 加载SVG并放大
            pixmap = QPixmap(64, 64)  # 放大到64x64
            pixmap.fill(Qt.GlobalColor.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(0, 0, icon_pixmap)
            painter.end()

            return QIcon(pixmap)

    log_warning(T("托盘图标资源不可用，改用占位图标: {icon_path}", icon_path=icon_path), "Tray")
    return create_fallback_app_icon()

class MainApp(QObject):
    # Rust clipboard watcher may call from a worker thread.  This signal safely
    # marshals clipboard items back to the Qt GUI thread.
    clipboard_item_received = Signal(object)

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        
        # Config - 使用统一的设置管理器
        self.config_manager = get_tool_settings_manager()

        # 应用界面主题必须在创建任何窗口前初始化。截图强调色由
        # core.theme 单独管理，二者职责互不影响。
        from core.ui_theme import get_ui_theme
        self.ui_theme_manager = get_ui_theme().init(
            self.config_manager, self.app
        )
        self.ui_theme_manager.theme_changed.connect(
            self._on_ui_theme_changed
        )
        
        # Logger - 日志初始化，
        setup_logger(self.config_manager)
        self._logger = get_logger()
        self.app.aboutToQuit.connect(self._on_about_to_quit)
        from core.save import save_notifications
        save_notifications().failed.connect(self._on_image_save_failed)

        # Qt 的自动高 DPI 缩放已关闭。首次进入欢迎向导前，按 Windows 的
        # 显示缩放为两套界面比例选一个初始档位；已有值（包括用户选择）不覆盖。
        from core.ui_scale import apply_first_run_scale_defaults
        recommended_scale = apply_first_run_scale_defaults(self.config_manager)
        if recommended_scale is not None:
            log_info(
                T(
                    "首次启动，系统推荐界面比例: {percent}%",
                    percent=recommended_scale,
                ),
                "DPI",
            )
        
        # 初始化翻译系统
        from core.i18n import I18nManager
        # 检查是否有保存的语言设置，如果没有则使用系统语言
        saved_lang = self.config_manager.get_app_setting("language", "__NOT_SET__")
        if saved_lang == "__NOT_SET__":
            # 第一次启动，检测系统语言
            saved_lang = I18nManager.get_system_language()
            self.config_manager.set_app_setting("language", saved_lang)
            log_info(T("首次启动，检测到系统语言: {saved_lang}", saved_lang=saved_lang), "I18n")
        I18nManager.load_language(saved_lang)
        log_info(T("语言设置: {lang_name}", lang_name=I18nManager.get_current_language_name()), "I18n")
        
        # 连接语言切换信号，用于更新托盘菜单等 UI
        I18nManager.instance().language_changed.connect(self._on_language_changed)
        
        # 初始化主题颜色管理器
        from core.theme import get_theme
        get_theme().init(self.config_manager)

        # 初始化操作界面缩放管理器（工具栏/面板建出来之前必须先载入比例）
        from core.ui_scale import get_ui_scale
        get_ui_scale().init(self.config_manager)

        # 初始化独立窗口缩放管理器（设置/剪贴板管理/翻译窗口）
        from core.ui_scale import get_dialog_scale
        get_dialog_scale().init(self.config_manager)
        
        # 输出DPI信息用于调试
        try:
            from PySide6.QtGui import QGuiApplication
            primary_screen = QGuiApplication.primaryScreen()
            if primary_screen:
                dpr = primary_screen.devicePixelRatio()
                logical_dpi = primary_screen.logicalDotsPerInch()
                physical_dpi = primary_screen.physicalDotsPerInch()
                log_debug(f"Device Pixel Ratio: {dpr}", "DPI")
                log_debug(f"Logical DPI: {logical_dpi}", "DPI")
                log_debug(f"Physical DPI: {physical_dpi}", "DPI")
        except Exception as e:
            log_warning(T("无法获取DPI信息: {e}", e=e), "DPI")
        
        # 热键系统先创建，实际注册放到启动预加载完成后，避免预加载期间触发卡顿。
        self.hotkey_system = HotkeySystem()
        self.hotkey_system.set_suppressed(
            self.config_manager.get_app_setting("global_hotkeys_disabled", False)
        )
        
        # 窗口实例
        self.tray_icon = None
        self.settings_window = None
        self.screenshot_window = None
        self._capture_countdown = None
        self._quitting = False
        self._capture_busy = False
        self._collection_resume_timer = None
        self.clipboard_window = None
        # 剪贴板管理器
        self.clipboard_manager = None

        from clipboard.controllers.foreground_tracker import (
            ForegroundWindowTracker, get_current_pid, get_window_pid,
        )
        self._capture_foreground_tracker = ForegroundWindowTracker()
        own_pid = get_current_pid()
        self._capture_foreground_tracker.set_excluded(lambda hwnd: get_window_pid(hwnd) == own_pid)
        self._capture_foreground_tracker.start()

        from translation.smart_translation_controller import SmartTranslationController
        self.smart_translation_controller = SmartTranslationController(self)
        self.clipboard_item_received.connect(self._on_clipboard_item_received)
        self.clipboard_item_received.connect(
            self.smart_translation_controller.on_clipboard_item
        )
        
        # 启动预加载链（截图模块 → 工具栏 → OCR → 设置窗口 → 剪贴板 → 显示主界面）
        from core.bootstrap import PreloadManager
        self._preloader = PreloadManager(self)
        self._preloader.build_and_start()

    def _on_about_to_quit(self):
        """应用退出前收尾"""
        self._cancel_pending_capture()
        if self.clipboard_manager:
            self.clipboard_manager.stop_image_indexing()
        try:
            from translation import TranslationManager

            TranslationManager.cleanup()
        except Exception as e:
            log_exception(e, T("清理翻译线程"))
        try:
            from text_recognition import shutdown_recognition

            shutdown_recognition()
        except Exception as e:
            log_exception(e, T("等待文字识别线程"))
        try:
            if hasattr(self, "_logger") and self._logger:
                self._logger.close()
        except Exception as e:
            log_exception(e, T("关闭logger"))

    def _on_wizard_requested(self):
        """设置窗口请求打开向导：隐藏设置窗口、注销热键，再显示向导，完成后恢复"""
        log_info(T("向导请求：隐藏设置窗口并注销热键"), "MainApp")

        # 1. 隐藏设置窗口
        if self.settings_window:
            self.settings_window.hide()

        # 2. 注销所有热键（向导期间不拦截快捷键）
        self.hotkey_system.unregister_all()

        # 3. 显示向导
        try:
            from ui.welcome import WelcomeWizard
            wizard = WelcomeWizard(self.config_manager)
            wizard.exec()
        except Exception as e:
            log_exception(e, T("向导启动失败"))

        # 4. 向导结束后重新注册热键
        self.update_hotkey()
        log_info(T("向导完成，热键已恢复"), "MainApp")

    def _on_language_changed(self, lang_code: str):
        """语言切换时更新所有 UI 元素"""
        log_debug(T("语言已切换到: {lang_code}，更新 UI", lang_code=lang_code), "I18n")
        
        # 更新托盘菜单
        self._update_tray_menu()
        
        # 设置窗口是预加载的，需要重建才能更新翻译。
        if self.settings_window:
            self._recreate_settings_window()
        
        # 关闭翻译窗口（下次打开时会用新语言创建）
        from translation import TranslationManager
        TranslationManager.instance().close_dialog()

    def _create_tray_menu(self) -> QMenu:
        """创建托盘菜单"""
        return create_tray_menu(self)

    def _on_ui_theme_changed(self, _tokens):
        """主题变化后刷新由 MainApp 持有的原生界面。"""
        self._update_tray_menu()
        if self.settings_window:
            self.settings_window.update()

    def _setup_pin_tray_updates(self):
        """刷新托盘菜单中的钉图数量。"""
        try:
            from pin.pin_manager import PinManager
            pin_manager = PinManager.instance()
            pin_manager.pin_created.connect(lambda _pin: self._update_tray_menu())
            pin_manager.pin_closed.connect(lambda _pin: self._update_tray_menu())
            pin_manager.all_pins_closed.connect(self._update_tray_menu)
        except Exception as e:
            log_exception(e, T("连接钉图托盘菜单刷新信号"))

    def _update_tray_menu(self):
        """重建托盘菜单（用于语言切换后刷新）"""
        if not hasattr(self, 'tray_icon') or not self.tray_icon:
            return

        # 更新 tooltip
        self.tray_icon.setToolTip(self.tr("jietuba - Click to screenshot").replace("jietuba", "VersePic").replace("截图吧", "VersePic"))

        # 重建菜单
        self.tray_icon.setContextMenu(self._create_tray_menu())

    def update_hotkey(self, show_error: bool = False):
        """
        更新所有全局热键（截图、剪贴板和智能翻译）
        
        Args:
            show_error: 是否显示错误提示（设置保存时为 True，启动时为 False）
        """
        
        # 注销所有已注册的热键
        self.hotkey_system.unregister_all()
        self.hotkey_system.set_suppressed(
            self.config_manager.get_app_setting("global_hotkeys_disabled", False)
        )
        
        failed_hotkeys = []  # 收集注册失败的热键
        
        # 注册截图热键
        hotkey = self.config_manager.get_hotkey()
        if hotkey:
            if self.hotkey_system.register_hotkey(hotkey, self.start_screenshot):
                log_info(T("截图热键已注册: {hotkey}", hotkey=hotkey), "Hotkey")
            else:
                log_warning(T("截图热键注册失败: {hotkey}", hotkey=hotkey), "Hotkey")
                failed_hotkeys.append((self.tr("Screenshot"), hotkey))

        from settings.tool_settings import QUICK_CAPTURE_ACTIONS
        for kind, label in QUICK_CAPTURE_ACTIONS:
            for suffix in ("", "_2"):
                key = self.config_manager.get_app_setting(f"quick_{kind}_hotkey{suffix}", "")
                if key and not self.hotkey_system.register_hotkey(
                        key, lambda capture_kind=kind: self.start_quick_capture(capture_kind)):
                    failed_hotkeys.append((self.tr(label), key))

        # 注册截图备用热键
        hotkey_2 = self.config_manager.get_hotkey_2()
        if hotkey_2:
            if self.hotkey_system.register_hotkey(hotkey_2, self.start_screenshot):
                log_info(T("截图备用热键已注册: {hotkey_2}", hotkey_2=hotkey_2), "Hotkey")
            else:
                log_warning(T("截图备用热键注册失败: {hotkey_2}", hotkey_2=hotkey_2), "Hotkey")
                failed_hotkeys.append((self.tr("Screenshot (2)"), hotkey_2))

        # 注册统一翻译热键：有选中文本时显示小窗，否则打开完整输入窗口。
        translation_hotkeys = (
            (self.config_manager.get_translation_hotkey(), self.tr("Translation")),
            (self.config_manager.get_translation_hotkey_2(), self.tr("Translation (2)")),
        )
        for translation_hotkey, label in translation_hotkeys:
            if not translation_hotkey:
                continue
            if self.hotkey_system.register_hotkey(
                translation_hotkey, self.smart_translation_controller.trigger
            ):
                log_info(T("智能翻译热键已注册: {translation_hotkey}", translation_hotkey=translation_hotkey), "Hotkey")
            else:
                log_warning(T("智能翻译热键注册失败: {translation_hotkey}", translation_hotkey=translation_hotkey), "Hotkey")
                failed_hotkeys.append((label, translation_hotkey))
        
        # 注册剪切板热键（如果剪切板功能启用）
        if self.config_manager.get_clipboard_enabled():
            clipboard_hotkey = self.config_manager.get_clipboard_hotkey()
            if clipboard_hotkey:
                if self.hotkey_system.register_hotkey(clipboard_hotkey, self.open_clipboard_window):
                    log_info(T("剪贴板热键已注册: {clipboard_hotkey}", clipboard_hotkey=clipboard_hotkey), "Hotkey")
                else:
                    log_warning(T("剪贴板热键注册失败: {clipboard_hotkey}", clipboard_hotkey=clipboard_hotkey), "Hotkey")
                    failed_hotkeys.append((self.tr("Clipboard"), clipboard_hotkey))

            # 注册剪贴板备用热键
            clipboard_hotkey_2 = self.config_manager.get_clipboard_hotkey_2()
            if clipboard_hotkey_2:
                if self.hotkey_system.register_hotkey(clipboard_hotkey_2, self.open_clipboard_window):
                    log_info(T("剪贴板备用热键已注册: {clipboard_hotkey_2}", clipboard_hotkey_2=clipboard_hotkey_2), "Hotkey")
                else:
                    log_warning(T("剪贴板备用热键注册失败: {clipboard_hotkey_2}", clipboard_hotkey_2=clipboard_hotkey_2), "Hotkey")
                    failed_hotkeys.append((self.tr("Clipboard (2)"), clipboard_hotkey_2))

        # 注册「钉住剪贴板图片」热键（主 + 备用）。刻意放在 clipboard_enabled
        # 判断之外：这条路径优先钉系统剪贴板里的图，历史功能关掉时照样有用。
        # 默认两个都留空——不自作主张占用用户的按键，想用就自己设一个。
        pin_clipboard_hotkeys = (
            (self.config_manager.get_pin_clipboard_hotkey(), self.tr("Pin Clipboard Image")),
            (self.config_manager.get_pin_clipboard_hotkey_2(), self.tr("Pin Clipboard Image (2)")),
        )
        for pin_clipboard_hotkey, label in pin_clipboard_hotkeys:
            if not pin_clipboard_hotkey:
                continue
            if self.hotkey_system.register_hotkey(pin_clipboard_hotkey, self.pin_clipboard_image):
                log_info(T("钉图热键已注册: {pin_clipboard_hotkey}", pin_clipboard_hotkey=pin_clipboard_hotkey), "Hotkey")
            else:
                log_warning(T("钉图热键注册失败: {pin_clipboard_hotkey}", pin_clipboard_hotkey=pin_clipboard_hotkey), "Hotkey")
                failed_hotkeys.append((label, pin_clipboard_hotkey))
        
        # 如果有注册失败的热键且需要显示提示
        if show_error and failed_hotkeys:
            self._show_hotkey_error(failed_hotkeys)

    def set_global_hotkeys_disabled(self, disabled: bool):
        """禁用/启用所有全局热键，并立即应用。"""
        self.config_manager.set_app_setting("global_hotkeys_disabled", disabled)
        self.hotkey_system.set_suppressed(disabled)
        if disabled:
            log_info(T("全局热键已临时禁用（保留注册，仅忽略回调）"), "Hotkey")
        else:
            log_info(T("全局热键已启用"), "Hotkey")
            if not self.hotkey_system.has_registered_hotkeys():
                self.update_hotkey(show_error=True)
    
    def _show_hotkey_error(self, failed_hotkeys: list):
        """显示热键注册失败的提示"""
        
        lines = []
        for name, key in failed_hotkeys:
            lines.append(f"• {name}: {key}")
        
        msg = self.tr("The following hotkeys failed to register:") + "\n\n"
        msg += "\n".join(lines)
        msg += "\n\n" + self.tr("The hotkey may be occupied by other programs. Please try a different combination.")
        
        log_debug(T("显示热键错误提示: {failed_hotkeys}", failed_hotkeys=failed_hotkeys), "Hotkey")
        
        show_warning_dialog(
            None,
            self.tr("Hotkey Registration Failed"),
            msg,
        )

    def setup_tray(self):
        if self.tray_icon:
            return

        if not QSystemTrayIcon.isSystemTrayAvailable():
            show_error_dialog(None, "Error", "System tray not available")
        self.tray_icon = QSystemTrayIcon(self)

        # Use custom icon
        icon = create_app_icon()
        self.tray_icon.setIcon(icon)

        self.tray_icon.setToolTip(self.tr("jietuba - Click to screenshot").replace("jietuba", "VersePic").replace("截图吧", "VersePic"))

        # Menu
        self.tray_icon.setContextMenu(self._create_tray_menu())
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.start_screenshot()

    def _activate_blocking_modal(self) -> bool:
        """模态窗口存在时阻止创建无法交互的截图层。"""
        modal = QApplication.activeModalWidget()
        if modal is None or not modal.isVisible():
            return False

        log_debug(
            T("检测到模态窗口 {modal_type}，忽略截图触发", modal_type=type(modal).__name__),
            "MainApp",
        )
        modal.raise_()
        modal.activateWindow()
        return True
            
    def start_delayed_screenshot(self, seconds):
        """Schedule one capture without taking focus from the target application."""
        if getattr(self, "_quitting", False):
            return
        if self.screenshot_window and getattr(self.screenshot_window, "_session_active", False):
            self.start_screenshot()
            return
        thread = getattr(self, "_capture_thread", None)
        if (getattr(self, "_capture_busy", False) or (thread and thread.isRunning())
                or self._activate_blocking_modal()):
            return
        if getattr(self, "_capture_countdown", None) is None:
            from ui.capture_countdown import CaptureCountdown
            self._capture_countdown = CaptureCountdown()
            self._capture_countdown.finished.connect(self.start_screenshot)
            self._capture_countdown.failed.connect(self._on_capture_failed)
        try:
            self._capture_countdown.start(seconds)
        except Exception as exc:
            log_exception(exc, "Start delayed screenshot")
            self._on_capture_failed()

    def _cancel_pending_capture(self):
        self._quitting = True
        timer = getattr(self, "_collection_resume_timer", None)
        if timer is not None:
            timer.stop()
        countdown = getattr(self, "_capture_countdown", None)
        if countdown is not None:
            countdown.cancel()
        tracker = getattr(self, "_capture_foreground_tracker", None)
        if tracker is not None:
            tracker.stop()

    def _continue_collection_capture(self):
        if getattr(self, "_quitting", False):
            return
        from PySide6.QtCore import QTimer
        if getattr(self, "_collection_resume_timer", None) is None:
            self._collection_resume_timer = QTimer(self)
            self._collection_resume_timer.setSingleShot(True)
            self._collection_resume_timer.timeout.connect(self._start_collection_capture)
        self._collection_resume_timer.start(100)

    def _start_collection_capture(self):
        self.start_screenshot()
        if not getattr(self, "_capture_busy", False):
            self._restore_image_collection()

    def _restore_image_collection(self):
        timer = getattr(self, "_collection_resume_timer", None)
        if getattr(self, "_quitting", False) or (timer and timer.isActive()):
            return
        if self.screenshot_window and getattr(self.screenshot_window, "_session_active", False):
            return
        collection = getattr(self.app, "_image_layout_window", None)
        if collection is not None and collection._hidden_for_capture:
            collection._hidden_for_capture = False
            collection.show()
            collection.raise_()
            collection.activateWindow()

    def _on_image_save_failed(self, _path):
        if not getattr(self, "_quitting", False) and self.tray_icon:
            self.tray_icon.showMessage(
                self.tr("Save failed"),
                self.tr("Could not save the image. Check the output size, folder permissions and free space."),
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def _on_capture_failed(self, reason=""):
        self._capture_busy = False
        self._restore_image_collection()
        if not getattr(self, "_quitting", False) and self.tray_icon:
            self.tray_icon.showMessage(
                self.tr("Screenshot failed"),
                (self.tr("Capture target is unavailable or moved. Use region capture or choose another target.")
                 if reason == "target_unavailable" else
                 self.tr("Could not capture the screen. Please try again.")),
                QSystemTrayIcon.MessageIcon.Warning,
            )

    def start_quick_capture(self, kind):
        from PySide6.QtGui import QCursor
        from capture.quick_capture import make_quick_capture_request
        from core.last_capture_region import get_last_region

        if getattr(self, "_quitting", False) or getattr(self, "_capture_busy", False):
            return
        countdown = getattr(self, "_capture_countdown", None)
        if countdown is not None and countdown.is_pending:
            return
        if self.screenshot_window and getattr(self.screenshot_window, "_session_active", False):
            self.start_screenshot()
            return
        try:
            tracker = getattr(self, "_capture_foreground_tracker", None)
            if tracker is not None:
                tracker.sample()
            action = self.config_manager.get_app_setting("quick_capture_result", "edit")
            if action not in ("edit", "copy"):
                action = "edit"
            request = make_quick_capture_request(
                kind, point=QCursor.pos(), hwnd=tracker.target_hwnd if tracker else None,
                last_region=get_last_region(), action=action,
            )
        except Exception as exc:
            log_exception(exc, "Resolve quick capture target")
            self._on_capture_failed("target_unavailable")
            return
        self.start_screenshot(request=request)

    def _on_capture_result(self, image, desktop, selection, action):
        self._capture_busy = False
        if getattr(self, "_quitting", False):
            return
        if selection is None:
            if action == "private":
                self._on_capture_ready(image, desktop, sensitive=True)
                return
            self._on_capture_ready(image, desktop)
            return
        if self._activate_blocking_modal():
            return
        if action == "copy":
            from core.clipboard_utils import deliver_image_async
            from core.last_capture_region import set_last_region
            from core.save import SaveService

            image = image.copy(selection.translated(-round(desktop.x()), -round(desktop.y())))
            config = self.config_manager
            save = config.get_screenshot_save_enabled()
            deliver_image_async(
                image, save_service=SaveService(config) if save else None,
                save_kwargs={"directory": config.get_screenshot_save_path(), "prefix": "",
                             "image_format": config.get_screenshot_format()} if save else None,
                write_file_reference=config.get_clipboard_file_reference_enabled() if save else False,
            )
            set_last_region(selection)
            self._restore_image_collection()
        else:
            window = self._on_capture_ready(image, desktop)
            if window is not None:
                from PySide6.QtCore import QRectF
                window.scene.selection_model.initialize_confirmed_rect(QRectF(selection))

    def start_sensitive_screenshot(self):
        from core.capture_privacy import ensure_supported
        countdown = getattr(self, "_capture_countdown", None)
        if countdown is not None and countdown.is_pending:
            # An ordinary delayed capture must not fire after the user asked for a
            # one-shot private session. Cancel does not emit finished.
            countdown.cancel()
        if ensure_supported():
            self.start_screenshot(sensitive=True)

    def start_screenshot(self, *, request=None, sensitive=False):
        """启动截图 - 管理截图窗口生命周期"""
        if getattr(self, "_quitting", False):
            return
        countdown = getattr(self, "_capture_countdown", None)
        if countdown is not None and countdown.is_pending:
            return
        
        # 已有截图窗口且会话活跃 → 忽略重复触发，并把焦点还给截图窗口
        if self.screenshot_window and getattr(self.screenshot_window, '_session_active', False):
            log_debug(T("截图窗口已存在，忽略重复触发"), "MainApp")
            self.screenshot_window.activateWindow()
            self.screenshot_window.raise_()
            # 如果有颜色选择器正在显示，重新提到截图窗口上方，防止被全屏窗口遮挡
            from PySide6.QtWidgets import QApplication, QColorDialog
            for w in QApplication.topLevelWidgets():
                if isinstance(w, QColorDialog) and w.isVisible():
                    w.raise_()
                    w.activateWindow()
                    return
            self.screenshot_window.setFocus()
            return

        # QDialog.exec() 的嵌套事件循环仍会处理托盘信号，但应用模态会屏蔽
        # 新截图窗口的输入。此时不创建截图层，转而把现有模态窗口提到前面。
        if self._activate_blocking_modal():
            return
        
        # 后台截图线程正在运行时也忽略重复触发
        if (getattr(self, "_capture_busy", False)
                or (getattr(self, "_capture_thread", None) and self._capture_thread.isRunning())):
            log_debug(T("后台截图线程进行中，忽略重复触发"), "MainApp")
            return

        if sensitive:
            from core.capture_privacy import ensure_supported
            if request is not None or not ensure_supported():
                return

        # 关闭所有已打开的颜色选择器（避免其遮挡截图界面或触发焦点冲突）
        from PySide6.QtWidgets import QApplication, QColorDialog
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QColorDialog) and w.isVisible():
                w.reject()

        # 剪贴板窗口可能被设为粘贴后常驻，会连同它一起被截进图里。用 close
        # 而不是 hide：hide 不会关掉它已弹出的右键菜单，那个菜单是置顶的，
        # 照样会进画面。截图是主功能，不能因为这里出状况就起不来。
        try:
            if self.clipboard_window and self.clipboard_window.isVisible():
                self.clipboard_window.close()
        except Exception as e:
            log_exception(e, T("关闭剪贴板窗口"))

        collection = getattr(self.app, "_image_layout_window", None)
        if collection is not None and collection.isVisible():
            collection._hidden_for_capture = True
            collection.hide()

        log_info(T("启动后台截图线程"), "MainApp")
        
        # 在后台线程执行 mss.grab()，避免主线程被阻塞 100~500ms
        from PySide6.QtCore import QThread, Signal

        include_cursor = self.config_manager.get_app_setting("screenshot_include_cursor", False) is True

        class CaptureThread(QThread):
            captured = Signal(object, object, object, str)
            failed = Signal(str)

            def run(self):
                try:
                    from capture.capture_service import CaptureService
                    service = CaptureService(include_cursor=include_cursor)
                    if request is None:
                        image, rect = service.capture_all_screens()
                        self.captured.emit(image, rect, None, "private" if sensitive else "edit")
                    else:
                        from capture.quick_capture import CaptureTargetUnavailable
                        try:
                            image, rect, selection = request.capture(service)
                        except CaptureTargetUnavailable:
                            self.failed.emit("target_unavailable")
                            return
                        self.captured.emit(image, rect, selection, request.action)
                except Exception as e:
                    log_exception(e, T("后台截图失败"))
                    self.failed.emit("")

        self._capture_busy = True
        self._capture_thread = CaptureThread()
        self._capture_thread.captured.connect(self._on_capture_result)
        self._capture_thread.failed.connect(self._on_capture_failed)
        self._capture_thread.start()

    def _on_capture_ready(self, image, rect, *, sensitive=False):
        """后台截图完成后，在主线程创建或复用截图窗口"""
        if getattr(self, "_quitting", False):
            return
        log_debug(T("后台截图完成，准备截图窗口"), "MainApp")

        # 截图采集期间也可能弹出模态窗口，避免在线程结束后创建一个被锁死的界面。
        if self._activate_blocking_modal():
            return
        
        if self.screenshot_window is not None:
            # 复用已有窗口（节省 ~250ms 的 UI 壳创建时间）
            log_debug(T("复用已有截图窗口"), "MainApp")
            if sensitive:
                self.screenshot_window.prepare_new_session(image, rect, sensitive=True)
            else:
                self.screenshot_window.prepare_new_session(image, rect)
        else:
            # 首次创建
            log_debug(T("首次创建截图窗口"), "MainApp")
            # 延迟到真正需要时才导入：这条 import 链拖着 canvas/toolbar/tools 一整套
            # 模块，放在文件顶部会在 QApplication 建立之前、启动阶段就被迫付掉这笔
            # 开销。后台预加载线程（bootstrap.py _preload_screenshot_modules）会尽
            # 量抢先把它导入好，这里通常只是从 sys.modules 里取一下。
            from ui.screenshot_window import ScreenshotWindow
            self.screenshot_window = ScreenshotWindow(
                self.config_manager,
                prefetched_image=image,
                prefetched_rect=rect,
                **({"sensitive": True} if sensitive else {}),
            )
            self.screenshot_window.collection_continue_requested.connect(self._continue_collection_capture)
            self.screenshot_window.session_ended.connect(self._restore_image_collection)
        return self.screenshot_window
    
    def open_settings(self):
        """打开设置窗口"""
        if not self.settings_window:
            # Fallback: 如果还没预加载，立即创建
            self._preloader.preload_settings()
        
        # 确保窗口在可见屏幕内
        self._ensure_window_on_screen(self.settings_window)
        
        self.settings_window.setWindowState(self.settings_window.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _ensure_window_on_screen(self, win):
        """检查窗口位置，若在所有屏幕外则居中显示"""
        from PySide6.QtWidgets import QApplication
        pos = win.pos()
        for screen in QApplication.screens():
            if screen.availableGeometry().contains(pos):
                return
        # 窗口不在任何屏幕内，重置到主屏幕中央
        screen = QApplication.primaryScreen()
        if screen:
            screen_rect = screen.availableGeometry()
            x = screen_rect.x() + (screen_rect.width() - win.width()) // 2
            y = screen_rect.y() + (screen_rect.height() - win.height()) // 2
            win.move(x, y)

    def on_settings_accepted(self):
        """设置保存后更新热键和剪贴板设置"""
        accepted_window = self.sender()
        dialog_scale_changed = bool(getattr(
            accepted_window, "_dialog_scale_changed_on_accept", False
        ))

        self.set_clipboard_monitoring_enabled(
            self.config_manager.get_clipboard_enabled()
        )
        self.update_hotkey(show_error=True)
        
        # 通知剪贴板窗口重新加载设置
        if hasattr(self, 'clipboard_window') and self.clipboard_window:
            self.clipboard_window._load_settings()
            self.clipboard_window.controller._load_settings()
            # 同时更新历史限制
            if hasattr(self, 'clipboard_manager') and self.clipboard_manager:
                self.clipboard_manager._apply_history_limit()

        if dialog_scale_changed:
            self._recreate_clipboard_manage_dialog()
            # accepted 信号发出时旧窗口已经隐藏，所以这里明确要求把按新比例
            # 构造的窗口重新打开，而不是依据旧窗口当前的可见状态。
            self._recreate_settings_window(reopen=True)

    def _recreate_clipboard_manage_dialog(self):
        """Discard the cached clipboard manager UI after window-scale changes."""
        from clipboard import (
            destroy_manage_dialog,
            get_existing_manage_dialog,
            get_manage_dialog,
        )

        old_dialog = get_existing_manage_dialog()
        if old_dialog is None:
            return

        manager = old_dialog.manager
        was_visible = destroy_manage_dialog()
        if not was_visible:
            return

        dialog = get_manage_dialog(manager)
        if self.clipboard_window:
            self.clipboard_window._connect_manage_dialog(dialog)
        dialog.show_and_activate()

    def _recreate_settings_window(self, reopen=None):
        """Rebuild the cached settings UI after a process-wide UI setting changes.

        ``reopen=None`` preserves whether the old window was visible.  Callers
        running from QDialog.accepted can pass ``True`` because Qt has already
        hidden the accepted dialog before emitting that signal.
        """
        window = self.settings_window
        if window is None:
            return

        if reopen is None:
            reopen = window.isVisible()

        window.hide()
        window.deleteLater()
        self.settings_window = None

        self._preloader.preload_settings()
        if reopen:
            self.open_settings()
    
    def open_translator(self):
        """打开翻译窗口"""
        from translation import TranslationManager
        
        params = self.config_manager.get_translation_request_params()
        
        manager = TranslationManager.instance()
        manager.translate(
            text="",
            **params
        )

    @Slot(object)
    def _on_clipboard_item_received(self, item):
        """Refresh clipboard UI on the GUI thread without owning probe logic."""
        if getattr(item, "content_type", None) == "image" and self.clipboard_manager:
            self.clipboard_manager.start_image_indexing()
        if self.clipboard_window:
            self.clipboard_window.notify_new_content(item)

    def set_clipboard_monitoring_enabled(self, enabled: bool) -> bool:
        """Synchronize the Rust clipboard watcher with the saved setting.

        The manager stays allocated while disabled so a later enable only needs
        to start its watcher thread.  ``stop_monitoring`` joins that thread,
        making this method safe to call again immediately after disabling it.
        """
        manager = self.clipboard_manager

        if not enabled:
            if not manager:
                log_debug(T("剪贴板监听已禁用，未创建管理器"), "Clipboard")
                return True
            if not manager.is_available:
                log_warning(T("剪贴板管理器不可用，无法停止监听"), "Clipboard")
                return False
            if not manager.is_monitoring():
                return True

            try:
                manager.stop_monitoring()
            except Exception as e:
                log_exception(e, T("停止剪贴板监听"))
                return False

            stopped = not manager.is_monitoring()
            if stopped:
                log_info(T("剪贴板监听已按设置关闭"), "Clipboard")
            return stopped

        try:
            if manager is None:
                from clipboard import ClipboardManager
                manager = ClipboardManager()
                self.clipboard_manager = manager

            if not manager.is_available:
                log_warning(T("剪贴板管理器不可用（pyclipboard 未安装）"), "Clipboard")
                return False
            if manager.is_monitoring():
                return True

            manager.start_monitoring(callback=self.clipboard_item_received.emit)
            started = manager.is_monitoring()
            if started:
                log_info(T("剪贴板监听已按设置启动"), "Clipboard")
            else:
                log_warning(T("剪贴板监听启动失败"), "Clipboard")
            return started
        except ImportError:
            log_debug(T("clipboard 模块不存在"), "Clipboard")
        except Exception as e:
            log_exception(e, T("启动剪贴板监听"))
        return False
    
    def open_clipboard_window(self):
        """打开剪切板历史窗口"""
        
        try:
            from clipboard import ClipboardWindow
            
            # 如果窗口已存在且可见，则关闭
            if self.clipboard_window and self.clipboard_window.isVisible():
                self.clipboard_window.close()
                return
            
            # 如果窗口不存在，创建新窗口
            if not self.clipboard_window:
                self.clipboard_window = ClipboardWindow()
            
            # 不能带 WindowActive：它会在 show 之前激活窗口，showEvent 里就采不到原来的前台窗口（粘贴目标）
            self.clipboard_window.setWindowState(self.clipboard_window.windowState() & ~Qt.WindowState.WindowMinimized)
            self.clipboard_window.show()
            self.clipboard_window.raise_()
            self.clipboard_window.activateWindow()
            log_debug(T("剪切板窗口已打开"), "Clipboard")

        except Exception as e:
            log_exception(e, T("打开剪切板窗口失败"))

    def pin_clipboard_image(self):
        """把剪贴板里的图片钉到鼠标位置。"""
        from PySide6.QtGui import QCursor
        from clipboard.ui.windows.pin_window import pin_latest_clipboard_image

        try:
            pin_latest_clipboard_image(QCursor.pos())
        except Exception as e:
            log_exception(e, T("钉住剪贴板图片失败"))
        
    def quit_app(self):
        self._cancel_pending_capture()
        # 完全销毁缓存的截图窗口
        if self.screenshot_window:
            try:
                self.screenshot_window.full_destroy()
            except Exception as e:
                log_exception(e, T("销毁截图窗口"))
            self.screenshot_window = None

        # 关闭剪贴板窗口
        if self.clipboard_window:
            try:
                self.clipboard_window.close()
            except Exception as e:
                log_exception(e, T("关闭剪贴板窗口"))
            self.clipboard_window = None

        # 停止剪贴板监听
        if self.clipboard_manager and self.clipboard_manager.is_available:
            try:
                self.clipboard_manager.stop_monitoring()
            except Exception as e:
                log_exception(e, T("停止剪贴板监听"))

        # 关闭设置窗口
        if self.settings_window:
            try:
                self.settings_window.close()
            except Exception as e:
                log_exception(e, T("关闭设置窗口"))
            self.settings_window = None

        # 等待预加载线程结束（最多 2 秒，避免卡退出）
        for attr in ('_screenshot_preload_thread', '_ocr_preload_thread', '_capture_thread'):
            thread = getattr(self, attr, None)
            if thread and thread.isRunning():
                thread.wait(2000)

        self.hotkey_system.unregister_all()
        self.app.quit()
        
    def run(self):
        sys.exit(self.app.exec())

if __name__ == "__main__":
    from core.bootstrap import run
    run()
