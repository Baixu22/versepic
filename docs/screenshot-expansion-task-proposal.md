# VersePic 截图拓展任务提案

日期：2026-10-09。提案：`TFP-20261009-screenshot-expansion`。源码基线：`d6221be`。

> 状态：**用户已确认开始落实，提案已正式应用。** 本提案建立 45 个节点：1 个全局目标、6 个分支、38 个具体任务；44 条主归属边、15 条前置依赖、2 条次级贡献关系。正式节点编号为 TF-0001 至 TF-0045；入库不表示功能已经完成。

- [已应用的原始提案 JSON](C:/Users/27933/Desktop/versepixpin/jietuba/.agent-workbench/task-forest/proposals/TFP-20261009-screenshot-expansion.json)
- [正式森林 HTML](C:/Users/27933/Desktop/versepixpin/jietuba/.agent-workbench/task-forest/exports/task-forest.html)：只反映正式状态；未开始任务按导出规则计入未完成数量，不伪装为进行中。

## 全局目标

拓展 VersePic 截图能力：快捷截取、可复用编辑与可靠输出

保持本地轻量截图工作台定位，将已确认有增量价值的能力整理为可独立开发、逐批验收的任务。

## 开发边界与状态规则

- 复用既有模块和共享 Qt 组件，优先标准库及现有依赖；新增依赖需单独说明必要性。
- 实施前检查当前差异并重新核对相关代码；保留用户未提交工作和现有行为。
- 不得用历史测试、静态语法检查或生成文件存在替代本功能验收。
- 所有新增节点初始为 proposed、进度 0；已有功能只作为复用基础，不重复登记为待实现能力。
- 每个开发节点具有唯一主父节点、明确范围、真实前置依赖和验收标准。
- 优先级 1 为高频补齐或质量门槛，2 为后续重点，3 为场景增强，4 为需进一步验证的可选能力。
- 可选任务不默认纳入首个交付批次；采用或退役必须经后续提案确认。
- 非目标：不开发全能 AI 截图助手、云相册、账号协作服务、完整 Photoshop 式编辑器或插件平台。
- 非目标：不重新实现已经具备的基础 OCR、横向长截图、GIF 裁剪、圆角阴影或贴图功能。
- 非目标：不将本轮任务规划算作功能开发进度，不自动提交代码或发布安装包。
- 所有节点初始状态均为 `proposed`、进度 0%。提案应用与功能执行是两回事。
- 难度仅为相对判断，未承诺工时。不要为了出现在 HTML 里而把未开发任务标成进行中。
- 原生验收使用隔离演示数据，不访问或污染用户真实剪贴板。
- 在应用提案时由 CLI 分配正式节点编号；下文仅用任务名称与内部别名关联依赖。

## 六个开发分支

| 分支 | 具体任务数 | 目标 |
| --- | ---: | --- |
| 快捷截取与可控输出 | 7 | 先补高频小缺口，让用户更准确地截取，并控制图片尺寸、体积与命名。 |
| 多图收集与长截图修正 | 8 | 把多次截图组织成可交付的长图或 PDF，同时提供长截图的可控恢复与修正。 |
| 轻量编辑与成果复用 | 6 | 复用现有画布拓展文件编辑、可编辑工程、截图对比及动图输出。 |
| 结构化识别与隐私保护 | 5 | 在已有 OCR、文字索引和脱敏基础上增加用户控制、结构化输出和明确的数据留存边界。 |
| 教程标注与问题报告 | 8 | 按实际需求增加解释性标注、图片标识和本地报告输出，不扩成完整设计工具。 |
| 兼容性验证与交付收尾 | 4 | 用真实平台证据约束功能完成状态，并确保安装包和文档与已验收范围一致。 |

## 建议启动顺序

1. 延时截图、数字尺寸选区、导出尺寸与质量控制。
2. 快捷截取、区域预设与命名；多图拼版、多页 PDF 和连续收集。
3. 长截图恢复与修正、轻编辑及可编辑工程。
4. 对比、结构化 OCR、教程与报告增强按实际需求选取。
5. 每批同步执行所需的平台/隐私验收，完成回归后再验证安装包与文档。
6. 自动滚动与 MP4 导出均为先验证可行性的候选，不默认进入首批。

## 1. 快捷截取与可控输出

先补高频小缺口，让用户更准确地截取，并控制图片尺寸、体积与命名。

### 延时截图与可取消倒计时

允许用户在截图前展开菜单、下拉框和悬浮提示，避免触发截图后目标消失。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：低。
- 初始状态：拟议 / 0%；内部别名：`delayed-capture`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 提供 3/5/10 秒入口，复用普通截图入口
- 支持 Esc 取消、重复触发合并及退出清理

**验收条件**
- 倒计时结束只启动一次截图，取消与退出后不再采集
- 菜单和 Tooltip 场景完成原生 Windows 操作验收，倒计时界面不进入成图
- 覆盖重复触发、模态窗口和采集失败的定向回归

