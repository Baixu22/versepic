
<p align="center"><img src="docs/images/versepic-icon.png" width="104" alt="VersePic icon"></p>

# VersePic

[English](README.md) · [简体中文](README_zh-CN.md) · [日本語](README_JA.md)

面向 Windows 的截图与剪贴板工作台。截取、标注、贴图和整理复制内容，在一个轻量界面中完成。

## 主要功能

- **截图与标注**：区域／窗口截图、滚动长截图、箭头、形状、文字与马赛克。
- **贴图参考**：将图片固定在屏幕上，支持缩放、继续标注与 OCR。
- **剪贴板历史**：检索文字、图片和文件，使用分组、标签、类型与日期筛选整理内容。
- **内容管理**：创建分组、编辑常用内容、导入与导出 CSV 文本。
- **识别与输出**：本地 PP-OCR、可配置翻译服务、GIF 录制、条码识别和 PDF 导出。
- **截图内容助手**：OCR 结果可合并断行、清理空格、撤销、翻译、网页搜索并保存到分组或文本文件；历史图片在后台建立本地文字索引，可按图中文字检索。
- **智能脱敏**：截图工具栏「更多」或历史图片右键菜单可识别手机号、邮箱与自定义关键词，逐行确认遮盖，也可拖动补画区域；复制和导出为合成后的实色遮盖图片。
- **统一界面**：中性深浅色、圆角组件、Lucide 图标和简短交互动效。

## 应用截图

以下为真实应用界面，使用隔离的演示数据，不包含个人剪贴板内容。

| 剪贴板 | 内容管理 |
| --- | --- |
| ![剪贴板](docs/images/clipboard.png) | ![管理页面](docs/images/manage.png) |

![深色管理页面](docs/images/manage-dark.png)

## 下载与使用

