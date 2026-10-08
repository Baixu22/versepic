# shadcn/ui 风格对齐 — 三个页面

## 2026-10-04：页面布局与文案整理

在已有 Qt 组件和中性主题上继续调整，参考官方 [Tabs](https://ui.shadcn.com/docs/components/base/tabs) 的浅底分段容器与实体选中项。复用原生 Qt 控件，不增加依赖。

- **剪贴板历史**：补回搜索收起时的标题；有查询词时显示查询词并保持筛选。类型筛选使用统一的分段底色，搜索输入使用细边框。
- **剪贴板管理**：保留导航、列表、编辑器三栏及固定保存区；增加简短操作说明，避免重复分组类型描述。
- **截图设置**：按「常规 / 放大镜 / 保存与钉图」分成三个标签页，各自滚动；切换不丢编辑内容。保存提示紧邻保存选项；底部明确标注「重置截图设置」，仍重置所有截图选项。
- **公共细节**：短中文 Tooltip 保持单行，长提示仍换行；修复关闭动效时隐藏剪贴板的递归调用。
- **翻译**：新增 8 条文案覆盖中、英、日、韩，压缩 8 条中文说明；已重编译四份 QM，并逐条核对 40 条精确上下文译文。

相关回归：**263 passed、1 skipped，exit 0，49.31s**。跳过项是离屏平台不支持的窗口透明度验证；随后在原生 Windows 平台补测搜索、透明度、关闭动效和提示，**5 passed，exit 0，7.80s**，记录为 `.ui_review/unified-native-tests.log`。改动文件 Ruff 与 `git diff --check` 均 exit 0。

原生 Windows Qt 使用隔离设置及示例数据，分别生成中文 100%、英文 150% 的深浅色截图，各 38 张，两次命令均 exit 0。覆盖默认/最小窗口、全部截图标签、管理表单、剪贴板查询、选中/悬停及 Tooltip；截图设置无水平溢出。没有执行全仓测试或全应用业务验收。

本轮证据：`.ui_review/unified-tests-final.log`、`.ui_review/unified-lint.log`、`.ui_review/unified-native.log`、`.ui_review/unified-en-150.log`，截图在 `.ui_review/unified-after/` 与 `.ui_review/unified-en-150/`。可用 `.ui_review/unified-pages.py` 重现；这些是本机验收产物。

以下保留此前的圆角与主题对齐记录；历史测试数字不代表本轮结果。

---

目标：让**剪贴板窗口**、**内容管理窗口**、**设置 › 截图设置页**风格一致，并按
[shadcn/ui](https://ui.shadcn.com/docs/components) 的观感到齐配色、圆角、描边、间距、字重。
只做视觉还原，不改交互架构、不改业务逻辑。

## 现状：三层主题各自为政

三个页面分别由**三套互不相干**的几何/配色来源驱动，这是「风格不一致」的根因：

| 页面 | 入口 | 取色来源 | 圆角来源 |
| --- | --- | --- | --- |
| 剪贴板窗口 | `clipboard_window.py` | `themes.ThemeColors` → `theme_styles.surface_palette()` | `theme_styles.py` 里写死的 7/8/10/14 |
| 内容管理 | `manage_dialog.py` | `management_palette()` 把 `ThemeColors` 桥接进 `ui_theme` tokens | `ui/apple_style.py` 的 6/10/12 |
| 截图设置页 | `page_capture.py` | `ui_theme` tokens（经 `fluent_lite.theme.ui_tokens`） | `fluent_lite/theme.py` 的 6/8/10/12 |

三套圆角刻度：

- `theme_styles.py`：按钮 7、输入 8、浮层 14
- `apple_style.py`：control 6、card/chip 10、window 12、input 10
- `fluent_lite/theme.py`：ITEM 6、CONTROL 8、SURFACE 10、WINDOW 12、POPUP 8

字号同样三套：`theme_styles` 用 12/13/14，`fluent_lite` 以 14 为基准，
截图页用 12/13/14/15。

好消息是**配色层已经基本对好了**：`core/ui_theme.py` 的中性 token 本来就是
shadcn 中性色（`#171717` / `#FAFAFA` / `#E7E7E7`），且 `themes._neutral_colors()`
已把 apple/light/dark 三个预设桥接到这套 token。所以主要工作在**圆角与字号统一**，
而不是重做配色。

## shadcn 的圆角刻度（`--radius: 0.625rem` = 10px）

| Token | 值 | shadcn class | 用途 |
| --- | --- | --- | --- |
| `RADIUS_SM` | 6 | `rounded-sm` | 徽标、kbd、小色块 |
| `RADIUS_MD` | 8 | `rounded-md` | 按钮、输入框、菜单项 |
| `RADIUS_LG` | 10 | `rounded-lg` | 对话框、浮层 |
| `RADIUS_XL` | 14 | `rounded-xl` | 卡片、窗口 |

统一后：三页的按钮/输入 8、菜单项 6、浮层 10、卡片与窗口 14。

## 实施

### 1. 单一圆角来源

`core/ui_theme.py` 新增 `RADIUS_SM/MD/LG/XL`，三处消费方都改读它，
不再各写一套数字：

- `clipboard/ui/theme/theme_styles.py`：7/8/10/14 → 共享 token
- `ui/apple_style.py`：6/10/12 → 共享 token
- `ui/fluent_lite/theme.py`：`CONTROL_RADIUS` 等改为共享 token 的别名，
  名字保持不变，现有 import 不受影响
- `clipboard/ui/windows/clipboard_window.py`：工具栏按钮 16 → 8、
  搜索框胶囊 17 → 8、窗口圆角 12 → 14
- `clipboard/ui/dialogs/manage_dialog.py`：导航列圆角 18 → `SURFACE_RADIUS`

### 2. 顺带修掉的真实缺陷

- **预览弹窗深色失效**：`preview_popup.py` 把 `#FAFAFA`/`#333` 写死在样式表里，
  而它是独立顶层窗口、拿不到剪贴板窗口的样式，深色主题下会弹出一块白底黑字。
  现在订阅 `theme_changed`，用 `generate_preview_popup_style()` 取色。
- **提示文案不跟随缩放**：截图页的 `hint.setStyleSheet("padding: 5px;")` 是唯一
  一处没走 `dialog_scaled()` 的（同页其他页都在用），100% 缩放下看不出，
  150% 时和相邻间距对不上。已改为 `dialog_scaled(5)`。

### 3. 文案与布局

- 截图页 `💡 Hint: Even with auto-save off, it will be copied to clipboard.`
  按 `docs/manage-ui-review.md`「避免满屏 emoji」的既定方向，去掉 emoji 并把
  句子写成陈述式：`With auto-save off, the screenshot is still copied to the
  clipboard.`。四个语言的 XML 与 `.qm` 同步更新。
- 分组标题从 12px/600 改为 13px/500 + 次级色：原样式与卡片内标题（14px/500）
  层级太近，看起来像两层标题。

**没有**把截图页从 `SettingCardGroup` 换成 `SectionCard`。中途发现 9 个设置页里
8 个用 `SettingCardGroup`、只有 `page_hotkey.py` 用 `SectionCard`——换过去反而
让截图页成为异类。改为对齐分组标题的字号字重，代价小且不动结构。

## 验收

- 三个页面在浅色/深色下圆角、描边、字号、字重一致。
- 全量测试不低于基线（基线：2462 passed / 29 failed / 2 skipped；29 个失败是
  沙箱环境导致，见下）。
- 渲染截图核对。

### 验证结果

- 全量测试：**2462 passed / 29 failed / 2 skipped**，失败集合与基线**逐条完全一致**
  （`Compare-Object` 无差异），确认零回归。
- 渲染：`.ui_review/shadcn-aligned/` 下 `settings-capture-{light,dark}.png`、
  `manage-{light,dark}.png`；剪贴板窗口用 `.ui_review/round5/capture.py`
  在真实 Windows 平台 + 真实 DWM 合成下截图（`after_light.png` / `after_dark.png`）。

  注意：离屏（offscreen）平台无法合成无边框窗口，`ManageDialog.grab()` 会得到
  空白图；上述截图因此在 `QT_QPA_PLATFORM=windows` 下生成，脚本为
  `.ui_review/render_shadcn_native.py`。

## 改动前 vs 改动后

| 位置 | 改动前 | 改动后 |
| --- | --- | --- |
| 剪贴板工具栏按钮 | 16 | 8 |
| 剪贴板搜索框 | 17（胶囊） | 8 |
| 剪贴板窗口 | 8（Win11）/ 12 | 8（Win11）/ 14 |
| 内容管理导航列 | 18 | 10 |
| 生成器按钮 | 7 | 8 |
| 生成器输入/下拉 | 8 | 8 |
| 生成器浮层 | 14 | 10 |
| `apple_style` control | 6 | 8 |
| `apple_style` card | 10 | 10 |
| `apple_style` window | 12 | 14 |
| `fluent_lite` window | 12 | 14 |
| 截图页提示 padding | 5px（不缩放） | `dialog_scaled(5)` |
| 分组标题 | 12px/600/主色 | 13px/500/次级色 |

## 基线记录

`.ui_review/shadcn/baseline_full.txt`：2462 passed, 29 failed, 2 skipped。

29 个失败全部来自环境，与本次改动无关：

- `test_double_click_confirm.py`（28 个）：测试用 `subprocess` 捕获子进程输出，
  沙箱禁止管道 stdio（EPERM）。
- `test_module_imports.py`（1 个）：同类子进程限制。

另：沙箱下 `os.mkdir(mode=0o700)` 建出的目录无法枚举，导致 pytest 的
`tmp_path_factory` 在**每个**测试 setup 失败。用 `build/run_pytest.py` 规避
（会话内把 mkdir 权限位改成 0o777，并把 TEMP 指到工作区内），不改项目代码。

翻译改动只需重跑 `main/compile_translations.py`；沙箱下它的 `capture_output=True`
会被 EPERM 拦住，用 `build/compile_translations_nocapture.py` 代替（继承 stdio，
只取退出码）。