**建议代码落点**
- [main/main_app.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/main_app.py)
- [main/ui/tray_menu.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/tray_menu.py)
- [main/ui/settings_ui/page_capture.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/settings_ui/page_capture.py)

### 当前屏幕、活动窗口和上次区域的快捷截取

为高频截图提供无需再次框选的独立入口，同时保留原截图快捷键行为。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`quick-capture`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 提供当前显示器、可见活动窗口、上次区域的快捷动作
- 支持快捷键冲突反馈及用户选择直接复制或进入编辑

**验收条件**
- 在启动截图层前确定目标窗口，避免把自身当作目标
- 负坐标副屏、失效窗口及越界上次区域有明确安全回退
- 不承诺截取最小化窗口或被遮挡内容，不破坏既有快捷键

**建议代码落点**
- [main/main_app.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/main_app.py)
- [main/capture/capture_service.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/capture_service.py)
- [main/capture/window_finder.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/window_finder.py)
- [main/core/last_capture_region.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/last_capture_region.py)
- [main/core/shortcut_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/shortcut_manager.py)

### 数字尺寸输入与常用比例选区

让用户能够精确设置坐标、宽高与常用比例，而不是仅查看尺寸或锁定当前比例。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`precise-region`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 支持 X/Y/宽/高输入和 1:1、4:3、16:9 比例
- 复用单选区模型、已有比例约束和信息面板

**验收条件**
- 输入、拖动、比例切换后的选区与导出像素尺寸一致
- 无效尺寸和越界坐标得到校验，负坐标显示器可正常使用
- 已有圆角、阴影、锁比及标注交互不退化

**建议代码落点**
- [main/ui/selection_info/panel.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/selection_info/panel.py)
- [main/ui/selection_info/lock_ratio.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/selection_info/lock_ratio.py)
- [main/canvas/selection_model.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/selection_model.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)

### 保存并恢复命名截图区域

将当前只保存在内存中的上次区域扩展为用户明确保存的跨重启预设。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`region-presets`。
- 前置依赖：「数字尺寸输入与常用比例选区」

**开发范围**
- 支持新增、重命名、删除与选择命名区域
- 保存必要的显示器几何信息，沿用现有设置存储

**验收条件**
- 退出重启后能恢复用户明确保存的预设
- 显示器拔插、布局或缩放改变时提示调整，不静默截错位置
- 预设可删除，临时上次区域行为与快捷键保持兼容

**建议代码落点**
- [main/core/last_capture_region.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/last_capture_region.py)
- [main/settings/tool_settings.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/settings/tool_settings.py)
- [main/ui/settings_ui/page_capture.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/settings_ui/page_capture.py)

### 导出尺寸、质量控制与分享预设

接通已有但尚未使用的截图质量配置，并提供原图、缩小和指定宽度输出。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`image-export-presets`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 统一 Qt/Pillow 的格式、缩放和质量参数传递
- 提供原始尺寸、50%、指定宽度及少量分享/留档预设

**验收条件**
- JPG/WebP 的质量值实际传入编码器并有参数回归，PNG/BMP 不误用有损质量
- 普通截图、长截图、贴图相关输出行为按明确入口一致
- 小尺寸和透明图导出正确，保存失败有反馈且不覆盖原图

**建议代码落点**
- [main/settings/tool_settings.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/settings/tool_settings.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)
- [main/tools/action.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/action.py)
- [main/ui/settings_ui/page_capture.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/settings_ui/page_capture.py)

### 截图命名模板与日期目录

减少截图整理成本，支持日期、序号和手填项目名组成的有限文件名模板。

- 优先级：2（后续重点）；相对难度：低。
- 初始状态：拟议 / 0%；内部别名：`file-naming`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 提供少量安全占位符与预览
- 支持可选日期子目录，复用唯一文件路径分配

**验收条件**
- 非法字符、保留名、路径穿越、同秒多图和已有文件碰撞被安全处理
- 默认命名保持兼容，不默认添加窗口标题等敏感内容
- 实际输出路径与预览一致，失败不留下误导性空文件

**建议代码落点**
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)
- [main/settings/tool_settings.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/settings/tool_settings.py)
- [main/ui/settings_ui/page_capture.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/settings_ui/page_capture.py)

### 静态截图可选择包含真实鼠标指针

为教程截图提供真实指针显示开关，区别于现有 GIF 鼠标效果。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`static-cursor`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 默认行为不变，显式开启后合成采集时的指针
- 处理指针热点、缩放与选区边界

**验收条件**
- 箭头、文本光标与高 DPI 指针位置正确，热点误差有像素对照
- 没有重复指针、截图层光标或越界残影
- 选区外指针不进入图片，不影响取色与 GIF 原有行为

**建议代码落点**
- [main/capture/capture_service.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/capture_service.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)
- [main/gif/cursor_overlay.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/cursor_overlay.py)

## 2. 多图收集与长截图修正

把多次截图组织成可交付的长图或 PDF，同时提供长截图的可控恢复与修正。

