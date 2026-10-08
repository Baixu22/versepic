# 截图内容助手第一阶段

验证日期：2026-09-30。源码实现完成；后续测试修复后的全库回归已通过：2450 passed、2 skipped，exit 0；全库 Ruff 通过。保留了开始本轮前已有的界面修改。

## 使用入口

- 截图工具栏「更多 → 文字识别」：编辑结果、合并断行、清理空格、恢复原文、翻译、网页搜索、保存文本文件或保存到历史/分组。加工操作支持 Ctrl+Z。
- 剪贴板历史搜索：打开历史后后台逐张补索引，新复制的图片也会索引。搜索包括图片内文字；右键图片「文字识别」打开结果并选中搜索词。
- 截图工具栏「更多 → 智能脱敏」，或历史图片右键「智能脱敏」：识别手机号、邮箱、自定义逗号分隔关键词；确认各行遮盖，也可拖动补画区域。复制、PNG/JPEG/PDF 保存均输出已经合成的实色遮盖图片。

## 实现边界

OCR 索引保存在原剪贴板数据库的独立 `image_text` 表，保留图片内容、原始粘贴格式、顺序与分组。删除记录通过数据库触发器清除对应索引。写入时同时检查记录 ID 与图片 ID，取消、删除和数据库迁移后的迟到结果不能重建记录或旧数据库。

首次索引尚未完成时，搜索结果会逐步补齐。无文字图片记录为空索引；识别失败不当作空结果保存。任务串行执行，沿用本地 OCR 引擎，无新增依赖。退出沿用现有 OCR 线程等待机制。

脱敏采用整行文字框，支持手工增补，不保证规则识别覆盖所有敏感内容。原始历史图片不会被覆盖。网页搜索由用户点击后在浏览器中打开 Bing；翻译沿用用户配置的服务。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| 功能及相关回归分组 A | 287 passed，1 skipped，2 warnings；exit 0 |
| 新增功能与翻译资源分组 B | 47 passed；exit 0；其中 17 项与 A 重复 |
| 去重后的相关用例 | 317 passed，1 skipped |
| 本轮修改的 Python 文件 Ruff 检查 | exit 0 |
| 四种语言 XML → QM 编译 | 全部成功，exit 0 |
| `git diff --check` | exit 0 |
| 真实 OCR 演示 | 真实引擎识别错误码、邮箱、手机号；写入索引后从实际历史窗口搜索命中；脱敏匹配两行，exit 0 |
| 界面渲染 | 中文深浅色 OCR/脱敏窗口、历史搜索和导出图已查看；使用 Qt offscreen |

跳过项是剪贴板搜索动画的原生 Windows 分层窗口透明度测试，offscreen 不支持该能力。两条 warning 来自已有 `QImage.mirrored` 弃用调用。

本机验证日志位于 `.ui_review/`：`screen-assistant-focused-final.log`、`screen-assistant-i18n-final.log`、`screen-assistant-smoke.log`；演示图片位于 `.ui_review/screen-assistant/`。这些是本地忽略的验证产物，不随 Git 分发。

新增功能测试可单独运行：

```powershell
.\venv312\Scripts\python.exe -m pytest main/tests/test_screen_assistant.py -q
```

## 第一阶段留下的检查问题（历史记录）

- 全量测试收集 2446 项，运行至缩放设置测试附近长时间停留后中断，未得到完整汇总；该缩放测试单独运行 1 passed，exit 0。
- 现有翻译设置/编号样式测试单独复现 5 failed、82 passed，exit 1。四项仍按 `PushButton` 查找此前已改成其他按钮类型的控件；一项仍要求字面量 `background: white`，实际样式已经是 `#FFFFFF`。本轮未改这几处实现与断言。
- 一次较长的相关测试批次在 `test_i18n.py:286` 的 Qt 翻译调用出现 `Windows fatal exception: access violation`。该测试集单独运行及与新增功能一起分组运行通过；原生崩溃根因未定，分组通过不代表全库长时间运行稳定性已验证。
- 全库 Ruff 仍有其他文件的 19 项诊断；本轮改动范围检查通过。

第一阶段未生成新的安装包，也未将以上验证等同于用户桌面环境的完整原生交互验收。

## 后续测试修复与全量复验

用户确认继续处理测试失败后，完成以下修复：

- 翻译服务测试通过 `QAbstractButton` 查找真实按钮，继续验证实际点击、请求参数、模型列表与错误反馈，避免绑定旧的 `PushButton` 包装类型。
- 编号弹层配色检查覆盖深浅两种模式，比较颜色值与当前主题，而不要求 `white` 这种特定字符串拼写。
- 为翻译服务和字段测试创建的设置窗口补上 pytest-qt 销毁流程。实测该测试模块结束时残留控件从 5792 个降至 1 个 Qt 内置提示标签，设置窗口从 5 个降至 0 个。
- 工具提示的全局事件过滤器只在所属窗口可见时启用，隐藏时移除，重新显示时恢复。新增用例验证隐藏窗口不接收无关全局事件，以及显示、隐藏、销毁后的行为。
- 翻译单例测试用后恢复之前的实例，避免丢失其他窗口的翻译器与信号连接。欢迎页测试显式设置并恢复语言，分别验证中文与英文。
- 清理全库 19 项 Ruff 诊断；保留公开导出的 `ACCENT` 和渲染脚本中维持 QApplication 生命周期的引用。

最终验收命令：

```powershell
.\venv312\Scripts\python.exe -m pytest main/tests -q --tb=short -o faulthandler_timeout=30 --durations=10 -rs --junitxml=.ui_review/test-failure-acceptance.xml
ruff check main
git diff --check
```

| 检查 | 最终结果 |
| --- | --- |
| 全量测试，同一进程整批运行 | 2450 passed、2 skipped、640 warnings；159.92 秒；exit 0 |
| 修复相关回归 | 153 passed；exit 0 |
| 全库 Ruff | All checks passed；exit 0 |
| Diff 检查 | exit 0 |

本轮整批运行没有出现原生崩溃，也没有触发 30 秒 faulthandler 超时。此结果替代此前仅分组通过的结论，不等同于对所有原生 Qt 崩溃原因的穷尽证明。

两项跳过分别为需要显式启用的真实剪贴板监听性能基准，以及 offscreen 不支持的 Windows 分层窗口透明度检查。640 条 warning 来自现有 Qt/Pillow 弃用 API，本次没有屏蔽或将它们改为通过条件。

本机完整日志：`.ui_review/test-failure-acceptance.log`；JUnit 汇总：`.ui_review/test-failure-acceptance.xml`。窗口残留对照日志为 `.ui_review/test-failure-widget-retention-before.log` 与 `.ui_review/test-failure-widget-retention-after.log`。
