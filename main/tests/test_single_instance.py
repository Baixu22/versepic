# -*- coding: utf-8 -*-
"""单实例守卫的回归测试。

这个守卫保护的是"同一时刻只允许一个实例"这条产品承诺，所以必须测到
**跨进程**这一层：在同一个 pytest 进程里调 acquire() 只能证明同一个
进程重复调用是幂等的，证明不了两个进程之间会互斥。

测试策略：起真实的子进程（python -c），让子进程去抢同一个命名互斥体，
用子进程的退出码汇报"抢到了 / 没抢到"。这正是竞态曾经发生的地方，
因此用**并发**方式跑（同时起多个子进程），复现旧实现会失败的场景。

Windows 之外没有命名互斥体，整个模块退化为 PID 文件的尽力而为检查，
这些用例只在 Windows 上跑。
"""

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from core import platform_utils

pytestmark = pytest.mark.skipif(
    platform_utils.os.name != "nt",
    reason="命名互斥体是 Windows 专有机制",
)

MAIN_DIR = Path(__file__).resolve().parents[1]

# 子进程脚本：抢锁并用退出码汇报结果。
# 0 = 抢到了（成为唯一实例），3 = 没抢到（已有实例）。
_HELPER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {main_dir!r})
    from core import single_instance
    acquired = single_instance.acquire()
    sys.exit(0 if acquired else 3)
    """
)


def _run_helper():
    """跑一个子进程去抢锁，返回它的退出码。"""
    code = _HELPER.format(main_dir=str(MAIN_DIR))
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode


def test_second_process_cannot_acquire_while_first_holds_the_lock():
    """第一个进程持锁时，第二个进程必须拿不到。"""
    from core import single_instance

    assert single_instance.acquire() is True
    # 本进程持锁，子进程必须抢不到
    assert _run_helper() == 3


def test_lock_is_released_when_the_holder_exits():
    """持锁进程退出后，新的进程必须能拿到锁。

    这是"崩溃/强杀之后不需要手工清理"这条承诺的关键：互斥体句柄随进程
    退出自动释放，不会留下需要人工干预的僵尸锁。
    """
    from core import single_instance

    assert single_instance.acquire() is True
    single_instance.release()

    # 释放后子进程应该能抢到
    assert _run_helper() == 0


def test_concurrent_processes_produce_exactly_one_winner(tmp_path):
    """并发启动多个进程，只能有一个抢到锁。

    这正是旧实现（PID 文件 check-then-act）会失败的场景：
    多个进程同时启动时，它们会读到同一份记录、得出相同结论，
    最终全部运行起来。

    协调方式：抢到锁的子进程保持锁到父进程放行为止，
    其余子进程必然抢不到。如果让抢到的子进程抢到就退出，
    锁会随之释放，下一个启动慢的子进程就能再抢到——
    那就不是并发测试，而是测了启动顺序。
    """
    from core import single_instance

    assert single_instance.acquire() is True
    single_instance.release()

    work = tmp_path
    release_flag = work / "release"

    # 子进程：抢锁 -> 写结果 -> 抢到的等待释放信号 -> 退出
    code = textwrap.dedent(
        """
        import os, sys, time
        sys.path.insert(0, {main_dir!r})
        from core import single_instance
        work, name = sys.argv[1], sys.argv[2]
        acquired = single_instance.acquire()
        with open(os.path.join(work, name), "w") as f:
            f.write("1" if acquired else "0")
        if acquired:
            release = os.path.join(work, "release")
            deadline = time.time() + 60
            while not os.path.exists(release) and time.time() < deadline:
                time.sleep(0.01)
        sys.exit(0 if acquired else 3)
        """
    ).format(main_dir=str(MAIN_DIR))

    names = ["r%d" % i for i in range(6)]
    procs = []
    for name in names:
        procs.append(
            subprocess.Popen(
                [sys.executable, "-c", code, str(work), name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        )

    # 等所有子进程都已经尝试抢锁，才允许赢家释放锁
    deadline = time.time() + 60
    while time.time() < deadline:
        if all((work / name).exists() for name in names):
            break
        time.sleep(0.01)
    else:
        for proc in procs:
            proc.kill()
        pytest.fail("子进程未在限定时间内完成抢锁尝试")

    acquired_flags = [(work / name).read_text() for name in names]
    release_flag.write_text("go")

    codes = []
    for proc in procs:
        proc.communicate(timeout=60)
        codes.append(proc.returncode)

    winners = acquired_flags.count("1")
    assert winners == 1, (
        "并发启动时应该只有一个进程抢到锁，"
        "实际结果：%s" % acquired_flags
    )
    assert codes.count(3) == len(codes) - 1, (
        "除了赢家之外的子进程都应该被拒绝，退出码：%s" % codes
    )


def test_ensure_single_instance_returns_false_when_lock_is_taken(monkeypatch):
    """bootstrap.ensure_single_instance() 必须把"抢不到"传出来。

    旧实现的 ensure_single_instance() 没有返回值，调用方无法区分
    "已经成为唯一实例"和"已经有实例，应当退出"。
    """
    from core import bootstrap

    monkeypatch.setattr("core.single_instance.acquire", lambda: False)
    monkeypatch.setattr("core.single_instance.running_instance_pid", lambda: None)
    monkeypatch.setattr("core.single_instance.notify_already_running", lambda: None)

    assert bootstrap.ensure_single_instance() is False


def test_ensure_single_instance_returns_true_when_lock_is_free(monkeypatch):
    """抢到锁时应该继续启动。"""
    from core import bootstrap

    monkeypatch.setattr("core.single_instance.acquire", lambda: True)
    monkeypatch.setattr("core.single_instance.write_pid_record", lambda: None)
    monkeypatch.setattr("core.single_instance.notify_already_running", lambda: None)

    assert bootstrap.ensure_single_instance() is True


def test_startup_path_exits_when_an_instance_already_runs(monkeypatch):
    """run() 在抢不到锁时必须退出，不能创建 QApplication。

    多个实例同时存活会导致它们抢同一个全局热键
    （表现为"截图热键注册失败"），并同时写同一个剪贴板库。
    """
    import core.bootstrap as bootstrap_module

    started = []
    monkeypatch.setattr(bootstrap_module, "setup_environment", lambda: None)
    monkeypatch.setattr(bootstrap_module, "ensure_module_path", lambda: None)
    monkeypatch.setattr(bootstrap_module, "pin_bundled_resources", lambda: None)
    monkeypatch.setattr("core.platform_utils.set_app_user_model_id", lambda *a, **k: None)
    monkeypatch.setattr(bootstrap_module, "ensure_single_instance", lambda: False)

    class _FakeMainApp:
        def __init__(self):
            started.append("constructed")

        def run(self):
            started.append("run")

    import main_app
    monkeypatch.setattr(main_app, "MainApp", _FakeMainApp)

    with pytest.raises(SystemExit) as excinfo:
        bootstrap_module.run()

    assert excinfo.value.code == 0
    assert started == [], "抢不到单实例权限时不应进入 MainApp"


def test_refused_launch_tells_the_user(monkeypatch):
    """被拒绝的启动要通知用户，否则双击图标后静默无反应。

    用户会认为程序卡死了。
    """
    from core import bootstrap

    notified = []
    monkeypatch.setattr("core.single_instance.acquire", lambda: False)
    monkeypatch.setattr("core.single_instance.running_instance_pid", lambda: 4321)
    monkeypatch.setattr(
        "core.single_instance.notify_already_running", lambda: notified.append(True)
    )

    assert bootstrap.ensure_single_instance() is False
    assert notified == [True], "应当告知用户已有实例在运行"


def test_refused_launch_survives_a_failing_notice(monkeypatch):
    """提示本身失败不得影响退出逻辑。"""
    from core import bootstrap

    def _boom():
        raise RuntimeError("no desktop session")

    monkeypatch.setattr("core.single_instance.acquire", lambda: False)
    monkeypatch.setattr("core.single_instance.running_instance_pid", lambda: None)
    monkeypatch.setattr("core.single_instance.notify_already_running", _boom)

    assert bootstrap.ensure_single_instance() is False


def test_notice_covers_every_supported_language():
    """提示文案要覆盖所有支持的界面语言。"""
    from core import single_instance

    for language in ("zh", "en", "ja", "ko"):
        title, body = single_instance._NOTICES[language]
        assert title and body


def test_notice_does_not_block_the_refused_process(monkeypatch):
    """提示不得阻塞被拒绝的进程。

    MessageBoxW 是模态的：会阻塞调用它的线程直到用户点掉弹窗。
    而这里正是"被拒绝启动的进程"，它得强行退出——否则用户在任务
    管理器里看到的就是"两个实例都还在"，正好是要解决的问题。
    """
    import inspect

    from core import single_instance

    source = inspect.getsource(single_instance.notify_already_running)
    # 只看实际调用，不看文档里的提及（文档强调过 MessageBoxW 的问题）
    assert "user32.MessageBoxW" not in source, (
        "提示不能用模态的 MessageBox：会把被拒绝的进程卡住不退出"
    )
    assert "CreateWindowExW" in source, "提示应该用自己创建的非模态窗口"


def test_notice_creates_a_non_modal_window_and_returns(monkeypatch):
    """提示用自己创建的非模态窗口，创建后立即返回。"""
    from core import single_instance

    calls = []

    class _FakeUser32:
        def __init__(self):
            def _create_window_ex(*args):
                calls.append(("create_window", args))
                return 12345

            def _show_window(hwnd, cmd):
                calls.append(("show_window", hwnd, cmd))

            def _set_window_pos(*args):
                calls.append(("set_window_pos",))

            def _register_class(*args):
                calls.append(("register_class",))
                return 1

            def _invalidate_rect(*args):
                calls.append(("invalidate_rect",))

            def _update_window(hwnd):
                calls.append(("update_window",))

            def _get_dc(hwnd):
                calls.append(("get_dc",))
                return 999

            def _release_dc(hwnd, hdc):
                pass

            def _draw_text(*args):
                calls.append(("draw_text",))

            def _set_bk_mode(hdc, mode):
                pass

            def _def_window_proc(*args):
                return 0

            def _post_quit_message(code):
                pass

            def _begin_paint(hwnd, ps):
                calls.append(("begin_paint",))
                return 999

            def _end_paint(hwnd, ps):
                calls.append(("end_paint",))

            self.BeginPaint = _begin_paint
            self.EndPaint = _end_paint
            self.CreateWindowExW = _create_window_ex
            self.ShowWindow = _show_window
            self.SetWindowPos = _set_window_pos
            self.RegisterClassW = _register_class
            self.InvalidateRect = _invalidate_rect
            self.UpdateWindow = _update_window
            self.GetDC = _get_dc
            self.ReleaseDC = _release_dc
            self.DrawTextW = _draw_text
            self.SetBkMode = _set_bk_mode
            self.DefWindowProcW = _def_window_proc
            self.PostQuitMessage = _post_quit_message

    class _FakeGdi32:
        def __init__(self):
            def _get_stock_object(index):
                return 1

            def _select_object(hdc, obj):
                return 2

            def _set_bk_mode(hdc, mode):
                pass

            self.GetStockObject = _get_stock_object
            self.SelectObject = _select_object
            self.SetBkMode = _set_bk_mode

    class _FakeKernel32:
        def __init__(self):
            def _get_module_handle(name):
                return 5

            self.GetModuleHandleW = _get_module_handle

    import ctypes
    fake_windll = type("W", (), {
        "user32": _FakeUser32(),
        "gdi32": _FakeGdi32(),
        "kernel32": _FakeKernel32(),
    })()
    monkeypatch.setattr(ctypes, "windll", fake_windll)
    monkeypatch.setattr(single_instance, "_detect_language", lambda: "en")
    # 提示只存在 3 秒，测试不应该真等那么久
    monkeypatch.setattr(single_instance, "_NOTICE_LIFETIME_SECONDS", 0.0)

    # 这一行不应阻塞：没有循环，也没有 MessageBox
    single_instance.notify_already_running()

    names = [c[0] for c in calls]
    assert "create_window" in names
    assert "show_window" in names
    assert "invalidate_rect" in names
    assert "update_window" in names


def test_notice_paints_its_text_in_a_separate_band(monkeypatch):
    """标题和正文必须分开画，同一个 rect 里会上下重叠。"""
    import inspect

    from core import single_instance

    source = inspect.getsource(single_instance.notify_already_running)
    assert source.count("DrawTextW") >= 2, "标题和正文应该分开调用 DrawTextW"


def test_notice_paints_exactly_once_per_paint_message(monkeypatch):
    """提示窗口不得把进程持在 100% CPU 的循环里。

    真实发生过：提示刚创建时用的是 GetDC/ReleaseDC，而不是
    BeginPaint/EndPaint。GetDC 不会验证更新区，Windows 就不断重发 WM_PAINT，
    最终是一个海护循环：被拒绝启动的进程永远不退出，
    用户在任务管理器里仍然看得到"两个实例都还在"。

    测量方式：用真实的 Win32 API，只把 BeginPaint / DrawTextW 换成计数器。
    正常情况下一次窗口绘制只会触发一次 BeginPaint（它会验证更新区），
    标题和正文各绘制一次。循环时这两个计数会无限增长。

    不用 CPU 时间做判定：它是进程全局的，完整测试套并发跑时
    其他测试留下的后台线程会把它形成噪声（实测确有过因此误报）。
    """
    import ctypes

    from core import single_instance

    real_user32 = ctypes.windll.user32
    counts = {"begin_paint": 0, "draws": 0}

    class _CountingUser32:
        """代理真实的 user32，只统计 BeginPaint 和 DrawTextW 的调用次数。"""

        def __getattr__(self, name):
            real = getattr(real_user32, name)

            if name == "BeginPaint":
                def wrapper(*args):
                    counts["begin_paint"] += 1
                    return real(*args)

                return wrapper

            if name == "DrawTextW":
                def wrapper(*args):
                    counts["draws"] += 1
                    return real(*args)

                return wrapper

            return real

    monkeypatch.setattr(ctypes, "windll", type("W", (), {
        "user32": _CountingUser32(),
        "gdi32": ctypes.windll.gdi32,
        "kernel32": ctypes.windll.kernel32,
    })())

    monkeypatch.setattr(single_instance, "_detect_language", lambda: "en")
    monkeypatch.setattr(single_instance, "_NOTICE_LIFETIME_SECONDS", 0.3)

    single_instance.notify_already_running()

    assert counts["begin_paint"] == 1, (
        "一次窗口绘制只应触发一次 BeginPaint，实测 %d 次"
        "\u8bf4明 WM_PAINT 在被无限重发" % counts["begin_paint"]
    )
    assert counts["draws"] == 2, (
        "标题和正文各绘制一次，应该共 2 次 DrawTextW，实测 %d 次"
        % counts["draws"]
    )
