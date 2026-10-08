# Qt components 对齐与复用约定

参考：[shadcn/ui Components](https://ui.shadcn.com/docs/components)。本次读取官方
`https://ui.shadcn.com/r/styles/new-york-v4/{component}.json` 中的 Button、Input、
Textarea、Select、Checkbox、Radio Group、Switch、Tabs、Dropdown Menu、Tooltip、
Badge、Card、Dialog 实现。以该套组件的语义、状态与外观作为参考，保留 Qt 的编辑、
菜单、模态窗口与无障碍语义。不是 React/Tailwind 的运行时封装，也不承诺逐像素一致。

## 现有组件盘点

| shadcn 组件 | 现有 Qt 入口 | 实际使用位置与本次处理 |
| --- | --- | --- |
| Button / Toggle | `Button`、`PushButton`、`PrimaryPushButton`、`TransparentPushButton` | 设置、管理、OCR、翻译等；统一到一个 Button 基类，旧名称保留；Toggle 使用 `setCheckable(True)` |
| Icon Button | `IconButton`、`TransparentToolButton` | 图标操作、设置刷新；与普通按钮共用颜色配方与圆角，QToolButton 保留菜单语义 |
| Input / Textarea | `LineEdit`、`TextEdit` | 设置、内容编辑、OCR；共用输入尺寸、焦点与错误态、右键菜单 |
| Select | `ComboBox` | 设置与剪贴板筛选；与输入框共用外框，下拉沿用原生键盘与禁用项行为 |
| 数字输入 | `SpinBox`、`DoubleSpinBox` | 截图设置；扩展同一套 Input 样式，保留数值校验 |
| Checkbox | `CheckBox` | 通用确认框、颜色格式管理、脱敏选项接入；支持三态 |
| Radio Group | `RadioButton` + Qt 的互斥组 | 剪贴板分组表单；复用现有指示器、文字避让与键盘互斥行为 |
| Switch | `SwitchButton` | 设置、欢迎页；统一动画时长，修复缩放后的滑块间距并支持 RTL |
| Tabs | `SegmentedWidget` | 设置与分段切换；单个 Tab 停靠点，方向键跳过禁用项，Home/End、RTL |
| Dropdown / Context Menu | `Menu`、`menu_qss()` | 设置菜单、剪贴板菜单、编辑器右键菜单共用一份样式配方，保留窗口自己的主题 |
| Tooltip | `ToolTip.install(root)` | 窗口作用域内共用一个提示；鼠标和键盘焦点均可触发，失焦/Esc/隐藏时消失 |
| Badge | `Badge` | 现有徽标组件；统一主题与 destructive 填充，展示页可对照 |
| Separator | `Separator` | 现有横/竖分隔线；公开统一导入入口 |
| Card | `SimpleCardWidget`、`SettingCard`、`SettingCardGroup` | 设置行、分组与容器；尺寸层级共用常量，业务布局继续组合 |
| Dialog / Alert Dialog | `StandardDialog`、`DialogButtonBox` | 通用确认/提示框；跟随本地主题，按钮按 Qt role 映射到共用 Button |
| Sidebar | `NavigationInterface` | 设置、管理导航；复用主题、圆角和动效，管理页保留自己的文字/布局 |
| Scroll Area | Qt `QScrollArea` + `scrollbar_qss()` | 设置、编辑区；复用现有滚动条入口 |

专用控件也已定位，但没有用通用组件覆盖其业务行为：截图工具条/画布控制点、
圆角与边框阴影滑块、文字描边的离散刻度滑块、GIF 进度条、日期选择和分组列表。
这些控件包含截图强调色、实时预览或特殊命中区域。本次保持原实现；它们不计入已完成的
通用组件迁移。网站中项目尚未使用的 Carousel、Chart、Command 等未新增。

## 单一维护入口

1. **颜色**：`main/core/ui_theme.py` 的 `UIThemeTokens`。组件通过
   `ui_tokens(widget)` 查找窗口作用域，禁止直接读取全局主题替代父窗口覆盖。
   `danger` 用于错误文字；`destructive_background` 用于承载白字的按钮填充。
2. **尺寸与样式配方**：`main/ui/fluent_lite/theme.py`。控件圆角、菜单项圆角、
   卡片圆角、输入高度、动效时长，以及 `button_colors`、`button_qss`、`menu_qss`
   集中维护。原生 Qt 需要自己的绘制实现，但不得另起一套配色与尺寸。
3. **组件**：`main/ui/fluent_lite/`。兼容现有导入路径，避免创建并行的第二套 Qt UI 库。
4. **业务页面**：仅组合布局、文案、数据与信号。普通操作按钮选择 variant，
   不再粘贴一份 QSS。例如管理页删除与关闭按钮已移除各自的样式函数。

旧页面有意使用自定义 QSS 的兼容入口仍保留，颜色样本按钮也继续显示用户选定的颜色。
新增普通控件应使用公共 API；迁移旧页面时逐个核对主题与缩放，避免全局替换破坏截图操作。

```python
from ui.fluent_lite import Button, LineEdit, Menu, ToolTip
from core.ui_scale import configure_dialog_controls

save = Button("保存", parent, variant="primary")
delete = Button("删除", parent, variant="destructive")
name = LineEdit(parent)
name.setAccessibleName("名称")
name.setInvalid(False)  # 业务校验负责提示文案；组件负责一致的错误外观
menu = Menu(parent=save)
ToolTip.install(parent)
# 完成窗口布局后，将业务窗口缩放应用到组件的基准尺寸。
configure_dialog_controls(parent)
```

按钮支持 `primary/default`、`secondary`、`outline`、`ghost`、`destructive`、`link`；
尺寸支持 `xs`、`sm`、`md/default`、`lg`、`icon`、`icon-sm`、`icon-lg`。
旧 `PushButton` 对应 outline，`PrimaryPushButton` 对应 primary，
`TransparentPushButton` 对应 ghost。已有代码无需批量改名。

## 可运行的组件展示页

展示页直接使用生产组件，无另一套展示专用控件；不读取个人设置、剪贴板或网络。

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'main')
.\venv312\Scripts\python.exe -m ui.component_gallery
# 可重复生成浅色/深色截图，也可指定 --scale 150。
.\venv312\Scripts\python.exe -m ui.component_gallery --capture .ui_review/shadcn --scale 100
```

验证包括 `main/tests/test_shared_components.py`、现有组件、缩放、主题、管理页、
颜色格式、脱敏与设置即时生效测试。原生截图与原生 Qt 事件测试单独运行；
offscreen 测试不作为完整桌面交互验收的替代。

本次验证（2026-09-30，Python 3.12.13 / PySide6 6.11.0）：完整测试
**2464 passed、2 skipped**，exit 0；原生 Windows Qt 组件/菜单测试
**18 passed**，exit 0；改动范围 Ruff 与 `git diff --check` 均 exit 0。
完整测试产生 640 条警告，主要为现有 Qt/Pillow 弃用调用及未注册的 pytest 标记，
未在这次组件迁移中扩展处理。日志和深浅色组件/实际页面截图保存在 `.ui_review/shadcn*`。
