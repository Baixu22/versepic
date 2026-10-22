# -*- coding: utf-8 -*-
r"""单实例守卫 —— 用原子互斥体把"同一时刻只允许一个实例"变成内核保证。

背景
----
旧实现在 `bootstrap.ensure_single_instance()` 里用 PID 文件做"检查再写入"：

    读 PID 文件 -> 校验是旧实例 -> 终止旧实例 -> 写入自己的 PID

这是典型的 check-then-act 竞态：两次启动若落在同一个时间窗里，两边会读到
同一份（可能还不存在的）记录，两边都判定"没有别人在跑"，于是两个实例都
继续启动。实测证据：%LOCALAPPDATA%\Jietuba\Logs\runtime_20261022.log
里在 14:59:01 / 14:59:05 / 14:59:05 / 14:59:13 / 14:59:13 出现了 5 个
Logger 启动头，随后的"截图热键注册失败: ctrl+1"说明多个实例真的同时活着，
在抢同一个全局热键。

新实现
------
改用 Win32 命名互斥体（CreateMutexW）。互斥体的所有权由内核原子地授予
且只授予一个进程，不存在"两边同时认为自己赢了"的窗口——竞态从根上消失。
句柄随进程退出自动释放，崩溃、强杀、断电都不会留下"僵尸锁"。

命名规则
--------
* 打包后：按可执行文件绝对路径取哈希，命名空间 Local\。
  用绝对路径而不是文件名，是为了区分"装在 Program Files 的 versepic.exe"
  和"某个临时目录里的同名 versepic.exe"——它们是两个不同的程序，
  本就该能同时运行。
* 开发态：固定名 jietuba_dev，与任何 python 进程都不冲突。

同时保留 PID 文件，但角色变了：它不再是"锁"，只是给已有实例
（想被唤起时）提供可读的 PID，以及给日志提供线索。
"""

import ctypes
import os
import sys
import tempfile
from ctypes import wintypes

# ── Win32 常量 ──────────────────────────────────────────────
ERROR_ALREADY_EXISTS = 183

