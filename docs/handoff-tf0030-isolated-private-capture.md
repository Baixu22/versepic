# HANDOFF：TF-0030 单次敏感截图 —— 真实监听零留存验收

> 接收方：拥有更高权限 / 隔离环境的 agent 或工程师
> 发起方：jietuba 仓库本轮开发 agent（当前被本机权限挡住）
> 生成时间：2026-10-10
> 目标：跑通 TF-0030 最后一条验收——**真实系统剪贴板监听下零留存**，并把证据带回
> 状态：用户已指示本机解决不了就跳过（节点现为 deprecated）。本文件是「以后谁有权限谁来做」的执行说明；
> 跑通后请把证据带回，节点可重新打开并转为 review_needed / done。

---

## 0. 一句话

代码已经写完（会话策略 + Rust 入库前拦截 + 明确复制才写剪贴板），只剩「真实监听零留存」无法在本机验证：
本机进程**创建独立 window station 被拒绝（WinError 5）**。请在有权限的 Windows 上跑下面两个原生驱动，
**不要改动工作区、不要应用任务提案**。

---

## 1. 这个节点要满足什么（TF-0030 原文验收条件）

- 单次模式结束后恢复正常行为，不永久关闭监听或保存设置。
- 用**隔离数据库和输出目录**验证不存在原始图、缩略图、索引或敏感日志残留。
- 仅用户明确复制才写入系统剪贴板；明确不承诺删除其他软件已读取的内容。
- 不做：系统级隐私擦除、阻止第三方剪贴板工具的保证。

## 2. 现在到哪一步了

**已实现并已有证据（不需要重做）**

- 单次敏感模式入口与会话策略：敏感状态随截图 → 钉图 → 脱敏窗口传递，会话结束复位；不修改持久设置。
- 入库前拦截：Rust 侧在读取监听负载前检查标记，命中则不读负载、不落文件/缩略图/数据库、不回调 Python。
- 显式敏感复制：同一 `OpenClipboard` 事务内先写标记再写像素，失败不降级为普通复制。
  - 自定义格式：`VersePic.PrivateCapture.v1`
  - 标准标记：`ExcludeClipboardContentFromMonitorProcessing`、`CanIncludeInClipboardHistory = 0`
  - 原生能力握手：`pyclipboard.PRIVATE_CAPTURE_PROTOCOL == 1`（无协议即拒绝敏感复制）
- 已有 60 项 Python 回归 + 原生 UI 流程（复制/采集用替身），但 `result.json` 里明确写着
  `real_clipboard_exclusion_verified: false` —— **替身证据不能当真实监听验收**。

**未完成（本次要做的）**

- 在真实系统剪贴板通知下，用隔离 DB/目录/日志验证：私密内容不产生原图、缩略图、原始格式、数据库行、
  OCR 索引或含敏感内容的日志；模式结束后普通复制恢复。

## 3. 为什么本机跑不了（已复核两次）

- `CreateWindowStationW` 用 4 种访问掩码（`0xF037F` / `0` / `0x10000000` / `0x2`）全部返回 **WinError 5（拒绝访问）**；
  最新一次复核用 2 种掩码，均为 `error=5`。
- 当前账户无 `SeTcbPrivilege`、非提升会话、无 Windows Sandbox。
- 脚本在创建独立 window station 时就退出，**尚未触碰任何剪贴板内容**。

**需要的条件（任选其一即可）**

| 方案 | 说明 | 风险 |
| --- | --- | --- |
| A. 允许创建独立 window station/desktop 的 Windows 会话 | 最贴近脚本设计 | 无 |
| B. 隔离 VM / Windows Sandbox（推荐） | 全新系统，剪贴板天然隔离 | 无（推荐） |
| C. 用户明确授权的真实剪贴板快照→私密复制→恢复 | 会短暂改动系统剪贴板 | 需用户书面同意，必须先快照并在结束时恢复 |

## 4. 环境准备

- Windows 10/11 x64，PowerShell。
- 仓库目录（**必须原样使用，不要新建分支/不要 reset/clean/stash**）：
  `C:\Users\27933\Desktop\versepixpin\jietuba`
  当前分支 `master2`，工作区有大量未提交改动，这是交接状态。
- Python 环境：`venv312\Scripts\python.exe`（Python 3.12.13、PySide6 6.11.0、pywin32 311、mss 10.1、pytest 9.1.1）。
- 先确认工作树没被动过：`git status --porcelain`（应仍是一大批 `M` / `??`）。

**预检（先跑这个，权限不够就立刻停）**

```powershell
& 'venv312\Scripts\python.exe' -c "import ctypes, ctypes.wintypes as w; u=ctypes.WinDLL('user32', use_last_error=True); u.CreateWindowStationW.restype=w.HANDLE; h=u.CreateWindowStationW('VersePicPreflight', 0, 0x37F, None); print('handle=', bool(h), 'err=', ctypes.get_last_error()); u.CloseWindowStation(h) if h else None"
```