### 历史图片与贴图的多图拼版

把已存在的多张图片排成一张教程图或记录图，而不是进行重叠内容长截图匹配。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`image-layout`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 从历史图片或贴图选择多张图片，拖动排序
- 支持上下/左右排版、统一宽度、间距和底色，导出合成图

**验收条件**
- 排序与导出顺序一致，空选择和失效记录有反馈
- 透明图、不同尺寸和大图输入有受控内存占用且不修改源图片
- 预览与导出尺寸及留白一致，取消后释放临时数据

**不做的内容**
- 不建立自由画布排版器或新的独立图片库

**建议代码落点**
- [main/clipboard/ui/windows/clipboard_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/ui/windows/clipboard_window.py)
- [main/clipboard/core/manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/manager.py)
- [main/pin/pin_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_manager.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)

### 多张图片按顺序导出多页 PDF

补齐当前仅支持单张图片页的 PDF 输出，直接整理票据、页面和截图。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`multi-page-pdf`。
- 前置依赖：「历史图片与贴图的多图拼版」

**开发范围**
- 复用多图选择与排序结果
- 提供一图一页、原图尺寸或统一纸张适配，以及页边距

**验收条件**
- 页数和顺序与选择一致，超宽/超长/透明图不裁掉有效内容
- 生成 PDF 在独立阅读器打开检查分页、缩放和边距
- 不默认加入 OCR 文字层，不覆盖已有文件且失败有反馈

**建议代码落点**
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)
- [main/clipboard/ui/windows/clipboard_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/ui/windows/clipboard_window.py)
- [main/pin/pin_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_manager.py)

### 连续单区域截图与临时收集篮

减少反复启动截图的成本，将多次截图集中到一个可整理的临时结果列表。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`capture-basket`。
- 前置依赖：「历史图片与贴图的多图拼版」

**开发范围**
- 增加完成后继续截图选项，保留单区域会话机制
- 收集篮支持预览、排序、删除及统一保存或进入拼版

**验收条件**
- 连续截取时上一轮标注、选区和快捷键状态不污染下一轮
- 每次输出仅进入列表一次，收集篮自身不进入成图
- 完成、取消、退出和内存上限行为明确，不默认为持久化录屏

**建议代码落点**
- [main/main_app.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/main_app.py)
- [main/ui/screenshot_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/screenshot_window.py)
- [main/tools/action.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/action.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)

### 同一冻结画面提取多个区域

在已有连续收集流程上支持一次冻结多个选区，适合从同屏资料摘取多个片段。

- 优先级：3（场景增强，按需选做）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`multi-region-freeze`。
- 前置依赖：「连续单区域截图与临时收集篮」

**开发范围**
- 在冻结底图上新增、删除、排序多个矩形选区
- 每个选区独立导出并进入收集篮，不重写完整多图编辑系统

**验收条件**
- 各区域来自同一帧且不包含选区装饰，相交区域规则明确
- 区域顺序、零面积、越界、撤销和取消经过回归
- 不会把单选区绘制对象错误复用到所有输出区域

**不做的内容**
- 第一版不支持每个区域独立复杂图层会话

**建议代码落点**
- [main/canvas/selection_model.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/selection_model.py)
- [main/canvas/view.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/view.py)
- [main/ui/screenshot_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/screenshot_window.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)

### 长截图撤销最近拼接与有限检查点

允许恢复到最近一次可靠结果，弥补目前失败后只能忽略新帧的交互缺口。

- 优先级：2（后续重点）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`stitch-checkpoint`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 保留受数量或内存预算限制的拼接检查点
- 支持撤销最近一次成功拼接，并明确失败重采集操作

**验收条件**
- 正向、反向、横向拼接撤销后结果和滚动方向状态一致
- 检查点数量/内存有上限，关闭会话释放临时图片
- 拼接失败不损坏此前有效结果，超大图与连续失败有测试

**建议代码落点**
- [main/stitch/scroll_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/scroll_window.py)
- [main/stitch/jietuba_long_stitch_unified.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/jietuba_long_stitch_unified.py)
- [main/tests/test_stitch_integration.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tests/test_stitch_integration.py)

### 长截图接缝预览与手工重叠调整

当自动重叠匹配不可靠时，让用户可查看接缝并手动修正，而不是只能重新开始。

- 优先级：3（场景增强，按需选做）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`stitch-seam`。
- 前置依赖：「长截图撤销最近拼接与有限检查点」

**开发范围**
- 显示最近接缝附近的两帧预览
- 允许调整重叠量，确认后替换结果，取消恢复原结果

**验收条件**
- 用有明确像素标记的样例验证无重复行、漏行及错误方向
- 修正、撤销、继续采集与导出的内容一致
- 修正采用检查点帧且受同一资源限制，不无限保留全部原图

**建议代码落点**
- [main/stitch/scroll_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/scroll_window.py)
- [main/stitch/jietuba_long_stitch_unified.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/jietuba_long_stitch_unified.py)