1. 在 [Releases](https://github.com/Baixu22/versepic/releases) 下载 Windows x64 ZIP。仓库已公开，无需登录。
2. 完整解压，运行 **versepic.exe**，保持 **models/** 与程序在同一目录。
3. 从系统托盘打开截图、剪贴板及设置；快捷键可在设置中调整。

压缩包已包含两份 OCR 模型，无需安装 Python。当前提供 x64 版本；ARM64 属于源码构建目标，本次未提供经过验证的 ARM64 安装包。程序未签名。应用内的更新查询读取公开的 Releases API，无需登录。

## 数据与兼容性

剪贴板内容与 OCR 在本机处理。翻译会将选定文字发送至你配置的服务。为兼容已有数据，暂时保留旧版设置／数据目录标识，品牌改名不会清空历史。CSV 导出针对已保存文本，不等同于完整图片或数据库备份。

打开剪贴板历史后会逐张补齐旧图片的文字索引，新复制的图片也会在后台识别；底栏显示索引进度状态，首次使用时搜索结果会逐步补齐。索引与历史记录保存在同一个本地数据库，删除历史会一并删除对应索引。图片右键「文字识别」可打开识别结果并定位搜索词。「网页搜索」仅在点击时把当前选中文字（未选中时为全文）交给浏览器中的 Bing。智能脱敏按整行遮盖匹配项，支持手动补画，输出前可检查预览；原始历史图片不会被覆盖。

## 开发与打包

源码以 Windows、Python 3.11 为目标；本次本地包使用 Python 3.12 构建。请为当前架构安装匹配的原生扩展。

```powershell
py -3.11 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python main/main_app.py
.venv/Scripts/python -m pytest main/tests -q
.venv/Scripts/python build_with_ocr_onefile.py
```

依赖中的原生模块包括 pyclipboard、longstitch、gifrecorder、ppocr_rust；Rust 源码位于 rust_libs/，模型位于 models/。源码构建原生扩展的方法见 [.github/workflows/build.yml](.github/workflows/build.yml)。产物为 **dist/versepic.exe** 与 **dist/models/**，发布时必须一起打包。

## 致谢与许可

基于 [Jietuba](https://github.com/1003129155/jietuba) 开发，保留原作者版权及 [MIT 许可](LICENSE)。界面图标使用 [Lucide](https://lucide.dev)，附带其[许可](svg/lucide/LICENSE)。VersePic 应用图标由指定图像 API 生成并适配为 PNG／ICO。

---

## 目录结构总览

<details>
<summary>展开目录结构</summary>

```text
# 项目根目录
├── README.md / README_zh-CN.md / README_JA.md          # 英文、中文、日文说明文档
├── pyproject.toml                                      # Python 项目元数据与依赖声明
├── requirements.txt                                   # 运行依赖
├── requirements-dev.txt                               # 测试与构建依赖
├── build_with_ocr_onefile.py                           # PyInstaller 单文件构建脚本
│
├── main/                    # Python 主程序
│   ├── main_app.py          # 应用入口，系统托盘、全局快捷键、生命周期管理
│   ├── compile_translations.py  # 翻译文件编译工具（.xml → .qm）
│   ├── scripts/             # 辅助脚本 — 翻译提供商对比
│   │
│   ├── barcode/             # 扫码模块 — 二维码/条形码识别（zxing-cpp）
│   ├── canvas/              # 画布模块 — 图形编辑核心
│   ├── capture/             # 截图捕获模块 — 屏幕截图与窗口识别
│   ├── clipboard/           # 剪贴板管理模块 — 历史记录、分组/快速启动、导入导出、搜索
│   ├── core/                # 核心基础模块 — 启动引导、日志、资源、主题、国际化、快捷键
│   ├── gif/                 # GIF录制模块 — 屏幕录制、编辑、回放、导出
│   ├── ocr/                 # OCR模块 — PP-OCR 文字识别
│   ├── pin/                 # 钉图模块 — 截图置顶、编辑、OCR、翻译
│   ├── settings/            # 设置模块 — 统一配置管理
│   ├── stitch/              # 长截图拼接模块 — 滚动截图、自动拼接
│   ├── tools/               # 绘图工具模块 — 笔、矩形、箭头、文字、马赛克等
│   ├── translation/         # 翻译模块 — 多提供商翻译服务
│   ├── translations/        # 语言资源 — 中文/英文/日文/韩文
│   ├── ui/                  # 用户界面模块 — 通用UI组件库
│   └── tests/               # 测试模块 — 单元测试与集成测试
│
├── rust_libs/               # Rust 库源码（可自行编译）
│   ├── gifrecorder/         # GIF/视频合成编码器源码
│   ├── longstitch/          # 长截图拼接算法源码
│   ├── pyclipboard/         # 剪贴板底层操作源码
│   └── ppocr_rust/          # PP-OCR (PaddleOCR) ONNX 识别引擎源码
│
├── models/                  # PP-OCR ONNX 模型文件（OCR 必需）
│   ├── PP-OCRv6_det_small.onnx   # 文本检测模型 (DBNet)
│   └── PP-OCRv6_rec_small.onnx   # 文本识别模型 (CRNN/CTC)
│
└── svg/                     # SVG 图标资源
```

</details>



## 模块详细说明

### barcode/ — 扫码模块

识别截图选区里的二维码和条形码。结果窗口左侧在截图上标出每个码的位置，右侧按序号列出内容。

<details>
<summary>展开目录结构</summary>

```text
barcode/
├── __init__.py
├── reader.py                # read_codes / DecodedCode — 基于 zxing-cpp 解码，按阅读顺序给出内容、格式与轮廓
└── result_window.py         # BarcodeResultWindow — 扫码结果窗口，截图与结果列表按序号对应
```

</details>

**核心功能：**
- 支持 QR Code、Data Matrix、Aztec、PDF417 及 Code 128、EAN/UPC 等常见一维码
- 一次识别选区内的多个码，悬停截图或列表中的任一项，两边同时高亮
- 内容一键复制；http(s) 链接可直接在浏览器打开

---

### canvas/ — 画布模块

图形编辑画布系统，提供场景管理、视图渲染、图形项选择和撤销/重做功能。

<details>
<summary>展开目录结构</summary>

```text
canvas/
├── __init__.py
├── scene.py                 # CanvasScene — 画布场景，继承 QGraphicsScene
├── view.py                  # CanvasView — 画布视图，继承 QGraphicsView，负责渲染和交互
├── selection_model.py       # SelectionModel — 管理被选中的图形项，支持多选
├── undo.py                  # CommandUndoStack — 撤销/重做栈，支持添加、删除、批量删除、编辑命令
├── smart_edit_controller.py # SmartEditController — 智能编辑控制器，处理选择与编辑模式切换
├── smart_selection_anim.py  # SmartSelectionAnimator — 智能选区换窗口时的矩形补间
├── handle_editor.py         # LayerEditor / EditHandle — 图层编辑器，提供控制点拖拽编辑
├── gestures.py              # 鼠标手势状态机 — 文字边缘拖动、拉选区、挂起的单击编辑
├── handle_overlay.py        # HandleOverlay — 编辑控制点的独立合成层，避免整场景重绘
└── items/                   # 绘制图形项
    ├── __init__.py
    ├── drawing_items.py     # StrokeItem / RectItem / EllipseItem / NumberItem — 共用 DrawingItemMixin 的绘制项
    ├── background_item.py   # BackgroundItem — 选区背景底图
    ├── mosaic_item.py       # MosaicItem — 马赛克图形项
    ├── spotlight_item.py    # SpotlightItem / SpotlightCurtain — 聚光灯的孔与共用幕布
    ├── magnify_item.py      # MagnifyCalloutItem — 可导出的原图像素局部放大框
    ├── callout_link.py      # callout_link — 箭头与文字气泡组合标注的关联与几何同步
    ├── image_stamp_item.py  # ImageStampItem — 插入的位图（等比缩放、可撤销、随工程保存）
    ├── selection_item.py    # SelectionItem — 选中项的边界显示框
    ├── arrow_item.py        # ArrowItem — 箭头图元，九种样式的箭杆/端头/描边几何
    └── text_item.py         # TextItem — 文字图元，描边/阴影/背景色块与三态交互框
```

</details>


**核心功能：**
- 基于 Qt Graphics View Framework 的画布系统
- 支持自由绘制、矩形、椭圆、箭头、文字、编号等图形项
- 完整的撤销/重做机制（基于 QUndoStack）
- 智能编辑控制器实现选择与绘制模式无缝切换
- 控制点编辑器支持图形变换

---

### capture/ — 截图捕获模块

屏幕截图和窗口智能识别的核心服务。

<details>
<summary>展开目录结构</summary>

```text
capture/
├── __init__.py
├── capture_service.py       # CaptureService — 截图服务，屏幕截图核心逻辑
├── quick_capture.py         # 快捷截取的屏幕、窗口、上次区域目标校验
├── region_presets.py        # 命名区域与显示器布局、DPI 校验
├── cursor_capture.py        # Windows 真实指针快照与热点合成
├── multi_region.py          # 同帧多区域顺序与撤销/重做
├── uia_element_finder.py    # 后台 UI Automation 元素检测与选区快照缓存
└── window_finder.py         # WindowFinder — 窗口查找器，智能选择窗口，识别光标下的窗口
```

</details>

**核心功能：**
- 全屏截图和区域截图
- 智能窗口识别与选择（自动排除窗口阴影）
- 光标位置窗口检测

---

### clipboard/ — 剪贴板管理模块

类似 Ditto 的剪贴板历史管理系统，现已拆分为 controllers、core、services、ui 四层结构，支持文本、图片、HTML、文件等类型。
不仅能保存截图历史，还提供独立的三栏管理窗口用于维护分组与内容，并可从历史记录生成钉图。

<details>
<summary>展开目录结构</summary>

```text
clipboard/
├── __init__.py
├── controllers/             # 控制层 — 历史加载、粘贴流程、右键菜单、选择状态
│   ├── clipboard_controller.py   # ClipboardController — 历史加载、粘贴和菜单逻辑
│   ├── selection_manager.py      # SelectionManager — 列表选择状态管理
│   ├── context_menu_controller.py  # ContextMenuController — 右键菜单数据与行为组装
│   ├── foreground_tracker.py    # ForegroundWindowTracker — 记住粘贴目标窗口
│   ├── paste_keystroke.py       # 把焦点还给目标窗口后发送 Ctrl+V
│   └── __init__.py
├── core/                    # 数据层 — pyclipboard 封装、数据模型、分组类型
│   ├── manager.py           # ClipboardManager — 数据存储、监听、粘贴 API
│   ├── models.py            # ClipboardItem / Group — 剪贴板数据模型
│   ├── enums.py             # GroupType — 分组类型定义
│   ├── text_transform.py    # 纯文本加工函数 — 供「特殊粘贴」调用，全部无副作用
│   ├── tag_store.py         # TagStore — 标签定义与条目-标签映射存储
│   ├── image_text.py        # 本地图片文字索引、历史搜索与串行后台 OCR
│   └── __init__.py
├── services/                # 服务层 — 文件 payload、分组规则、导入导出、保存逻辑
│   ├── file_payload_service.py   # file 类型 JSON payload 与旧格式兼容
│   ├── group_service.py          # 分组图标、命名与删除确认辅助
│   ├── import_export_service.py  # 文本条目 CSV 导入/导出
│   └── manage_dialog_service.py  # 管理窗口保存逻辑
├── ui/
│   ├── layout_scale.py           # 管理窗口共用尺寸常量
│   ├── dialogs/
│   │   └── manage_dialog.py      # 三栏管理窗口：分组、内容、导入导出
│   ├── forms/
│   │   ├── group_form.py
│   │   ├── text_content_form.py
│   │   ├── file_content_form.py
│   │   ├── import_export_form.py
│   │   └── group_icon_picker.py
│   ├── menus/
│   │   ├── action_menu.py
│   │   ├── group_context_menu.py
│   │   └── item_context_menu.py
│   ├── mixins/
│   │   └── frameless_mixin.py
│   ├── panels/
│   │   └── setting_panel.py
│   ├── resources/
│   │   └── emoji_data.py
│   ├── theme/
│   │   ├── themes.py
│   │   └── theme_styles.py
│   ├── widgets/
│   │   ├── draggable_list_widget.py
│   │   ├── manage_list_delegate.py
│   │   ├── group_bar.py
│   │   ├── item_delegate.py
│   │   ├── item_widget.py
│   │   └── preview_popup.py
│   └── windows/
│       ├── clipboard_window.py   # 历史窗口、搜索、预览与快捷粘贴
│       └── pin_window.py         # 从历史条目创建钉图
```

</details>

**核心功能：**
- 监听系统剪贴板变化，自动保存历史记录
- 支持文本、图片、HTML、文件等多种格式
- 支持通用分组、快速启动分组、收藏与搜索
- 独立三栏管理窗口，可编辑分组、文本内容和文件内容
- 文本条目支持 CSV 导入/导出
- 多主题 UI（亮色/暗色等）
- 快捷键快速粘贴历史内容
- 预览弹窗支持大图/长文查看

---

### core/ — 核心基础模块

提供日志、资源加载、主题管理、国际化、快捷键等基础设施。

<details>
<summary>展开目录结构</summary>

```text
core/
├── __init__.py
├── bootstrap.py             # PreloadManager — 启动引导，环境初始化、DPI感知、单实例控制、链式预加载
├── single_instance.py       # SingleInstanceGuard — 命名互斥体单实例守卫，原子性保证同时只有一个实例
├── logger.py                # Logger — 文件+控制台日志系统，支持多级别 (debug/info/warning/error/exception)
├── crash_handler.py         # install_crash_hooks() — 全局异常和线程异常捕获
├── resource_manager.py      # ResourceManager — SVG/图片等资源加载管理
├── theme.py                 # ThemeManager — 应用级主题颜色管理
├── ui_scale.py              # UIScaleManager — 工具栏/面板/弹层共用的缩放比例
├── i18n.py                  # I18nManager / XmlTranslator / tr() — 国际化管理，多语言支持
├── shortcut_manager.py      # HotkeySystem / ShortcutManager — 全局热键和应用内快捷键管理
├── last_capture_region.py   # 进程内存的"上次截图区域"，供恢复选区快捷键使用
├── save.py                  # SaveService — 文件保存服务（自动命名、路径管理、高质量 PDF 输出）
├── searchable_pdf.py       # 基于最终像素的可搜索PDF与逐页回退报告
├── image_output.py          # 不可变图片导出配置与安全命名模板
├── image_layout.py          # 受限内存的图片拼版与一图一页 PDF 渲染
├── image_compare.py         # 有界且感知透明度的像素差异计算
├── image_document.py        # 非破坏性文件图片几何与源路径保护
├── editable_project.py      # 有界可编辑图片工程归档与标注编解码
├── export.py                # ExportService — 图像导出服务
├── number_legend.py         # 编号说明步骤列表的排版与导出（成图下方/右侧）
├── watermark.py             # 导出水印（TF-0038）：文字/图片、位置/边距/透明度，默认关闭
├── annotation_presets.py    # 常用标注样式预设（TF-0039）：按工具保存命名样式并应用到新建默认值
├── capture_metadata.py      # 截图元信息（TF-0040）：来源/时间/备注，默认全关
├── markdown_report.py       # Markdown 问题报告（TF-0041）：相对路径附件、转义与顺序
├── packaged_self_check.py   # 打包自检（TF-0045）：在安装包内跑本批核心链路
├── clipboard_utils.py       # copy_image_to_clipboard() — 图像复制到系统剪贴板
├── capture_privacy.py       # 单次截图和派生窗口的内存隐私策略
├── platform_utils.py        # DPI感知设置、AppUserModelID、进程管理等 Windows API 工具
├── qt_utils.py              # safe_disconnect() — Qt 信号安全断开工具
├── log_translations/        # 各模块日志文本翻译辅助
├── constants.py             # 全局常量定义（字体、路径等）
├── update_checker.py        # GitHub 最新版本异步查询与版本比较
└── ui_theme.py              # UIThemeManager — 应用窗口与原生 Qt 控件的明暗外观（截图配色仍在 theme.py）
```

</details>

**核心功能：**
- 统一的日志系统，支持文件输出和控制台输出
- 全局崩溃处理，自动捕获未处理异常
- SVG/图片资源统一加载
- 应用级亮色/暗色主题管理
- XML 格式的多语言国际化系统（中/英/日）
- 全局热键系统（基于 Windows API）和应用内快捷键管理
- 文件保存/导出服务（含高质量 PDF 输出）

---

### gif/ — GIF 录制模块

屏幕录制、编辑、回放和导出为 GIF/视频。

<details>
<summary>展开目录结构</summary>

```text
gif/
├── __init__.py
├── record_window.py         # GifRecordWindow / AppState — 主控制窗口，状态机协调器（管理3层窗口）
├── overlay.py               # CaptureOverlay / OverlayMode — 捕获覆盖层，选区调整界面
├── drawing_view.py          # GifDrawingView / GifDrawingScene — 录制中绘图编辑视图
├── drawing_toolbar.py       # GifDrawingToolbar — 绘制工具栏
├── record_toolbar.py        # RecordToolbar — 录制控制工具栏（开始/暂停/停止）
├── frame_recorder.py        # FrameRecorder / FrameData / CursorSnapshot — 帧录制器，采样屏幕帧和光标
├── playback_engine.py       # PlaybackEngine / PlayState — 回放引擎，帧播放和预览
├── playback_controller.py   # PlaybackController — 回放控制器，管理回放UI和导出
├── playback_toolbar.py      # PlaybackToolbar / RangeSlider — 回放工具栏，进度条、速度控制
├── composer.py              # _ComposeWorker / ComposerProgressDialog — GIF合成，将帧合成为GIF/视频
├── export_dialog.py         # GifExportDialog — GIF导出尺寸和帧率控制
├── mp4_export.py            # 无声H.264/MP4逐帧导出
├── mp4_diagnostics.py       # 安装包显式合成素材导出自检
├── cursor_overlay.py        # CursorOverlay — 光标渲染和点击动画
└── _widgets.py              # ClickMenuButton / svg_icon() — 自定义小部件
```

</details>

**核心功能：**
- 以状态机模式管理录制流程（选区 → 录制 → 回放 → 导出）
- 三层窗口架构：覆盖层（选区）、绘制层（标注）、工具栏层
- 帧采样录制，支持光标捕获和点击动画
- 回放预览，支持范围裁剪、速度调节
- 导出为 GIF 或视频格式（调用 Rust 库 gifrecorder）

---

### ocr/ — OCR 文字识别模块

支持 PP-OCR 引擎的文字识别管理。

<details>
<summary>展开目录结构</summary>

```text
ocr/
├── __init__.py
└── ocr_manager.py           # OCRManager — 基于 ppocr_rust (PP-OCR) 的文字识别
```

</details>

**核心功能：**
- 自动检测引擎与模型可用性
- 基于 ppocr_rust 引擎（纯 Rust + ONNX Runtime，PP-OCR det + rec），推理在原生线程运行不阻塞 UI
- 支持中/英/日文识别
- 单例模式管理，统一的识别接口，返回文字和位置信息

---

### pin/ — 钉图模块

将截图固定在屏幕上，支持编辑、缩放、OCR识别、翻译等。
<details>
<summary>展开目录结构</summary>

```text

pin/
├── __init__.py
├── pin_window.py            # PinWindow — 钉图主窗口，可拖动、缩放、编辑的置顶窗口
├── pin_canvas_view.py       # PinCanvasView — 钉图画布视图（唯一内容渲染者）
├── pin_canvas.py            # 钉图画布对象
├── pin_manager.py           # PinManager — 管理所有钉图窗口（单例）
├── workspace.py            # 有界可编辑贴图工作区文件与安全恢复
├── workspace_dialog.py     # 主动选择贴图、保存、恢复与回收站删除入口
├── pin_toolbar.py           # PinToolbar — 钉图工具栏
├── pin_controls.py          # PinControlButtons — 控制按钮（关闭、编辑、复制等）
├── pin_context_menu.py      # PinContextMenu — 右键菜单
├── pin_border_overlay.py    # PinBorderOverlay — 边框效果覆盖层
├── pin_ocr_manager.py       # PinOCRManager / _OCRThread — 钉图OCR管理（异步识别）
├── pin_shortcut.py          # PinShortcutController — 快捷键控制（普通模式/编辑模式）
├── pin_thumbnail.py         # PinThumbnailMode — 缩略图模式
├── pin_translation.py       # PinTranslationHelper — 翻译助手
├── pin_image_transform.py   # PinImageTransform — 图像变换（旋转、翻转等）
└── ocr_text_layer.py        # OCRTextLayer / OCRTextItem — OCR文字层显示
```

</details>

**核心功能：**
- 截图结果钉在屏幕最前端，支持拖拽移动和滚轮缩放
- 钉图上可直接进行绘制编辑
- 集成 OCR 识别，显示可选中文字层
- 集成翻译功能，可直接翻译钉图中的文字
- 快捷键支持普通模式和编辑模式

---

### settings/ — 设置模块

统一的配置管理系统。

<details>
<summary>展开目录结构</summary>

```text
settings/
├── __init__.py
├── color_formats.py         # 放大镜颜色格式模板：渲染、读取、保存
└── tool_settings.py         # ToolSettingsManager / ToolSettings — 管理工具颜色、大小、热键等配置
```

</details>

**核心功能：**
- 单例模式的配置管理器
- 管理各绘图工具的颜色、线宽、字体大小等参数
- 持久化存储到 QSettings

---

### stitch/ — 长截图拼接模块

滚动截图和自动拼接功能。
<details>
<summary>展开目录结构</summary>

```text

stitch/
├── __init__.py
├── jietuba_long_stitch_unified.py   # 长截图拼接接口（调用 Rust longstitch）
├── scroll_window.py                 # ScrollCaptureWindow — 滚动截图窗口
├── session.py              # 有界长截图检查点与可撤销的接缝修正
├── adjustment_dialog.py    # 接缝及匹配忽略区可视化复核窗口
├── auto_scroll.py          # 可取消、有上限的前台目标定向滚动
├── auto_scroll_dialog.py   # 自动滚动范围设置与显式启动对话框
└── scroll_toolbar.py                # 滚动截图工具栏
```

</details>

**核心功能：**
- 滚动页面并截图，支持横向和竖向
- 基于图像匹配的智能拼接算法（查找重叠区域）
- 统一的长截图接口（调用 Rust 库 longstitch 加速）

---

### tools/ — 绘图工具模块

提供各种绘图工具的实现。

<details>
<summary>展开目录结构</summary>

```text
tools/
├── __init__.py
├── base.py                  # Tool / ToolContext — 工具抽象基类和工具上下文
├── controller.py            # ToolController — 工具控制器，管理工具切换和状态
├── action.py                # ActionTools — 动作工具（复制、保存、取消等）
├── pen.py                   # PenTool — 自由绘制笔工具
├── rect.py                  # RectTool — 矩形工具（实心/空心）
├── ellipse.py               # EllipseTool — 椭圆工具
├── arrow.py                 # ArrowTool — 箭头工具
├── callout.py               # CalloutTool — 箭头 + 文字气泡组合标注
├── text.py                  # TextTool — 文字工具
├── number.py                # NumberTool — 数字编号工具（自动递增）
├── highlighter.py           # HighlighterTool — 荧光笔工具
├── mosaic.py                # MosaicTool — 马赛克工具
├── spotlight.py             # SpotlightTool — 聚光灯工具（压暗框外区域）
├── magnify.py               # MagnifyTool — 把原图像素的局部放大框放进成图
├── cursor.py                # CursorTool — 光标/选择工具
├── eraser.py                # EraserTool — 橡皮擦工具
└── cursor_manager.py        # CursorManager — 光标样式管理器
```

</details>

**核心功能：**
- 统一的工具基类架构（Tool → 各具体工具）
- 绘图工具：笔、矩形、椭圆、箭头、文字、数字、荧光笔、马赛克、光标、橡皮擦等
- 工具控制器负责工具切换、鼠标事件分发
- 工具上下文（ToolContext）提供场景、视图、设置等依赖注入

---

### translation/ — 翻译模块

多提供商翻译服务，支持 DeepL / Google / Azure / Amazon 等提供商。

<details>
<summary>展开目录结构</summary>

```text
translation/
├── __init__.py
├── provider.py              # TranslationProvider / ProviderMetadata — 提供商抽象契约
├── registry.py              # ProviderRegistry — 提供商注册表与工厂
├── service.py               # TranslationService — 提供商选择与翻译编排
├── models.py                # TranslationRequest / TranslationResult — 与提供商无关的请求/结果模型
├── worker.py                # TranslationWorker — 所有提供商共用的 Qt 工作线程
├── providers/               # 各翻译提供商实现
│   ├── deepl.py             # DeepL
│   ├── google.py            # Google
│   ├── azure.py             # Azure
│   ├── amazon.py            # Amazon
│   ├── baidu.py             # Baidu
│   ├── custom_llm.py        # 自定义 OpenAI 兼容服务（Ollama、LM Studio 等）
│   ├── deepseek.py          # DeepSeek (LLM)
│   └── openai_compatible.py # OpenAI 兼容接口基类
├── smart_translation_controller.py # SmartTranslationController — 一键选中文字探测与翻译弹窗路由
├── translation_popup.py     # TranslationPopup — 紧凑翻译弹窗（选中文字/手动输入两种模式）
├── deepl_service.py         # DeepLService / TranslationThread — 旧版 DeepL API 异步翻译
├── languages.py             # SupportedLanguages — 支持的语言列表与语言代码
├── translation_manager.py   # TranslationManager — 翻译窗口管理器（单例）
├── translation_dialog.py    # TranslationDialog / TranslationLoadingDialog — 翻译结果显示窗口
└── ui/
    ├── __init__.py
    ├── dialog.py            # 翻译对话框UI组件
    └── widgets.py           # 翻译相关小部件
```

</details>

**核心功能：**
- 可插拔的多提供商架构（DeepL / Google / Azure / Amazon），注册表统一管理
- 一键快捷键：自动探测选中文字并路由到翻译弹窗
- 紧凑翻译弹窗，支持选中文字与手动输入两种模式
- 异步翻译，不阻塞 UI
- 翻译结果支持复制

---

### translations/ — 语言资源

多语言翻译文件存放目录。

<details>
<summary>展开目录结构</summary>

```text
translations/
├── app_zh.xml / app_en.xml  # 中文/英文翻译源文件
├── app_ja.xml / app_ko.xml  # 日文/韩文翻译源文件
└── app_*.xml.qm             # 编译后的 Qt 二进制文件（app_zh.xml.qm 等）
```

</details>

**说明：** `.xml` 为可编辑的翻译源文件，`*.xml.qm` 为 Qt 运行时加载的编译文件。修改翻译后需运行 `compile_translations.py` 重新编译。

---

### ui/ — 用户界面模块

通用 UI 组件库，为各模块提供统一的界面元素。

<details>
<summary>展开目录结构</summary>

```text
ui/
├── __init__.py
├── toolbar.py               # Toolbar / _DragHandle — 可拖动工具栏基类
├── toolbar_layout.py        # 截图工具栏按钮排布（顺序 / 显示方式）的归一化与读写
├── toolbar_layout_dialog.py # ToolbarLayoutDialog — 截图工具栏排布对话框
├── reorderable_rows.py      # DragGrip / DraggableRow / ReorderableRowList — 可拖动重排的行列表
├── tray_menu.py             # TrayMenu — 系统托盘菜单
├── screenshot_window.py     # ScreenshotWindow — 截图主窗口（全屏覆盖、选区绘制）
├── capture_countdown.py     # CaptureCountdown — 不抢焦点、可取消的延时截图浮层
├── image_layout_dialog.py   # 图片收集、排序、预览与异步导出
├── image_compare.py         # 只读并排、滑杆和差异对比窗口
├── image_editor.py          # 复用贴图画布和标注工具栏的文件图片编辑器
├── multi_region_dialog.py   # 全桌面多区域选择与原子收集
├── dialogs.py               # StandardDialog / 对话框函数集 — 确认、警告、信息、错误对话框
├── component_gallery.py     # 共用 Qt 组件交互展示页；对齐与复用约定见 docs/qt-components.md
├── magnifier.py             # MagnifierOverlay — 放大镜覆盖层（像素级取色）
├── color_picker_dialog.py   # ColorPickerDialog — 自定义HSV颜色选择器
├── color_picker_button.py   # ColorPickerButton — 颜色选择按钮
├── hotkey_edit.py           # HotkeyEdit — 全局快捷键编辑框
├── inapp_key_edit.py        # InAppKeyEdit — 应用内快捷键编辑框
├── key_chip.py              # KeyChipLineEdit / StatusIcon — 快捷键按键块与状态图标
├── mask_overlay.py          # 遮罩覆盖层
├── selection_overlay.py     # SelectionOverlayWidget — 选区装饰浮层，压在遮罩之上
├── base_settings_panel.py   # BaseSettingsPanel / StepperWidget — 设置面板基类
├── paint_settings_panel.py  # PaintSettingsPanel — 画笔设置面板
├── shape_settings_panel.py  # ShapeSettingsPanel — 形状设置面板
├── text_settings_panel.py   # TextSettingsPanel — 文字设置面板
├── arrow_settings_panel.py  # ArrowSettingsPanel — 箭头设置面板
├── number_settings_panel.py # 数字工具设置面板
├── mosaic_settings_panel.py # 马赛克工具设置面板
├── apple_style.py           # Apple 风格设计 token 与 QSS 助手（剪切板与管理窗口共用）
├── motion.py                # 动效助手 — 窗口淡入淡出/上浮与悬停动画
│
├── glass.py / glyphs.py / outline_icons.py  # Native glass and Lucide SVG rendering
├── fluent_lite/             # Fluent 风格轻量组件库
│   ├── icon_label.py        # 图标与文字的共用对齐规则
│   ├── button_base.py / popups.py / primitives.py  # Shared animated controls
│   ├── buttons.py / cards.py / icons.py / inputs.py  # 按钮、卡片、图标、输入框
│   ├── labels.py / navigation.py / segmented.py      # 标签、导航、分段控件
│   ├── switch.py / theme.py / titlebar.py            # 开关、主题、标题栏
│   ├── frameless.py         # 无边框窗口
│   └── text_context_menu.py # 文本右键菜单
│
├── settings_ui/             # 应用设置对话框
│   ├── __init__.py
│   ├── dialog.py            # SettingsDialog — 主设置对话框（选项卡式）
│   ├── components.py        # SettingCardGroup / ToggleSwitch — 设置组件库
│   ├── page_appearance.py   # 外观设置页（主题、语言等）
│   ├── page_capture.py      # 截图设置页
├── watermark_controls.py  # Export watermark settings group (TF-0038)
├── metadata_controls.py   # Capture metadata settings group (TF-0040)
├── markdown_report_dialog.py # Markdown 报告对话框（TF-0041）
├── preset_dialog.py       # Annotation style presets dialog (TF-0039)
│   ├── color_format_dialog.py # ColorFormatDialog — 放大镜颜色格式管理窗口
│   ├── page_clipboard.py    # 剪贴板设置页
│   ├── page_hotkey.py       # 快捷键设置页
│   ├── page_translation.py  # 翻译设置页
│   ├── provider_fields.py   # 服务商字段的读写（按声明）
│   ├── page_log.py          # 日志设置页
│   ├── page_developer.py    # 开发者设置页
│   ├── page_misc.py         # 杂项设置页
│   ├── page_about.py        # 关于页面
│   └── mock_config.py       # MockConfig — 测试用模拟配置
│
├── welcome/                 # 首次启动欢迎向导
│   ├── __init__.py
│   ├── wizard.py            # WelcomeWizard — 欢迎向导主窗口（多页滑动）
│   ├── base_page.py         # BasePage — 向导页面基类
│   ├── page1_welcome.py     # 欢迎页
│   ├── page2_screenshot.py  # 截图快捷键设置页
│   ├── page3_clipboard.py   # 剪贴板快捷键设置页
│   ├── page5_translation.py # 翻译功能说明页
│   ├── page6_finish.py      # 完成页
│   └── page_hotkeys.py      # 全局快捷键页 — 六个键同属一个冲突域，集中设置并统一判重
│
└── selection_info/          # 选区信息UI
    ├── __init__.py
    ├── controller.py        # 选区信息控制器
    ├── panel.py             # 选区信息面板（尺寸、坐标）
    ├── geometry_dialog.py   # 选区坐标、尺寸与纵横比编辑
    ├── hook_manager.py      # 钩子管理
    ├── border_shadow.py     # 选区边框阴影效果
    ├── lock_ratio.py        # 锁定宽高比功能
    └── rounded_corners.py   # 圆角截图功能
```

</details>

**核心功能：**
- 可拖动工具栏基类，所有工具栏继承自此
- 全屏截图窗口，处理选区绘制和交互
- 放大镜、颜色选择器等精细UI组件
- Fluent 风格轻量组件库（按钮、卡片、导航、分段、开关等）
- 完整的应用设置对话框（外观/截图/热键/翻译等多个页面）
- 首次启动欢迎向导（6页引导流程）
- 选区信息面板（尺寸显示、宽高比锁定、圆角等）

---

### tests/ — 测试模块

单元测试和集成测试。

<details>
<summary>展开目录结构</summary>

```text
tests/
├── conftest.py              # pytest 配置和公共 fixture
├── pytest.ini               # pytest 运行配置
├── run_tests.py             # 测试运行脚本
├── test_drawing_tools.py    # 绘图工具测试（笔/矩形/箭头/文字/数字/荧光笔）
├── test_mosaic_tool.py      # 马赛克工具测试
├── test_spotlight.py        # 聚光灯测试
├── test_magnify_callout.py  # 局部放大框测试
├── test_text_callout.py     # 组合标注（箭头 + 文字气泡）测试
├── test_functional_handles.py # 控制点编辑测试
├── test_capture_service.py  # 截图服务测试
├── test_clipboard_api.py    # 剪贴板公共 API 测试
├── test_clipboard_manage_dialog.py # 剪贴板管理窗口测试
├── test_frame_recorder.py   # GIF 帧录制测试
├── test_playback_engine.py  # GIF 回放引擎测试
├── test_ocr_text_layer.py   # OCR 文字层测试
├── test_pin_window_zoom.py  # 钉图缩放测试
├── test_smart_translation.py # 智能翻译测试
├── test_translation_architecture.py # 翻译提供商架构测试
├── test_stitch_dedup.py     # 长截图拼接去重测试
├── test_settings_dialog_state.py # 设置对话框状态测试
├── test_welcome_translation.py # 欢迎向导翻译页测试
└── …（其余模块单元测试与集成测试，共 70 多个文件）
```

</details>

---

当前截图拓展开发包含 GIF 导出尺寸/帧率控制，需要从本工作区重建并安装 `rust_libs/gifrecorder`；公开的 j-gif 0.3.1 二进制不具备新增接口。构建方法见原生模块 README。这是本地开发状态，不代表安装包已验证或发布。

录制回放 → 保存 → MP4 可导出无声 H.264 视频，保留当前裁剪、速度和鼠标效果；奇数尺寸右侧/底部补边，不拉伸，不采集音频。可显式运行 `versepic.exe --verify-mp4-export <空输出目录>` 做包内合成素材编码自检，绕过正常启动，只在指定目录写入测试媒体与结果。构建包保留 PyAV 许可证；FFmpeg/x264 分发许可检查及完整安装包验收仍是发布前门槛。

智能脱敏增加可选的身份证日期/校验码、银行卡 Luhn 规则和有限的 OCR O/I/l 纠错。命名预设只保存规则开关，不保存关键词、OCR 文字或图像。匹配只是供人工复核的候选；校验通过不代表身份或账户真实，OCR 错字、分行可能漏报。PNG/JPEG/PDF 按预览原始尺寸将黑色遮盖扁平化到新文件，拒绝覆盖任何已有文件。

本地源码已接通托盘“单次敏感截图”：策略随贴图和脱敏窗口传递，阻止持久化、录制、文字和翻译出口，仅允许主动带标记复制图片。需要本地私密剪贴板协议。因隔离窗口站创建被拒绝，真实 Windows 监听零留存验收仍未完成；原生界面检查使用系统复制替身。此开发中功能不能视为已验证的隐私保证，也无法擦除其他软件已读取的内容、系统换页或崩溃转储。

历史图片右键 → 图片文字索引，可查看等待/识别中/失败/已排除/已索引/无文字状态，并重试、重新识别、排除或恢复。排除会移除当前 OCR 搜索元数据，重启后仍保持排除，直到主动恢复；原图和粘贴格式不变。失败项不再每次重启自动重试。任务令牌阻止排除、删除、换图或数据库迁移后的迟到结果写回；不承诺安全擦除 SQLite 页、数据库备份或此前复制的文字。

文字识别 → 复核表格，使用原始 OCR 文字框（不是纯文本编辑框的修改）将规整、单元格分离的截图重建为可编辑表格，保留原图对照。支持单元格、多行文字和行列校正、带引号转义的 TSV 复制及 Markdown 导出。限制200行、32列、4000格、50万字符，预览图最多3200万像素。合并单元格、折行或多格合并成一条OCR需人工校正。TSV默认给公式前缀加单引号；表格软件导入设置仍可能转换日期、前导零或嵌入控制字符。不增加云端上传或自动入历史。

多图 PDF 提供图片型（默认）与重新本地 OCR 的可搜索型选择，支持0/90/180/270度图像旋转。可搜索路径只识别旋转并以白底扁平化后的实际像素，不接受历史缓存或脱敏前OCR；文字按坐标放在不透明原图下，外观不变但可搜索/提取。空白、OCR失败和缺少字形会回退图片型并在逐页报告中说明；错字和复杂阅读顺序仍需复核。文字识别窗口也可为当前图像打开PDF输出，不把纯文本编辑框内容当作隐藏文字层。

截图、钉图和文件编辑画布可以把选中的源区域做成可导出的局部放大框。放大内容只取原图像素（最近邻），不含其他标注、放大框自身或编辑手柄；移动放大框不会改取样区域。这与取色用的屏幕放大镜不是同一功能。截图工具栏默认放在「…」里，钉图和文件编辑工具栏在绘制行显示。不含该图元的旧工程仍可打开；含该图元的新工程在旧版本中会报不支持的标注类型，而不会变成普通矩形。

截图、钉图和文件编辑画布可以一次拖出「箭头 + 文字气泡」的组合标注：从气泡要放的位置拖到要指的位置，松手即输入说明；文字为空并在别处点击，整条标注作废。气泡移动或文字变长时，箭尾重新落到气泡边缘，尖端仍指向原目标；删除、批量删除和撤销把两半当一个整体，单独的箭头与文字行为不变。截图工具栏默认放在「…」里，钉图和文件编辑工具栏在绘制行显示。工程重新打开后箭头和气泡仍按保存的坐标画在原处，只是不再联动。

编号工具现在可以给每个编号填一句说明（选中编号后在序号面板的输入框里写）。导出时可以选择把说明排成步骤列表放在成图下方或右侧：列表按编号顺序排列，编号和说明始终绑定，删除、撤销、重排编号都不会错配；长说明按像素宽度自动折行，中英日韩混排与显式换行都不会截断。默认「不附带说明」，所以既有截图行为不变；说明随工程保存，钉图克隆也会带走。

截图工具栏「…」里新增「插入图片…」：从本地文件显式插入一张位图（PNG/JPG/BMP/WebP），落在选区中央，可移动、用角手柄等比缩放、删除与撤销，并压在普通标注之上、文字之下。透明像素按原样合成；插入时只读一次像素，之后源文件被移动或删除都不影响成图。超出尺寸/像素/文件上限、文件缺失或不是图片都会被拒绝并给出提示；插图随工程保存，钉图继承也会保留。

## 本次新增截图能力（开发批）

以下能力已通过定向/全量回归与真实原生驱动验收（逐批证据见 docs/screenshot-expansion-progress.md 第二十至第二十九批）：

- **组合标注（TF-0035）**：一次拖出「箭头 + 文字气泡」；移动气泡时箭尾重落、尖端不动，删除/撤销按整体处理。
- **编号说明列表（TF-0036）**：给每个编号填说明，导出时可排成下方或右侧步骤列表；默认不附带。
- **插图（TF-0037）**：从文件插入 PNG/JPG/BMP/WebP，等比缩放、可撤销；超限与坏文件会被拒绝。
- **导出水印（TF-0038）**：文字或图片、四角/居中、不透明度与缩放，默认关闭；设置页有实时预览。
- **标注样式预设（TF-0039）**：按工具保存/应用/重命名/删除命名样式；可应用到新建默认值或选中的图元（可撤销）。
- **截图元信息（TF-0040）**：来源/时间/备注，默认全关，只有显式保留的内容才随导出；不读取窗口标题写文件名。
- **Markdown 问题报告（TF-0041）**：多图集合导出 report.md 与 images/ 相对路径附件，顺序与备注一致。
- **混合 DPI 验收（TF-0042）**：150% 单屏实测 Win32 / mss / Qt 物理矩形一致；100%/125%/200% 与负坐标副屏未验证。
- **捕获兼容性（TF-0043）**：普通/被遮挡/最小化窗口与 DWM 合成有实测结论；HDR、硬件加速窗口、受保护内容未验证，不尝试绕过保护。

**未验证/未交付**：真实监听零留存（TF-0030，需要隔离 Windows 环境或明确授权的验证方式）；HDR 与受保护内容；完整安装包主路径（TF-0045 之后补）。
