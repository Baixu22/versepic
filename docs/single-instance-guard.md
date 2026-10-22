# 单实例限制 — 发布说明

日期：2026-10-22
范围：发布到本机 `C:\Users\27933\AppData\Local\Programs\VersePic`

## 问题

用户报告：启动不会限制实例数量，可能启动两个实例。

现场证据：

- `%LOCALAPPDATA%\Jietuba\Logs\runtime_20261022.log` 里在 14:59:01 / 14:59:05 /
  14:59:05 / 14:59:13 / 14:59:13 出现了 **5 个 Logger 启动头**，
  说明那 90 秒里实际启动了 5 次。
- 随后的 `截图热键注册失败: ctrl+1` 证明多个实例同时活着，
  在抢同一个全局热键。

## 根因

旧实现（`bootstrap.ensure_single_instance()`）用 PID 文件做“检查再写入”：

```
读 PID 文件 -> 校验是旧实例 -> 终止旧实例 -> 写入自己的 PID
```

这是典型的 check-then-act 竞态。两次启动落在同一个时间窗里时，
两边会读到同一份（甚至不存在的）记录，两边都判定“没有别人在跑”，
于是两个实例都继续启动。

实测复现（A 已在运行，B/C 几乎同时启动）：

```
OLD IMPL (PID file, check-then-act): exit codes (A,B,C) = [0, 0, 0]  -> 0 of 3 refused, 3 became live instances
OLD IMPL RESULT: RACE - 3 instances coexisted
```

## 改法

新增 `main/core/single_instance.py`，用 **Win32 命名互斥体（`CreateMutexW`）** 承担互斥。

互斥体的所有权由内核原子地授予且只授予一个进程，
不存在“两边同时认为自己赢了”的窗口——竞态从根上消失。
句柄随进程退出自动释放，崩溃、强杀、断电都不会留下需要手工清理的“僋兵锁”。

语义上的两个关键变更：

1. **不再终止旧实例，而是拒绝本次启动。**
   用户要的是“限制实例数量”，不是“用新实例顶掉旧实例”。
   杀掉旧实例会连带丢掉它的剪贴板监听状态、钉图窗口和未保存的编辑内容。

2. **被拒绝的进程必须真正退出。**
   被拒绝的进程从不创建 QApplication、从不注册全局热键、从不监听剪贴板，
   所以它不是一个应用实例。

## 用户可见反馈

双击图标后静默无反应会让人认为“程序卡死了”，
所以被拒绝时会弹一个短暂的提示窗口（顶层、不夺焦点、自动关闭），
文案跟随界面语言（zh / en / ja / ko）。

提示窗口必须是**非阻塞**的。这里有两个真实陷阱，都已经修复并加上回归测试：

- **MessageBoxW 是模态的**：会阻塞被拒绝的进程直到用户点掉弹窗，
  用户在任务管理器里看到的就是“两个实例都还在”——正好是要解决的问题。
- **GetDC/ReleaseDC 会造成 100% CPU 循环**：GetDC 不会验证更新区，Windows 就不断重发 WM_PAINT。
  必须用 BeginPaint/EndPaint。实测异常进程耗时 45s CPU / 3s wall，修复后为 0.00s CPU / 3.0s wall。

## 验证

### 自动化回归（`main/tests/test_single_instance.py`，13 个用例）

- 跨进程互斥：第一个进程持锁时，第二个进程抢不到
- 锁会随进程退出释放（崩溃/强杀后无需手工清理）
- **并发启动多个进程，只有一个抢到锁**
- `ensure_single_instance()` 能区分“抢到”与“抢不到”
- `run()` 抢不到时退出，不创建 MainApp
- 被拒绝时告知用户；提示本身失败不影响退出逻辑
- 提示**不阻塞**被拒绝的进程
- 提示**不赪 CPU**：用真实 Win32 API 计数，一次窗口绘制必须恰好触发
  1 次 `BeginPaint`（2 次 `DrawTextW`：标题+正文）。循环时这两个计数会无限增长。