### 可视化选择长截图固定标题栏忽略区

把已有顶部忽略像素配置变成可理解、可预览的界面，降低固定栏干扰。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`stitch-fixed-header`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 复用现有 ignore_top_pixels 等有效接口
- 标出匹配忽略区与实际输出裁剪的区别，支持恢复默认

**验收条件**
- 配置真正传入匹配链路，预览不会误导为删除输出内容
- 竖向、反向和横向模式分别验证，避免同一参数错用
- 测试覆盖固定页头与无固定栏页面，失败信息仍可操作

**建议代码落点**
- [main/stitch/scroll_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/scroll_window.py)
- [main/stitch/jietuba_long_stitch_unified.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/jietuba_long_stitch_unified.py)
- [main/settings/tool_settings.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/settings/tool_settings.py)

### 用户控制的自动滚动长截图

在现有滚轮后采集基础上增加受控自动滚动，减少重复操作但不做无人值守自动化。

- 优先级：4（先验证需求与可行性）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`auto-scroll`。
- 前置依赖：「长截图撤销最近拼接与有限检查点」、「可视化选择长截图固定标题栏忽略区」

**开发范围**
- 由用户明确启动，提供步长、间隔及停止入口
- 到达重复画面、超时、最大高度/帧数或焦点丢失时停止

**验收条件**
- Esc/停止按钮立即终止，取消后无残留输入事件
- 不向其他窗口发送滚轮；停止后保留已确认结果
- 用实际网页和原生滚动容器验收，不把合成算法测试当真实兼容性通过

**不做的内容**
- 不绕过窗口权限，不提供后台无限滚动

**建议代码落点**
- [main/stitch/scroll_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/scroll_window.py)
- [main/stitch/scroll_toolbar.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/stitch/scroll_toolbar.py)

## 3. 轻量编辑与成果复用

复用现有画布拓展文件编辑、可编辑工程、截图对比及动图输出。

### 直接打开或拖入图片进行轻量编辑

把现有贴图画布开放为文件图片的明确编辑入口，避免先复制再贴图的绕路。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`external-editor`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 支持选择文件和拖入单张图片，复用现有画布与标注
- 支持裁剪、尺寸调整、已有旋转翻转能力及另存

**验收条件**
- 取消、非法图片、大图和文件丢失有反馈，原文件默认不被覆盖
- 裁剪或变换后标注位置、OCR 坐标和导出一致
- 浅色/深色、缩放和键盘操作通过实际界面验收

**不做的内容**
- 不新增第二套编辑器，不支持复杂滤镜和自由变形

**建议代码落点**
- [main/pin/pin_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_window.py)
- [main/pin/pin_canvas.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_canvas.py)
- [main/pin/pin_image_transform.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_image_transform.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)

### 保存与重新打开可编辑截图工程

将已经可在贴图中继续编辑的底图和标注结构持久化，让用户下次继续修改。

- 优先级：2（后续重点）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`editable-project`。
- 前置依赖：「直接打开或拖入图片进行轻量编辑」

**开发范围**
- 定义有版本号的最小工程格式，保存底图与支持的图元属性
- 提供手动保存/打开及未知版本或图元的明确错误

**验收条件**
- 关闭重开后各类支持图元、文字、位置、顺序和样式保持可编辑
- 采用受限数据格式而非 pickle/eval，限制资源尺寸、数量并校验路径
- 工程文件与扁平分享图片明确区分，脱敏导出不得夹带原图或可恢复图层

**不做的内容**
- 第一版不持久化完整撤销栈，不自动保存所有屏幕内容

**建议代码落点**
- [main/tools/action.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/action.py)
- [main/pin/pin_canvas.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_canvas.py)
- [main/canvas/undo.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/undo.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)

### 用户主动保存和恢复贴图工作区

保存多张贴图及位置、缩放和显示状态，重启后恢复参考材料。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`pin-workspace`。
- 前置依赖：「保存与重新打开可编辑截图工程」

**开发范围**
- 依托可编辑工程保存用户选定贴图集合
- 支持命名、打开、删除工作区，默认不后台自动持久化

**验收条件**
- 恢复后位置、缩放、缩略图和图元保持一致
- 显示器布局改变时窗口回到可见范围，缺失或损坏项目逐项报告
- 取消/删除可清楚移除保存内容，敏感原图不会因默认行为长期留存

**建议代码落点**
- [main/pin/pin_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_manager.py)
- [main/pin/pin_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_window.py)
- [main/pin/pin_thumbnail.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_thumbnail.py)

### 两张截图并排、滑杆及差异对比

帮助用户核对界面、版本或报表变化，先提供可解释的本地图片对比。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`image-compare`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 从历史、贴图或文件选择两张图片
- 并排与滑杆模式、同步缩放，以及可选像素差异高亮

**验收条件**
- 不同尺寸图片的对齐与缩放规则明确，不把重采样噪声称为业务差异
- 切换、替换图片和大图操作不泄漏资源，源图不变
- 使用已知差异样例校验高亮区域，原生界面验证对照操作