# PAINTSTRUCT 必须定义在模块级。
# 它若是函数里的局部类，ctypes 会为每次调用生成一个新的类对象，
# 而 user32.BeginPaint.argtypes 保存的是上一次设置时的类，与本次的 PAINTSTRUCT 不匹配，
# 结果是每次都报 "expected LP_PAINTSTRUCT instance instead of pointer to PAINTSTRUCT"，
# _paint 永远画不了，Windows 就会无限重发 WM_PAINT。
class _PaintStruct(ctypes.Structure):
    """Win32 PAINTSTRUCT（模块级定义，不能放进函数里）。"""

    _fields_ = [
        ("hdc", ctypes.c_void_p),
        ("fErase", ctypes.c_int),
        ("rcPaint", wintypes.RECT),
        ("fRestore", ctypes.c_int),
        ("fIncUpdate", ctypes.c_int),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


# 提示窗口的存活时长（秒）：足够用户看一眼，也不会拖延启动。
_NOTICE_LIFETIME_SECONDS = 3.0

# 提示窗口期间处理消息的上限（保护与保障）。
_MAX_NOTICE_MESSAGES = 200

# 模块级持有互斥体句柄：句柄一旦被 GC 关闭，锁就提前释放了。
# 必须是模块级变量，生命周期覆盖整个进程。
_mutex_handle = None


def _hash_name(text: str) -> str:
    """把任意字符串折成一个稳定的 32 位十六进制串，用于命名互斥体。"""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def instance_lock_name() -> str:
    r"""返回本程序在当前环境下的互斥体名称。

    打包后用"可执行文件绝对路径"作为身份；开发态用固定名。
    两者都放在 Local\ 命名空间，只对当前登录会话可见——
    多用户机器上每个用户各自跑一份互不干扰。
    """
    frozen = getattr(sys, "frozen", False)
    if frozen:
        identity = os.path.abspath(sys.executable).lower()
    else:
        # 开发态：run_dev.py / main_app.py 都归到同一个名字下，
        # 这样"开发版"和"开发版"之间同样互斥，但不会牵连任何 python 进程。
        identity = "jietuba_dev"
    return "Local\\VersePic.SingleInstance.%s" % _hash_name(identity)


def _pid_file_path() -> str:
    """实例记录文件路径（仅供读取已有实例的 PID，不承担互斥职责）。"""
    frozen = getattr(sys, "frozen", False)
    exe_name = os.path.basename(sys.executable if frozen else sys.argv[0])
    # 打包后用 exe 名，开发时固定用 jietuba_app，避免与其他 python 进程冲突
    pid_name = exe_name if frozen else "jietuba_app"
    return os.path.join(tempfile.gettempdir(), "%s.pid" % pid_name)


def _read_recorded_pid(pid_file: str):
    """从实例记录里读出 PID；读不到或格式不认识返回 None。"""
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
        if not lines:
            return None
        return int(lines[0])
    except Exception:
        return None


def _is_process_alive(pid: int) -> bool:
    """进程是否还活着。"""
    if not pid or pid <= 0:
        return False
    try:
        from core.platform_utils import get_process_identity
        return get_process_identity(pid) is not None
    except Exception:
        return False


def acquire() -> bool:
    """尝试成为唯一实例。

    返回 True 表示本进程取得了唯一实例身份，可以继续启动；
    返回 False 表示已经有实例在跑，本进程应当立刻退出。

    同一个进程重复调用是安全的：已持有句柄时直接返回 True。
    """
    global _mutex_handle

    if _mutex_handle is not None:
        return True  # 本进程已经持锁（同一进程内重复调用）

    if os.name != "nt":
        # 非 Windows 平台没有命名互斥体。退回到 PID 文件的尽力而为检查：
        # 不保证原子性，但至少不会在开发机上完全失效。
        return _acquire_without_mutex()

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    name = instance_lock_name()
    # bInitialOwner=True：创建即持有所有权。
    # 关键点：如果对象已存在，CreateMutexW 不会转移所有权——
    # 调用者只是拿到一个句柄，GetLastError() 返回 ERROR_ALREADY_EXISTS。
    # 也就是说"有且只有一个进程能拿到所有权"，这件事由内核保证，不存在竞态。
    handle = kernel32.CreateMutexW(None, True, name)
    if not handle:
        # 创建失败（例如权限问题）——不能因此拒绝启动，退回宽松模式。
        return _acquire_without_mutex()

    # 不能用 ctypes.get_last_error()：它只在系统 DLL 用 use_last_error=True
    # 加载时才会维护线程本地的 Win32 last error，
    # ctypes.windll 默认不保留它，返回的总是 0。
    # 必须直接调 GetLastError()，且紧跟在 CreateMutexW 之后。
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False

    _mutex_handle = handle
    return True


def _acquire_without_mutex() -> bool:
    """没有命名互斥体时的退化路径：读 PID 文件判断。"""
    pid_file = _pid_file_path()
    if not os.path.exists(pid_file):
        return True
    pid = _read_recorded_pid(pid_file)
    if pid is None:
        return True
    if pid == os.getpid():
        return True
    return not _is_process_alive(pid)


def _detect_language() -> str:
    """读取当前界面语言（不需要 QApplication）。

    用 QSettings 直接读取：启动早期还没建 QApplication，
    但用户保存的语言选择已经在注册表里了，直接读即可。
    """
    try:
        from PySide6.QtCore import QSettings

        value = QSettings("Jietuba", "ToolSettings").value("app/language", "")
        if isinstance(value, str) and value in ("zh", "en", "ja", "ko"):
            return value
    except Exception:
        pass
    return "en"


_NOTICES = {
    "zh": ("VersePic 已在运行", "程序已在后台运行。本次启动已取消，请使用系统托盘图标。"),
    "en": ("VersePic is already running", "VersePic is already running in the background. This launch was cancelled; use the system tray icon."),
    "ja": ("VersePic はすでに走っています", "VersePic はバックグラウンドで已に走っています。この起動はキャンセルされました。システムトレイのアイコンをお使いください。"),
    "ko": ("VersePic 이 이우 실행 중입니다", "VersePic 이 백하운헐서 실행 중입니다. 이 실행은 추소되었으며 시스템 트레이 아이콘을 사용하세요."),
}


def _pump_messages(seconds: float) -> None:
    """轮询消息一个有限的时间，让刚创建的窗口有机会绘出来。

    不阻塞（有上限的轮询），不建立消息循环的持有者。
    """
    import time

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        PM_REMOVE = 0x0001
        WM_QUIT = 0x0012
        MSG = wintypes.MSG
        user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND,
                                      wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]

        deadline = time.monotonic() + max(0.0, seconds)
        msg = MSG()
        handled = 0
        while time.monotonic() < deadline:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    return
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
                handled += 1
                # 保护上限：如果出现不断重发的消息（比如永不结束的
                # WM_PAINT），就不能把进程持在 100% CPU 的循环里。
                # 提示窗口只需要画几十次，超过这个数量就足够了。
                if handled > _MAX_NOTICE_MESSAGES:
                    return
            time.sleep(0.01)
    except Exception:
        pass