- 提示窗口的标题与正文分开绘制

### 实机验收（已安装的 2.1.3 构建）

```
T1: 启动第一个实例        -> 2 个进程（bootloader + 应用）
T2: 同时启动 5 个额外实例  -> 全部被拒绝，总数仍为 2
```

存活实例状态：CPU 增量近乎 0s；
`Screenshot hotkey registered: ctrl+1` / `Clipboard hotkey registered: ctrl+2`（无失败）；
`Clipboard monitoring started per settings`。

### 回归

- 全量测试：**3503 passed, 2 skipped**, 0 failed
- `ruff check main`：全部通过

## 已发布

- 标签：`v2.1.3`（指向 `a87f3d1`）
- Release：https://github.com/Baixu22/versepic/releases/tag/v2.1.3
- 仓库已改为 **public**；应用内的更新查询已能无账号读取公开的 Releases API（已实测返回 `v2.1.3`）。
- 产物：`VersePic-2.1.3-windows-x64.zip`（98 MB）+ `.zip.sha256`；
  已用未登录的下载验证过，字节数与 sha256 均与本地一致。
- 本地安装：`C:\Users\27933\AppData\Local\Programs\VersePic\versepic.exe`（与发布包内的 exe 哈希一致），
  旧版备份在 `backups/2.1.2-before-2.1.3/`。

## 需要知道的其他变化

- **EXE 体积从 45 MB 增到 75 MB**。这不是本次改动带来的，
  而是提交 `331e80d`（MP4 导出支持）把 `av` 加进了 hiddenimports，
  带来了 FFmpeg 编码器（avcodec-62 / avformat-62 / x264 等，共 30 个条目）。
  安装的 2.1.2 构建早于该提交，所以没有这些。
- **删除了 `platform_utils.terminate_process_by_pid()`**：旧的单实例逻辑是唯一使用者，
  新实现不再终止旧实例，该函数随之变为死代码（含其 `PROCESS_TERMINATE` /
  `TerminateProcess` 声明）。
- **`SettingsDialog.resizeEvent` 的崩溃与本次改动无关**。
  已用“完全回退到 HEAD 版本重建”的方式复完：
  回退构建在 18:04:28 出现完全相同的异常，
  残留在 `ui/settings_ui/dialog.py:1110` 的 `super().resizeEvent(e)`（`qframelesswindow` 父类访问不存在的 `titleBar`）。
  这是仓库里本来就有的问题，**本次未修复**，也不在本次范围内。

## 附带发现：开机自启注册表项

安装期间发现 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 的 `Jietuba`
值指向了开发版启动器（`venv312\Scripts\python.exe main\main_app.py`），
而不是已安装的 `versepic.exe`。

这个值是什么时候被写入的**无法确定**：

- 安装流程没有触碰这个注册表项；
- 已验证**测试套不会改写它**（完整套跑前后对比：`CHANGED BY TESTS: False`）；
- 代码里写注册表的只有 `ui/welcome/page6_finish.py::_set_autostart()`，
  它写的是**当前运行的可执行文件**（打包后是 `versepic.exe`，
  开发模式是 `python.exe main_app.py`）——所以只有在**开发版**下打开设置并保存
  开机自启时才会写入开发路径。

已恢复为已安装的 exe，并实测确认它启动后能被单实例守卫正常拒绝：

```
[18:55:23] [INFO] [SingleInstance] Another instance is already running (PID 17236), this launch was cancelled
```

## 未验证的部分

- 提示窗口的**视觉样式**（字体、背景色、圆角）是用户默认系统样式，
  没有做设计精修。若需要统一视觉，应改为调用已运行实例的 UI 来显示提示。
- **多用户机器**的行为未实机验证（互斥体用 `Local\` 命名空间，
  各登录会话互不干扰，预期正确，但未在另一个会话上实测）。