**不做的内容**
- 不增加 AI 语义对比、自动版本判定或测试平台

**建议代码落点**
- [main/pin/pin_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_window.py)
- [main/pin/pin_image_transform.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_image_transform.py)
- [main/clipboard/ui/windows/clipboard_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/ui/windows/clipboard_window.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)

### GIF 导出尺寸、帧率与体积控制

开放已有目标宽度等导出能力，让用户控制分享体积，而非新增一套 GIF 编辑器。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`gif-export-controls`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 提供原尺寸、指定宽度与受支持的帧率调整
- 沿用已有裁剪、速度和鼠标效果，展示实际文件大小

**验收条件**
- 参数真正到达合成器，裁剪时长、速度和指针位置在缩放后正确
- 帧率转换不引入明显重复时长错误，取消导出清理临时文件
- 体积若为估算必须明确标记，不声称未知编码参数已生效

**建议代码落点**
- [main/gif/composer.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/composer.py)
- [main/gif/playback_controller.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/playback_controller.py)
- [main/gif/playback_toolbar.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/playback_toolbar.py)
- [main/tests/test_gif_composer.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tests/test_gif_composer.py)

### 验证并提供无声 MP4 导出

复用现有录制帧与裁剪结果输出更适合分享的视频，先验证编码与打包可行性。

- 优先级：4（先验证需求与可行性）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`silent-mp4`。
- 前置依赖：「GIF 导出尺寸、帧率与体积控制」

**开发范围**
- 先验证现有 av 依赖和帧访问接口的编码能力
- 验证通过后提供无音轨 MP4 导出、进度及取消；不通过则记录阻塞与替代方案

**验收条件**
- 成品在独立播放器中可打开，时长、尺寸、裁剪和变速结果一致
- 奇数尺寸、长录制、取消、编码失败及内存占用有验证
- Windows 发布包实际具备所需编码能力，未通过可行性验证前不标功能完成

**不做的内容**
- 不做系统音频、麦克风、多轨剪辑或直播

**建议代码落点**
- [main/gif/frame_recorder.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/frame_recorder.py)
- [main/gif/playback_controller.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/playback_controller.py)
- [main/gif/composer.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/gif/composer.py)
- [requirements.txt](C:/Users/27933/Desktop/versepixpin/jietuba/requirements.txt)
- [rust_libs/gifrecorder/src/frame_store.rs](C:/Users/27933/Desktop/versepixpin/jietuba/rust_libs/gifrecorder/src/frame_store.rs)

## 4. 结构化识别与隐私保护

在已有 OCR、文字索引和脱敏基础上增加用户控制、结构化输出和明确的数据留存边界。

### 增加可校验的敏感信息规则与规则预设

在已有手机号、邮箱和关键词基础上增加身份证号、银行卡号等候选识别，保持人工复核。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`redaction-rules`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 增加格式/校验规则及可保存的启用组合
- 保留整行覆盖、手工补画、预览确认与原图不覆盖行为

**验收条件**
- 正反例集覆盖 OCR 混淆字符、误报及漏报，明确规则不保证覆盖全部隐私
- 输出 PNG/JPEG/PDF 均为扁平实色遮盖，边界像素不泄露原内容
- 截图和历史图片入口行为一致，关闭规则不会改变既有数据

**不做的内容**
- 不依赖人脸识别模型，不承诺字符级精准定位

**建议代码落点**
- [main/text_recognition/redaction.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/text_recognition/redaction.py)
- [main/text_recognition/redaction_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/text_recognition/redaction_window.py)
- [main/tests/test_screen_assistant.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tests/test_screen_assistant.py)

### 本次敏感截图不落盘、不入历史的临时模式

让用户明确控制单次截图的数据留存，而不是仅关闭全局自动保存。

- 优先级：2（后续重点）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`private-capture`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 提供单次敏感模式，跳过本应用的自动文件保存、历史入库和 OCR 索引
- 复核复制、贴图、脱敏、取消及后续普通截图的模式边界

**验收条件**
- 单次模式结束后恢复正常行为，不永久关闭监听或保存设置
- 用隔离数据库和输出目录验证不存在原始图、缩略图、索引或敏感日志残留
- 仅用户明确复制才写入系统剪贴板；明确不承诺删除其他软件已读取的内容

**不做的内容**
- 不提供系统级隐私擦除或阻止第三方剪贴板工具的保证

**建议代码落点**
- [main/tools/action.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/action.py)
- [main/core/clipboard_utils.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/clipboard_utils.py)
- [main/clipboard/core/manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/manager.py)
- [main/clipboard/core/image_text.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/image_text.py)
- [main/text_recognition/redaction_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/text_recognition/redaction_window.py)

### 历史图片文字索引的重试、重识别与单项排除

给现有后台 OCR 索引增加用户可理解的控制，而不是重新开发图片文字搜索。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`ocr-index-controls`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 显示明确的等待/识别/失败/排除状态
- 支持失败重试、重新识别以及单项排除与恢复