- 输出 `handle= True err= 0` → 具备方案 A，可以继续。
- 输出 `handle= False err= 5` → 权限仍不足，请改用 VM/沙箱（方案 B）或申请授权（方案 C），**不要退回真实交互剪贴板**。

## 5. 要跑的两个驱动

输出目录都必须是**新建且为空**（脚本会拒绝非空目录）。

### 5.1 真实 private clipboard 驱动（核心）

```powershell
& 'venv312\Scripts\python.exe' 'main/tests/native_private_clipboard.py' --run --output 'D:\evidence\private-clipboard-20261010'
```

它会：

1. 先创建并校验独立、非交互 window station + desktop（确认不是 `WinSta0`）；
2. 把配置指到 `<output>\settings.ini`、DB 指到 `<output>\history.db`、日志指到 `<output>\logs`（**不碰真实配置**）；
3. 做私有图片复制 + 真实监听，断言**不产生**：数据库行、原始格式残留、缩略图、图片文件、Python 回调；
4. 校验标准排除标记存在（含 `CanIncludeInClipboardHistory` 为 0）；
5. 用 80 次私密/普通快速交替检查不残留敏感文本（DB / 格式 / 图片 / 回调）；
6. 校验注册表摘要不变、之后普通复制仍正常入库；
7. 把结果写到 `<output>\result.json` 并以退出码表示通过与否。

### 5.2 原生敏感会话 UI 驱动（补充证据）

```powershell
& 'venv312\Scripts\python.exe' 'main/tests/native_sensitive_session.py' --run --language zh --scale 100 --output 'D:\evidence\sensitive-session-20261010'
```

它会验证：敏感会话期间输出目录为空、无 `history.db`；只有显式 Copy 才复制且带 `sensitive=True`；
会话结束复位；钉图/脱敏继承敏感标志。注意它内部写的是 `real_clipboard_exclusion_verified: false`，
**它是 UI/策略证据，不能替代 5.1**。

## 6. 通过门槛（缺一不可）

- 5.1 **exit 0**，且 `result.json` 中所有 check 都是 passed（没有失败项、没有跳过项）；
- 5.2 exit 0；
- 证据保留：`result.json`、运行日志、脚本产生的 PNG/截图（如果有）；
- 回执里必须写清：机器环境、是否真的用了独立 window station / VM、**是否触碰了用户真实剪贴板**。

## 7. 明确不做

- 不删除/不改动用户真实的配置、数据库、截图目录；如果发现脚本写到了真实路径，**立即停止并报告**。
- 不申请或尝试绕过受保护内容；不承诺系统级擦除。
- 不自动上传、不改发布渠道、不做发布动作。
- 不要应用 `.agent-workbench/task-forest/proposals/` 里的任何提案（需用户确认）；不要改 Task Forest 正式状态。

## 8. 失败了怎么办

- `CreateWindowStationW` 仍 WinError 5：记录 `error`、访问掩码、`whoami /priv`、是否 VM → 停止，不退回真实剪贴板。
- 5.1 失败：把 `result.json` 失败项**原文**带回来，不要改写结论，也不要自行"修"成通过。
- 出现真实数据残留：立即停止并报告路径与数据类型，**不要自行删除**。

## 9. 回执模板

```
环境：Windows 版本 / 会话类型（独立 window station / VM / 沙箱）/ 是否管理员
命令 1：… → exit ?
命令 2：… → exit ?
证据路径：…
失败项原文：…
是否触碰真实剪贴板：是/否（若是，说明快照与恢复方式）
结论：TF-0030 真实零留存 = 通过 / 未通过 / 仍被环境阻塞（附证据）
```

## 10. 相关代码与材料

- 驱动脚本：`main/tests/native_private_clipboard.py`、`main/tests/native_sensitive_session.py`
- 敏感复制与标记：`main/core/clipboard_utils.py`（`PRIVATE_CAPTURE_FORMAT`、`_copy_win32_legacy`）
- Rust 隐私模块：`rust_libs/pyclipboard/src/privacy.rs`、`rust_libs/pyclipboard/src/lib.rs`（协议版本 1）
- 实现与历史证据：`docs/screenshot-expansion-progress.md`（搜索 "第十五批"）
- 相关任务提案（**不要应用**）：`.agent-workbench/task-forest/proposals/TFP-20261010-private-clipboard-progress.json`、
  `TFP-20261010-sensitive-session-progress.json`
- 历史失败日志（若存在）：`.ui_review/screenshot-expansion/sensitive-session-native-zh.log`

## 11. 当前整体状态（供参考）

- 全库回归（本轮最终）：3489 passed / 2 skipped / 675 warnings / 230.56 秒 / exit 0。
- 剩余节点只有 TF-0030；其余 37/38 已有本地实现与证据（含原生 DPI、捕获兼容性、安装包自检 8/8）。
- 所有累计进度提案都处于 `proposed`（未应用）；正式 Task Forest 的 45 个节点状态不变。
- 代码未提交，工作区保持 dirty。