def notify_already_running() -> None:
    """向用户告知"已在运行"，避免双击后静默无反应。

    必须是**非阻塞**的。之前这里用的是 MessageBoxW，
    它是模态的：会阻塞调用它的线程直到用户点掉弹窗。
    而这里正是"被拒绝启动的进程"，它得强行退出——否则用户在任务
    管理器里看到的就是"两个实例都还在"，正好是要解决的问题。

    改用自己创建的顶层窗口（非模态）来提示：创建后立即返回，
    进程随即退出，窗口由系统在进程退出后自动清理。

    不用 Qt：单实例检查发生在 QApplication 创建之前。
    """
    title, body = _NOTICES.get(_detect_language(), _NOTICES["en"])
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        WS_POPUP = 0x80000000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000
        SW_SHOWNOACTIVATE = 4
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        WM_DESTROY = 0x0002
        WM_PAINT = 0x000F
        COLOR_WINDOW = 5
        DT_WORDBREAK = 0x00000010
        DT_CENTER = 0x00000001
        TRANSPARENT = 1
        DEFAULT_GUI_FONT = 17
        HWND_TOP = -1

        # ctypes.wintypes 里没有 WNDCLASS，自己定义一个。
        # 字段顺序必须与 Win32 的 WNDCLASS 一致。
        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                # 64 位下 HINSTANCE/HICON/HBRUSH 都是指针宽的句柄，
                # wintypes 里的类型是 c_int，赋一个 64 位地址会溢出。
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        # 文字必须在 WM_PAINT 里画：直接对 DC 画一次是不可靠的——
        # 窗口一显示，Windows 就会重新发 WM_PAINT 把那一画抹掉。
        _NOTICE_TEXT = {"title": title, "body": body}

        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.LPVOID,
        ]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]

        # 窗口类名里带一个唯一标识，避免与其他进程碰撞
        class_name = "VersePicAlreadyRunning_%d" % os.getpid()

        def _paint(hwnd):
            """在窗口的客户区里画提示文字。

            必须用 BeginPaint/EndPaint，不能用 GetDC/ReleaseDC：
            GetDC 不会清空更新区，Windows 会不断重发 WM_PAINT，
            最终变成一个 100% CPU 的海护循环，进程永远退不了。
            BeginPaint 会验证更新区，所以 WM_PAINT 只会来一次。

            标题和正文分开画：同一个 rect 里两段文字会上下重叠。
            """
            ps = _PaintStruct()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            try:
                font = gdi32.GetStockObject(DEFAULT_GUI_FONT)
                old_font = gdi32.SelectObject(hdc, font)
                gdi32.SetBkMode(hdc, TRANSPARENT)

                title_rect = wintypes.RECT(16, 14, 444, 40)
                title = _NOTICE_TEXT["title"]
                user32.DrawTextW(
                    hdc, title, len(title), ctypes.byref(title_rect),
                    DT_WORDBREAK | DT_CENTER,
                )

                body_rect = wintypes.RECT(16, 46, 444, 114)
                text = _NOTICE_TEXT["body"]
                user32.DrawTextW(
                    hdc, text, len(text), ctypes.byref(body_rect),
                    DT_WORDBREAK | DT_CENTER,
                )

                gdi32.SelectObject(hdc, old_font)
            finally:
                user32.EndPaint(hwnd, ctypes.byref(ps))

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            if msg == WM_PAINT:
                _paint(hwnd)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )
        wnd_proc = WNDPROC(_wnd_proc)

        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        instance = kernel32.GetModuleHandleW(None)
        wndclass = WNDCLASS()
        wndclass.style = 0
        wndclass.lpfnWndProc = ctypes.cast(wnd_proc, ctypes.c_void_p).value
        wndclass.hInstance = instance
        # COLOR_WINDOW + 1：系统提供的窗口背景色，不需要自己创建 GDI 牛尖笔
        wndclass.hbrBackground = COLOR_WINDOW + 1
        wndclass.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wndclass))

        hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class_name,
            title,
            WS_POPUP,
            240, 180, 480, 150,
            None, None, instance, None,
        )
        if not hwnd:
            return

        # 用系统默认字体（不创建 GDI 资源，也不会泄漏）
        # 这几个 API 都要显式声明参数/返回类型：
        # ctypes 默认按 c_int 处理，在 64 位上会把句柄截断，进而报
        # "int too long to convert" 或越界访问。
        gdi32.GetStockObject.restype = wintypes.HGDIOBJ
        gdi32.GetStockObject.argtypes = [ctypes.c_int]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SetBkMode.restype = ctypes.c_int
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        user32.GetDC.restype = wintypes.HDC
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        # ctypes 的参数类型必须写成 LP_PAINTSTRUCT（指向结构体的指针）。
        # 写成 POINTER(PAINTSTRUCT) 会在调用时报
        # "expected LP_PAINTSTRUCT instance instead of pointer to PAINTSTRUCT"，
        # 而这个异常是在 ctypes 回调里抛出的（不会中断消息循环），
        # 结果就是 _paint 永远画不了，Windows 反复重发 WM_PAINT。
        LP_PAINTSTRUCT = ctypes.POINTER(_PaintStruct)
        user32.BeginPaint.restype = wintypes.HDC
        user32.BeginPaint.argtypes = [wintypes.HWND, LP_PAINTSTRUCT]
        user32.EndPaint.restype = wintypes.BOOL
        user32.EndPaint.argtypes = [wintypes.HWND, LP_PAINTSTRUCT]
        user32.DrawTextW.restype = ctypes.c_int
        user32.DrawTextW.argtypes = [
            wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int,
            ctypes.POINTER(wintypes.RECT), wintypes.UINT,
        ]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.InvalidateRect.restype = wintypes.BOOL
        user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
        user32.UpdateWindow.restype = wintypes.BOOL
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]

        user32.InvalidateRect(hwnd, None, True)
        user32.UpdateWindow(hwnd)
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
        user32.SetWindowPos(
            hwnd, HWND_TOP, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

        # 提示需要一点时间才能被看到：进程一退出，窗口
        # 就消失了。这里轮询一个很短的消息循环（不阻塞、有上限），
        # 让窗口有机会绘出来。
        #
        # 这里不会影响"只能有一个实例"这条承诺：被拒绝的进程从未创建
        # QApplication、从未注册全局热键、从未监听剪贴板，它不是一个应用实例。
        _pump_messages(_NOTICE_LIFETIME_SECONDS)
    except Exception:
        pass


def running_instance_pid():
    """返回当前正在运行的实例 PID；判断不出来时返回 None。

    只在"拿不到互斥体"（即确认已有实例）时才有意义。
    """
    pid_file = _pid_file_path()
    pid = _read_recorded_pid(pid_file)
    if pid and pid != os.getpid() and _is_process_alive(pid):
        return pid
    return None


def write_pid_record() -> None:
    """把当前 PID 写进实例记录文件。

    这个文件不承担互斥职责（互斥体才是），只是让"已有实例"能被定位：
    想唤起已有窗口时需要它的 PID，日志排查时也需要它。
    """
    pid_file = _pid_file_path()
    try:
        from core.platform_utils import get_process_identity

        identity = get_process_identity(os.getpid())
        create_time = identity[0] if identity else None
        with open(pid_file, "w", encoding="utf-8") as f:
            f.write("%d\n" % os.getpid())
            if create_time is not None:
                f.write("%d\n" % create_time)
    except Exception:
        pass


def clear_pid_record() -> None:
    """清除实例记录文件（仅当记录指向自己时才删）。"""
    pid_file = _pid_file_path()
    try:
        if not os.path.exists(pid_file):
            return
        pid = _read_recorded_pid(pid_file)
        if pid is not None and pid != os.getpid():
            return  # 别人写的记录，不动
        os.remove(pid_file)
    except Exception:
        pass


def release() -> None:
    """释放互斥体（正常退出时调用；进程被杀时由内核自动回收）。"""
    global _mutex_handle
    if _mutex_handle is None:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
    except Exception:
        pass
    _mutex_handle = None