**验收条件**
- 被排除项不会被后台补索引任务再次自动加入
- 删除、取消、移动数据库后的迟到结果仍不能复活数据
- 搜索分页、原始粘贴格式及图片本身不变，重复操作幂等

**建议代码落点**
- [main/clipboard/core/image_text.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/image_text.py)
- [main/clipboard/core/manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/manager.py)
- [main/clipboard/ui/windows/clipboard_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/ui/windows/clipboard_window.py)
- [main/tests/test_screen_assistant.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tests/test_screen_assistant.py)

### 规整表格截图转可校正的 TSV 与 Markdown

利用现有 OCR 文字框重建简单行列，让表格可以粘贴到 Excel 或文档。

- 优先级：3（场景增强，按需选做）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`table-ocr`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 第一版限定清晰规整表格，保留图片和可修改的表格预览
- 支持 TSV 复制与 Markdown 表格导出，低置信结果提示人工校正

**验收条件**
- 带坐标的固定样例验证行列归属、空格、制表符和换行转义
- 实际粘贴到表格软件验证单元格落位，不把普通纯文本导出当表格识别完成
- 复杂合并单元格和跨行布局明确提示能力边界，无隐式云端上传

**不做的内容**
- 不宣称支持任意复杂表格、公式识别或 LaTeX

**建议代码落点**
- [main/ocr/ocr_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ocr/ocr_manager.py)
- [main/text_recognition/result_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/text_recognition/result_window.py)
- [main/clipboard/core/image_text.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/image_text.py)

### 截图 PDF 添加可搜索的 OCR 文字层

在现有图片型 PDF 上叠加位置一致的文字层，便于查找和复制内容。

- 优先级：3（场景增强，按需选做）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`searchable-pdf`。
- 前置依赖：「多张图片按顺序导出多页 PDF」

**开发范围**
- 复用 OCR 结果和图片坐标，支持明确的图片型/可搜索型输出选择
- 处理旋转、缩放、分页与阅读顺序

**验收条件**
- 独立 PDF 阅读器中能搜索和复制，图片与文字位置对齐
- 脱敏区域不嵌入原敏感文字；无法证明安全时拒绝为脱敏图嵌入原文字层
- 无文字、OCR 失败和多语言字体有回退及提示，不把 PDF 成功写盘当文字层验收

**建议代码落点**
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)
- [main/ocr/ocr_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ocr/ocr_manager.py)
- [main/text_recognition/redaction.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/text_recognition/redaction.py)
- [main/clipboard/core/image_text.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/image_text.py)

## 5. 教程标注与问题报告

按实际需求增加解释性标注、图片标识和本地报告输出，不扩成完整设计工具。

### 可导出的局部放大标注框

把图片局部以放大框形式放入成图，区别于仅辅助取色的屏幕放大镜。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`magnified-callout`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 选择源区域、调整放大框位置与倍率
- 复用图元选择、拖动、删除及撤销机制

**验收条件**
- 放大内容与源像素一致，移动和缩放后不偏移
- 框选自身或覆盖源区域时不递归取样，不包含 UI 控制点
- 复制、贴图继承与文件导出一致，未支持的工程类型有明确处理

**建议代码落点**
- [main/canvas/items/drawing_items.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/items/drawing_items.py)
- [main/canvas/smart_edit_controller.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/smart_edit_controller.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)
- [main/pin/pin_canvas.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_canvas.py)

### 箭头与文字气泡组合标注

让用户一次创建可移动的解释标注，减少手动调整箭头和文字的步骤。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`text-callout`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 复用现有箭头和文字能力组成简单关联标注
- 支持端点、气泡位置与内容编辑，统一撤销/删除

**验收条件**
- 组合移动和局部编辑不丢失关系，文字编辑快捷键正常
- 与原有单独箭头、文字、跨工具选择兼容
- 截图与贴图导出一致，不引入独立复杂图层系统

**建议代码落点**
- [main/tools/arrow.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/arrow.py)
- [main/tools/text.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/text.py)
- [main/canvas/items/text_item.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/items/text_item.py)
- [main/canvas/undo.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/undo.py)
- [main/pin/pin_canvas.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_canvas.py)

### 编号标注对应说明列表

把已有编号工具扩展为带文字说明的教程步骤，而不是另建编号工具。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`numbered-legend`。
- 前置依赖：「历史图片与贴图的多图拼版」

**开发范围**
- 支持为编号填写说明并导出旁注或下方步骤列表
- 编号、说明和排序保持关联

**验收条件**
- 删除、撤销、调整编号后说明不会错配或重复
- 长说明排版可阅读，多语言和换行不截断
- 既有无说明编号行为保持兼容，可与拼版组合使用

**建议代码落点**
- [main/tools/number.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/number.py)
- [main/canvas/items/drawing_items.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/items/drawing_items.py)
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)

### 在截图中插入小图片或 Logo

