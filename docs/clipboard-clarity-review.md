# 剪贴板可辨识性验收 · 2026-10-08

本次在既有修改上调整剪贴板列表、排列菜单和预览，沿用共享主题与 Qt 控件。
视觉规则见 `DESIGN_CLIPBOARD.md` 第 12 节。

## 验证结果

- 剪贴板全部测试，加共享控件、主题、OCR 搜索与翻译回归：323 passed、2 skipped、3 warnings，exit 0。
  跳过的是需单独启用的真实监听性能基准，以及 offscreen 下不支持的原生窗口透明度测试。
- 9 个预设主题 × 8 种标签色，在普通/置顶背景上验证标签文字对比度不低于 4.5:1。
- 四种排列均在数据库分页之前执行，搜索结果也遵循同一排列；测试覆盖置顶、取消置顶和跨页顺序。
- 中文、英文、日文、韩文 QM 已重编译；本次 10 条文本的 40 个精确上下文翻译全部通过。
- Windows Qt 平台隔离示例：菜单点击、排序记忆、置顶切换与选中项保持通过；已检查浅色、深色、
  悬停/选中、560px 窄窗口、22px 大字号、长文本与图片预览截图。

## 本地证据

- `.ui_review/clipboard-clarity/regression-final.log`
- `.ui_review/clipboard-clarity/native-final.log`
- `.ui_review/clipboard-clarity/sorted.png`
- `.ui_review/clipboard-clarity/apple-pinned-hover.png`
- `.ui_review/clipboard-clarity/apple-dark-pinned-hover.png`
- `.ui_review/clipboard-clarity/apple-large-font.png`
- `.ui_review/clipboard-clarity/apple-dark-text-preview.png`
- `.ui_review/clipboard-clarity/sort-menu.png`

原生验收由 `native_review.py` 使用临时数据库和设置执行，窗口退出后关闭标签库并清理临时数据。
截图与交互断言来自真实 Qt Windows 平台；系统桌面自动化未枚举出测试窗口，因此没有将其算作系统鼠标端到端验收。
本次未重新打包发布版、未测监听性能，也不代表用户实际桌面背景下的高透明度可读性验收。

旧 `venv312` 的基础解释器路径已失效。本次仅将 `pyvenv.cfg` 指回现有同版本 Python 3.12.13，
保留原文件于 `.ui_review/clipboard-clarity/before/pyvenv.cfg`，未重装依赖。

开发版启动：`venv312\Scripts\python.exe run_dev.py`。