为截图补充示意图和标识，沿用现有画布而非制作海报编辑器。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`insert-image`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 从文件或剪贴板显式插入位图图元
- 支持移动、等比缩放、删除和撤销，明确层叠规则

**验收条件**
- 透明图片和不同 DPI 图片正确合成，大小和位置与导出一致
- 非法、超大图片和外部文件失效有安全处理
- 插图在贴图继承中保留，工程支持与否有明确版本校验

**建议代码落点**
- [main/canvas/scene.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/scene.py)
- [main/canvas/items/drawing_items.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/items/drawing_items.py)
- [main/canvas/undo.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/undo.py)
- [main/pin/pin_canvas.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_canvas.py)

### 导出时可选文字或图片水印

为共享图片提供简单的来源标识，不改变原图也不默认写入敏感信息。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`watermark`。
- 前置依赖：「导出尺寸、质量控制与分享预设」

**开发范围**
- 支持位置、边距、透明度和简单文字/图片水印
- 可预览且默认关闭，沿用最终图像导出链路

**验收条件**
- 预览与 PNG/JPEG/WebP/PDF 成图位置一致
- 透明背景、小图及缩放后文字仍可阅读且不越界
- 不覆盖源文件，不读取未授权的窗口标题或身份信息

**建议代码落点**
- [main/core/export.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/export.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)
- [main/settings/tool_settings.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/settings/tool_settings.py)

### 保存并复用常用标注样式

在现有每工具设置持久化基础上增加少量命名样式组合，减少重复调色和字号。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`annotation-presets`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 保存、应用、重命名和删除常用样式
- 按工具保存有效字段，复用现有设置面板和默认值

**验收条件**
- 重新启动后样式保留，非法或过期字段有回退
- 应用样式与选中图元编辑/新建工具设置语义明确，支持必要撤销
- 所有入口即时更新且不干扰工具栏自定义布局

**建议代码落点**
- [main/settings/tool_settings.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/settings/tool_settings.py)
- [main/ui/base_settings_panel.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/ui/base_settings_panel.py)
- [main/tools/controller.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tools/controller.py)
- [main/canvas/smart_edit_controller.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/smart_edit_controller.py)

### 截图可选来源信息、时间和备注

让问题报告可追溯，但只有用户显式选择的信息才随导出分享。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`capture-metadata`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 在截图前获取来源窗口/应用，允许用户查看、修改或删除
- 提供时间与备注；默认不把标题写入文件名或图片

**验收条件**
- 来源不是截图工具自身，窗口消失和权限不足有回退
- 预览清楚显示将导出的元数据，取消后不传播敏感标题
- 数据只进入用户选择的输出，原有剪贴板来源字段不被误用

**建议代码落点**
- [main/main_app.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/main_app.py)
- [main/capture/window_finder.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/window_finder.py)
- [main/clipboard/core/models.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/core/models.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)

### 多张截图导出 Markdown 问题报告

把截图、顺序和用户备注整理成可直接交付的本地问题报告。

- 优先级：3（场景增强，按需选做）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`markdown-report`。
- 前置依赖：「历史图片与贴图的多图拼版」

**开发范围**
- 复用图片选择和排序，导出 Markdown 及相对路径图片附件
- 支持手填标题、步骤和备注，可选用户批准的来源元数据

**验收条件**
- 将报告目录移到其他位置后图片仍可访问，顺序与说明一致
- 文件名、Markdown 和 HTML 特殊字符正确处理，无绝对本机路径或默认隐私信息
- 全部附件为用户选择的最终图片，脱敏输出不附原始工程或底图

**不做的内容**
- 不自动上传工单平台，不引入账号或云端服务

**建议代码落点**
- [main/clipboard/ui/windows/clipboard_window.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/clipboard/ui/windows/clipboard_window.py)
- [main/pin/pin_manager.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/pin/pin_manager.py)
- [main/core/save.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/save.py)

## 6. 兼容性验证与交付收尾

用真实平台证据约束功能完成状态，并确保安装包和文档与已验收范围一致。

### 混合 DPI 与多显示器截图验收及最小修复

用原生 Windows 实测确认坐标、选区与输出一致，修复可重复的具体问题。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`dpi-acceptance`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 覆盖可用环境中的 100/125/150/200% 缩放组合、负坐标副屏及显示器重排
- 验证精确尺寸、预设恢复、贴图移动和导出像素

**验收条件**
- 记录操作步骤、屏幕布局和原始输出，区分真实多屏与模拟测试
- 复现的问题有最小修复和回归，无设备的矩阵项标记未验证
- 不以静态语法或 offscreen 测试替代真实 DPI 验收

**建议代码落点**
- [main/core/platform_utils.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/platform_utils.py)
- [main/core/ui_scale.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/ui_scale.py)
- [main/capture/capture_service.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/capture_service.py)
- [main/canvas/view.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/canvas/view.py)
- [main/tests/test_dpi_awareness.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/tests/test_dpi_awareness.py)

### HDR 与特殊窗口捕获兼容性验证

确认当前采集方案的真实边界，在证据支持时做最小修复或明确回退。

- 优先级：3（场景增强，按需选做）；相对难度：高。
- 初始状态：拟议 / 0%；内部别名：`capture-compatibility`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 检查可用的 HDR/SDR、硬件加速窗口和原生窗口样例
- 记录颜色异常、黑屏、遮挡和受保护内容的边界

**验收条件**
- 记录设备与窗口类型、复现步骤、原始图片及结论，不伪造未具备硬件的结果
- 确认存在问题后才评估替代捕获路径与打包影响
- 受保护/最小化/被遮挡内容不被宣传为保证支持，也不尝试绕过保护

**不做的内容**
- 不以本节点直接承诺替换整套采集后端

**建议代码落点**
- [main/capture/capture_service.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/capture_service.py)
- [main/capture/window_finder.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/capture/window_finder.py)
- [main/core/platform_utils.py](C:/Users/27933/Desktop/versepixpin/jietuba/main/core/platform_utils.py)

### 按实际交付批次完成回归、界面和隐私验收

为新增截图能力提供真实收尾门槛，防止只有单元测试或漂亮界面就宣称完成。

- 优先级：1（高频补齐 / 质量门槛）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`release-regression`。
- 前置依赖：无硬前置；先复用当前已有能力。

**开发范围**
- 每批明确包含的功能节点和未交付范围
- 使用隔离数据执行定向/全量回归、原生深浅色与缩放截图、资源释放检查

**验收条件**
- 记录命令、退出码、通过/失败/跳过数量及产物，不复用历史通过数冒充本轮结果
- 逐项检查开始、取消、失败、保存、重开和隐私边界；高风险路径有真实交互证据
- 缺少硬件、编码器或其他外部条件时保留未验证状态；可选需求不无条件阻塞核心批次

**不做的内容**
- 不是本轮任务建档工作的完成证据；只有功能实现后才可执行验收

**建议代码落点**
- [main/tests](C:/Users/27933/Desktop/versepixpin/jietuba/main/tests)
- [run_dev.py](C:/Users/27933/Desktop/versepixpin/jietuba/run_dev.py)
- [docs/screen-assistant-phase1.md](C:/Users/27933/Desktop/versepixpin/jietuba/docs/screen-assistant-phase1.md)

### 验证安装包并对齐截图功能文档

让用户实际拿到的安装包、入口说明和 README 与已通过验收的能力一致。

- 优先级：2（后续重点）；相对难度：中。
- 初始状态：拟议 / 0%；内部别名：`package-docs`。
- 前置依赖：「按实际交付批次完成回归、界面和隐私验收」

**开发范围**
- 在每批回归后验证构建产物和所需模型/原生扩展
- 更新中英日说明中的入口、数据流、限制和未验证平台边界

**验收条件**
- 隔离目录运行安装包，实测本批新增功能及既有截图/OCR 主路径
- 文档不宣传未实现节点、未验证架构或不能保证的隐私能力
- 记录构建命令、退出码、产物及摘要；不自动上传发布或修改发布渠道

**建议代码落点**
- [build_with_ocr_onefile.py](C:/Users/27933/Desktop/versepixpin/jietuba/build_with_ocr_onefile.py)
- [versepic.spec](C:/Users/27933/Desktop/versepixpin/jietuba/versepic.spec)
- [README.md](C:/Users/27933/Desktop/versepixpin/jietuba/README.md)
- [README_zh-CN.md](C:/Users/27933/Desktop/versepixpin/jietuba/README_zh-CN.md)
- [README_JA.md](C:/Users/27933/Desktop/versepixpin/jietuba/README_JA.md)

## 跨分支关系

- 多图拼版也服务教程/报告，但只有一个主归属，避免重复计算进度。
- 用户批准的截图来源信息可贡献给 Markdown 报告；基本手填报告不需要硬依赖元数据功能。

## 提案保存时的验证记录（历史）

- `init`：exit 0，原仓库无森林，初始化成功。
- `list --json` / `todo --json`：初始均为空。
- 所有建议代码落点均检查存在；38 个任务的依赖别名引用无缺失。
- `proposal-save`：exit 0；通过模拟应用进行结构预校验并保存提案。
- `validate`：exit 0；验证的是当前正式空森林，不应拿它代替提案或功能验证。
- `export`：exit 0；生成的是正式空森林的真实视图，未伪造新节点。
- 保存后 `list --json` / `todo --json` 仍为空：确认尚未执行正式应用。
- 本轮没有功能代码改动、应用运行、回归测试、Git 提交或安装包发布。

## 正式应用记录

用户确认开始完整开发与验收后，已通过官方 CLI 执行 `proposal-apply TFP-20261009-screenshot-expansion --yes`，exit 0；`validate` 与 `export` 均 exit 0，正式查询确认 45 个节点已存在。开发验收证据另见 `docs/screenshot-expansion-progress.md`。后续状态回写仍走提案流程，不直接编辑权威数据。
