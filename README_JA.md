
<p align="center"><img src="docs/images/versepic-icon.png" width="104" alt="VersePic icon"></p>

# VersePic

[English](README.md) · [简体中文](README_zh-CN.md) · [日本語](README_JA.md)

Windows 向けスクリーンショット・クリップボード管理アプリ。ローカル OCR、注釈、画像ピン留め、履歴検索、グループ管理を統合しています。

最新のインストール手順、対応環境、データの扱いとビルド方法は [English README](README.md) を参照してください。現在の配布は Windows x64 です。プライベートリポジトリの Releases にはアクセス権が必要です。

![Clipboard](docs/images/clipboard.png)
![Manage](docs/images/manage-dark.png)

Jietuba を基に開発。元の著作権と [MIT ライセンス](LICENSE) を保持し、UI アイコンには [Lucide](svg/lucide/LICENSE) を使用しています。

## ディレクトリ構造

<details>
<summary>ディレクトリ構造を表示</summary>

```text
# プロジェクトルート
├── README.md / README_zh-CN.md / README_JA.md          # 英語・中国語・日本語ドキュメント
├── pyproject.toml                                      # Pythonプロジェクトのメタデータと依存関係
├── requirements.txt                                   # 実行時依存パッケージ
├── requirements-dev.txt                               # テスト・ビルド用依存パッケージ
├── build_with_ocr_onefile.py                           # PyInstaller単一ファイルビルドスクリプト
│
├── main/                    # Python メインプログラム
│   ├── main_app.py          # アプリエントリポイント：システムトレイ、グローバルホットキー、ライフサイクル管理
│   ├── compile_translations.py  # 翻訳コンパイラ（.xml → .qm）
│   ├── scripts/             # 補助スクリプト — 翻訳プロバイダー比較
│   │
│   ├── barcode/             # バーコードモジュール — QRコード/バーコード読み取り（zxing-cpp）
│   ├── canvas/              # キャンバスモジュール — グラフィックス編集コア
│   ├── capture/             # キャプチャモジュール — スクリーンキャプチャ＆ウィンドウ検出
│   ├── clipboard/           # クリップボードモジュール — 履歴、グループ/クイック起動、入出力、検索
│   ├── core/                # コアモジュール — ブートストラップ、ログ、リソース、テーマ、i18n、ホットキー
│   ├── gif/                 # GIFモジュール — 画面録画、編集、再生、エクスポート
│   ├── ocr/                 # OCRモジュール — PP-OCR 文字認識
│   ├── pin/                 # ピンモジュール — スクリーンショットピン留め、編集、OCR、翻訳
│   ├── settings/            # 設定モジュール — 統一設定管理
│   ├── stitch/              # 結合モジュール — スクロールキャプチャ、自動結合
│   ├── tools/               # ツールモジュール — ペン、矩形、矢印、テキスト、モザイク等
│   ├── translation/         # 翻訳モジュール — マルチプロバイダー翻訳サービス
│   ├── translations/        # 言語リソース — 中国語/英語/日本語/韓国語
│   ├── ui/                  # UIモジュール — 共通UIコンポーネントライブラリ
│   └── tests/               # テストモジュール — ユニットテスト＆統合テスト
│
├── rust_libs/               # Rustライブラリソースコード（ソースからビルド可能）
│   ├── gifrecorder/         # GIF/動画合成エンコーダーソース
│   ├── longstitch/          # 長いスクリーンショット結合アルゴリズムソース
│   ├── pyclipboard/         # クリップボード低レベル操作ソース
│   └── ppocr_rust/          # PP-OCR (PaddleOCR) ONNX 認識エンジンソース
│
├── models/                  # PP-OCR ONNX モデル（OCR に必須）
│   ├── PP-OCRv6_det_small.onnx   # テキスト検出モデル (DBNet)
│   └── PP-OCRv6_rec_small.onnx   # テキスト認識モデル (CRNN/CTC)
│
└── svg/                     # SVGアイコンリソース
```

</details>

---

## モジュール詳細

### barcode/ — バーコードモジュール

スクリーンショットの選択範囲にある QR コードやバーコードを読み取ります。結果ウィンドウでは、左側のスクリーンショット上に各コードの位置を示し、右側に番号順で内容を一覧表示します。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
barcode/
├── __init__.py
├── reader.py                # read_codes / DecodedCode — zxing-cpp でデコードし、内容・形式・輪郭を読み順で返す
└── result_window.py         # BarcodeResultWindow — 結果ウィンドウ。スクリーンショットと結果一覧を同じ番号で対応付け
```

</details>

- QR コード、Data Matrix、Aztec、PDF417 と、Code 128・EAN/UPC などの一般的な一次元バーコードに対応
- 選択範囲内の複数のコードを一度に読み取り。どちら側でコードにホバーしても両方がハイライト
- ワンクリックでコピー。http(s) リンクはブラウザで直接開ける

---

### canvas/ — キャンバスモジュール

シーン管理、ビューレンダリング、アイテム選択、アンドゥ/リドゥ機能を備えたグラフィックス編集キャンバスシステム。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
canvas/
├── scene.py                 # CanvasScene — QGraphicsScene継承のキャンバスシーン
├── view.py                  # CanvasView — QGraphicsView継承のキャンバスビュー
├── selection_model.py       # SelectionModel — 選択グラフィックスアイテムの管理
├── undo.py                  # CommandUndoStack — アンドゥ/リドゥスタック
├── smart_edit_controller.py # SmartEditController — 選択/編集モード切替
├── smart_selection_anim.py  # SmartSelectionAnimator — ウィンドウ切り替え時の選択範囲の補間
├── handle_editor.py         # LayerEditor / EditHandle — コントロールポイントドラッグ編集
├── gestures.py              # マウスジェスチャの状態機械 — 文字の端ドラッグ、ラバーバンド選択、保留中のクリック編集
├── handle_overlay.py        # HandleOverlay — 編集ハンドル専用の合成レイヤー、シーン全体の再描画を回避
└── items/
    ├── drawing_items.py     # StrokeItem / RectItem / EllipseItem / NumberItem — DrawingItemMixin を共有する描画アイテム
    ├── background_item.py   # BackgroundItem — 選択領域の背景
    ├── mosaic_item.py       # MosaicItem — モザイクアイテム
    ├── spotlight_item.py    # SpotlightItem / SpotlightCurtain — スポットライトの穴と共有の幕
    ├── magnify_item.py      # MagnifyCalloutItem — 元画像ピクセルの書き出し可能な拡大枠
    ├── callout_link.py      # callout_link — 矢印と吹き出しの注釈の関連付けと同期
    ├── image_stamp_item.py  # ImageStampItem — 挿入したビットマップ（等比拡縮・取り消し可・プロジェクトに保存）
    ├── selection_item.py    # SelectionItem — 選択境界表示
    ├── arrow_item.py        # ArrowItem — 矢印アイテム、9 種類の軸・先端・輪郭のジオメトリ
    └── text_item.py         # TextItem — テキストアイテム、縁取り/影/背景と三状態の操作枠
```

</details>

---

### capture/ — キャプチャモジュール

スクリーンキャプチャとスマートウィンドウ検出。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
capture/
├── capture_service.py       # CaptureService — スクリーンショットコアロジック
├── quick_capture.py         # 画面・ウィンドウ・前回範囲のクイック撮影検証
├── region_presets.py        # 保存範囲と画面配置・DPI の検証
├── cursor_capture.py        # Windowsポインターの取得とホットスポット合成
├── multi_region.py          # 静止画の複数範囲と取り消し/やり直し
├── uia_element_finder.py    # UI Automation によるバックグラウンド要素検出・キャッシュ
└── window_finder.py         # WindowFinder — スマートウィンドウ選択、カーソル位置検出
```

</details>

---

### clipboard/ — クリップボード管理モジュール

Ditto風のクリップボード履歴マネージャーで、controllers・core・services・ui の4層構成に再編されています。
テキスト、画像、HTML、ファイルに対応し、グループと内容を管理する独立した3ペイン管理ウィンドウも備えています。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
clipboard/
├── __init__.py
├── controllers/             # 制御層 — 履歴読み込み、貼り付け処理、メニュー、選択状態
│   ├── clipboard_controller.py   # ClipboardController — 読み込み、貼り付け、コンテキストメニュー
│   ├── selection_manager.py      # SelectionManager — リスト選択状態管理
│   ├── context_menu_controller.py  # ContextMenuController — コンテキストメニューのデータと動作の組み立て
│   ├── foreground_tracker.py    # ForegroundWindowTracker — 貼り付け先ウィンドウを記憶
│   ├── paste_keystroke.py       # 対象ウィンドウにフォーカスを戻してから Ctrl+V を送信
│   └── __init__.py
├── core/                    # データ層 — pyclipboard ラッパー、モデル、グループ種別
│   ├── manager.py           # ClipboardManager — 保存、監視、貼り付け API
│   ├── models.py            # ClipboardItem / Group データモデル
│   ├── enums.py             # GroupType 定義
│   ├── text_transform.py    # プレーンテキスト変換 — 「特殊貼り付け」用の副作用のない純関数群
│   ├── tag_store.py         # TagStore — タグ定義とアイテム-タグ対応の保存
│   ├── image_text.py        # ローカル画像文字索引・検索・バックグラウンド OCR
│   └── __init__.py
├── services/                # サービス層 — file payload、グループ規則、入出力、保存ロジック
│   ├── file_payload_service.py   # file 型 JSON payload と旧形式互換
│   ├── group_service.py          # グループのアイコン・命名・削除確認補助
│   ├── import_export_service.py  # テキスト項目の CSV インポート/エクスポート
│   └── manage_dialog_service.py  # 管理ウィンドウの保存ロジック
├── ui/
│   ├── layout_scale.py           # 管理ウィンドウ共通のサイズ定数
│   ├── dialogs/
│   │   └── manage_dialog.py      # グループ・内容・入出力を扱う3ペイン管理ウィンドウ
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
│       ├── clipboard_window.py   # 履歴ウィンドウ、検索、プレビュー、高速貼り付け
│       └── pin_window.py         # 履歴項目からピンを作成
```

</details>

**主な機能:**
- システムクリップボードの変更を監視し、自動で履歴を保存
- テキスト、画像、HTML、ファイル等に対応
- 通常グループ、クイック起動グループ、お気に入り、検索に対応
- 独立した3ペイン管理ウィンドウでグループ・テキスト内容・ファイル内容を編集可能
- テキスト項目の CSV インポート/エクスポートに対応
- テーマ切替、ショートカットによる高速貼り付け、大画像/長文プレビューに対応

---

### core/ — コアモジュール

ログ、リソースローディング、テーマ管理、国際化、ホットキー等のインフラ。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
core/
├── bootstrap.py             # PreloadManager — 起動ブートストラップ、環境初期化、DPI、シングルインスタンス
├── single_instance.py       # SingleInstanceGuard — 名前付きミューテックスの単一実行ガード（並列性の確保を事前に保証）
├── logger.py                # Logger — ファイル＋コンソールログ（debug/info/warning/error/exception）
├── crash_handler.py         # install_crash_hooks() — グローバル例外キャッチ
├── resource_manager.py      # ResourceManager — SVG/画像リソースローディング
├── theme.py                 # ThemeManager — アプリテーマカラー管理
├── ui_scale.py              # UIScaleManager — ツールバー/パネル/ポップアップ共通の拡大率
├── i18n.py                  # I18nManager / XmlTranslator / tr() — 国際化
├── shortcut_manager.py      # HotkeySystem / ShortcutManager — グローバル＆アプリ内ホットキー
├── last_capture_region.py   # 「前回の選択範囲を復元」用のプロセス内メモリ
├── save.py                  # SaveService — ファイル保存サービス（高品質 PDF 出力対応）
├── searchable_pdf.py       # 出力ピクセルからOCRする検索PDFとページ別結果
├── image_output.py          # 不変の画像出力設定と安全な命名テンプレート
├── image_layout.py          # メモリ上限付き画像結合と画像ごとのPDFページ描画
├── image_compare.py         # 容量制限付き透明度対応ピクセル比較
├── image_document.py        # 非破壊の画像変換と元ファイル保護
├── editable_project.py      # 容量制限付き編集画像プロジェクトと注釈の保存・復元
├── export.py                # ExportService — 画像エクスポート
├── number_legend.py         # 番号説明の手順リストを下/右にレイアウトして書き出す
├── watermark.py             # 出力ウォーターマーク（TF-0038）：文字/画像、位置/余白/不透明度、既定はオフ
├── annotation_presets.py    # 注釈スタイルのプリセット（TF-0039）：ツールごとに保存し新規既定へ適用
├── capture_metadata.py      # キャプチャのメタ情報（TF-0040）：来源/時刻/メモ、既定は全オフ
├── markdown_report.py       # Markdown 問題レポート（TF-0041）：相対パス添付・エスケープ・順序
├── packaged_self_check.py   # パッケージ自检（TF-0045）：ビルド内で主要経路を実行
├── clipboard_utils.py       # copy_image_to_clipboard() — 画像をクリップボードにコピー
├── capture_privacy.py       # キャプチャと派生ウィンドウのメモリ内機密ポリシー
├── platform_utils.py        # DPI設定、AppUserModelID、Windows APIユーティリティ
├── qt_utils.py              # safe_disconnect() — Qtシグナル安全切断
├── log_translations/        # 各モジュールのログ翻訳ヘルパー
├── constants.py             # グローバル定数（フォント、パス等）
├── update_checker.py        # GitHub 最新リリースの非同期取得とバージョン比較
└── ui_theme.py              # UIThemeManager — アプリ窓と Qt ネイティブ部品のライト/ダーク外観
```

</details>

---

### gif/ — GIF録画モジュール

画面録画、編集、再生、GIF/動画エクスポート。
<details>
<summary>ディレクトリ構造を表示</summary>

```text
gif/
├── record_window.py         # GifRecordWindow / AppState — ステートマシンコーディネーター（3層ウィンドウ）
├── overlay.py               # CaptureOverlay / OverlayMode — キャプチャオーバーレイ、領域調整
├── drawing_view.py          # GifDrawingView / GifDrawingScene — 録画中描画
├── drawing_toolbar.py       # GifDrawingToolbar — 描画ツールバー
├── record_toolbar.py        # RecordToolbar — 開始/一時停止/停止コントロール
├── frame_recorder.py        # FrameRecorder / FrameData / CursorSnapshot — フレームサンプリング
├── playback_engine.py       # PlaybackEngine / PlayState — フレーム再生＆プレビュー
├── playback_controller.py   # PlaybackController — 再生UI＆エクスポート管理
├── playback_toolbar.py      # PlaybackToolbar / RangeSlider — プログレスバー、速度調整
├── composer.py              # _ComposeWorker / ComposerProgressDialog — GIF/動画合成
├── export_dialog.py         # GifExportDialog — GIF出力サイズとフレームレート設定
├── mp4_export.py            # 無音H.264/MP4フレーム出力
├── mp4_diagnostics.py       # パッケージの明示的な合成素材出力チェック
├── cursor_overlay.py        # CursorOverlay — カーソルレンダリング＆クリックアニメーション
└── _widgets.py              # ClickMenuButton / svg_icon() — カスタムウィジェット
```

</details>

---

### ocr/ — OCRモジュール

PP-OCR による文字認識管理。


<details>
<summary>ディレクトリ構造を表示</summary>

```text
ocr/
└── ocr_manager.py           # OCRManager — ppocr_rust (PP-OCR) による文字認識
```

</details>

- ppocr_rust エンジン（純 Rust + ONNX Runtime、PP-OCR det + rec）を使用。推論はネイティブスレッドで実行され UI をブロックしない
- 中国語/英語/日本語認識
- シングルトンパターン、統一認識インターフェース

---

### pin/ — ピンモジュール

スクリーンショットを画面にピン留め。編集、ズーム、OCR、翻訳対応。


<details>
<summary>ディレクトリ構造を表示</summary>

```text
pin/
├── pin_window.py            # PinWindow — ドラッグ可能、ズーム可能、常に最前面の画像ウィンドウ
├── pin_canvas_view.py       # PinCanvasView — ピンキャンバスビュー
├── pin_canvas.py            # ピンキャンバスオブジェクト
├── pin_manager.py           # PinManager — 全ピンウィンドウ管理（シングルトン）
├── workspace.py            # 容量制限付き編集画像ワークスペースと復元
├── workspace_dialog.py     # 画像の選択、保存、復元とごみ箱への移動
├── pin_toolbar.py           # PinToolbar — ピンツールバー
├── pin_controls.py          # PinControlButtons — 閉じる、編集、コピーボタン
├── pin_context_menu.py      # PinContextMenu — 右クリックメニュー
├── pin_border_overlay.py    # PinBorderOverlay — ボーダーエフェクトオーバーレイ
├── pin_ocr_manager.py       # PinOCRManager / _OCRThread — 非同期OCR認識
├── pin_shortcut.py          # PinShortcutController — 通常/編集モードショートカット
├── pin_thumbnail.py         # PinThumbnailMode — サムネイルモード
├── pin_translation.py       # PinTranslationHelper — 翻訳ヘルパー
├── pin_image_transform.py   # PinImageTransform — 回転、反転等
└── ocr_text_layer.py        # OCRTextLayer / OCRTextItem — OCRテキストレイヤー表示
```

</details>

---

### settings/ — 設定モジュール

<details>
<summary>ディレクトリ構造を表示</summary>

```text
settings/
├── color_formats.py         # 拡大鏡のカラー形式テンプレート：描画・読み込み・保存
└── tool_settings.py         # ToolSettingsManager / ToolSettings — ツールの色、サイズ、ホットキー設定
```

</details>

---

### stitch/ — 長いスクリーンショット結合モジュール

<details>
<summary>ディレクトリ構造を表示</summary>

```text
stitch/
├── jietuba_long_stitch_unified.py   # 結合インターフェース（Rust の longstitch を呼び出す）
├── scroll_window.py                 # ScrollCaptureWindow — スクロールキャプチャウィンドウ
├── session.py              # 容量制限付きスクロール撮影履歴と継ぎ目修正
├── adjustment_dialog.py    # 継ぎ目と照合除外領域の確認画面
├── auto_scroll.py          # 停止可能で上限付きの前面対象スクロール
├── auto_scroll_dialog.py   # 自動スクロールの上限と開始確認画面
└── scroll_toolbar.py                # スクロールキャプチャツールバー
```

</details>

---

### tools/ — 描画ツールモジュール

<details>
<summary>ディレクトリ構造を表示</summary>

```text
tools/
├── base.py                  # Tool / ToolContext — 抽象基底クラス
├── controller.py            # ToolController — ツール切替＆状態管理
├── action.py                # ActionTools — コピー、保存、キャンセルアクション
├── pen.py                   # PenTool — フリーハンド描画
├── rect.py                  # RectTool — 矩形（塗りつぶし/アウトライン）
├── ellipse.py               # EllipseTool — 楕円
├── arrow.py                 # ArrowTool — 矢印
├── callout.py               # CalloutTool — 矢印 + 吹き出しの組み合わせ注釈
├── text.py                  # TextTool — テキスト
├── number.py                # NumberTool — 自動インクリメント番号
├── highlighter.py           # HighlighterTool — 蛍光ペン
├── mosaic.py                # MosaicTool — モザイク
├── spotlight.py             # SpotlightTool — スポットライト（枠の外を暗くする）
├── magnify.py               # MagnifyTool — 元画像の一部を拡大枠として書き出す
├── cursor.py                # CursorTool — カーソル/選択
├── eraser.py                # EraserTool — 消しゴム
└── cursor_manager.py        # CursorManager — カーソルスタイル管理
```

</details>

---

### translation/ — 翻訳モジュール

DeepL / Google / Azure / Amazon などに対応したマルチプロバイダー翻訳サービス。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
translation/
├── provider.py              # TranslationProvider / ProviderMetadata — プロバイダー抽象契約
├── registry.py              # ProviderRegistry — プロバイダー登録とファクトリ
├── service.py               # TranslationService — プロバイダー選択と翻訳オーケストレーション
├── models.py                # TranslationRequest / TranslationResult — プロバイダー非依存モデル
├── worker.py                # TranslationWorker — 全プロバイダー共通の Qt ワーカー
├── providers/               # 各翻訳プロバイダー実装
│   ├── deepl.py             # DeepL
│   ├── google.py            # Google
│   ├── azure.py             # Azure
│   ├── amazon.py            # Amazon
│   ├── baidu.py             # Baidu
│   ├── custom_llm.py        # カスタム OpenAI 互換サービス（Ollama、LM Studio など）
│   ├── deepseek.py          # DeepSeek (LLM)
│   └── openai_compatible.py # OpenAI 兼容接口基类
├── smart_translation_controller.py # SmartTranslationController — ワンキー選択テキスト検出＆ポップアップルーティング
├── translation_popup.py     # TranslationPopup — コンパクト翻訳ポップアップ（選択テキスト/手入力）
├── deepl_service.py         # DeepLService / TranslationThread — 旧版 DeepL API 非同期翻訳
├── languages.py             # SupportedLanguages — 対応言語リスト・言語コード
├── translation_manager.py   # TranslationManager — 翻訳ウィンドウマネージャー（シングルトン）
├── translation_dialog.py    # TranslationDialog — 翻訳結果ウィンドウ
└── ui/
    ├── dialog.py            # 翻訳ダイアログUI
    └── widgets.py           # 翻訳ウィジェット
```

</details>

**主な機能:**
- プラグイン可能なマルチプロバイダー構成（DeepL / Google / Azure / Amazon）をレジストリで一元管理
- ワンキー：選択テキストを自動検出して翻訳ポップアップへ
- 選択テキスト／手入力の2モード対応コンパクトポップアップ
- 非同期翻訳でUIをブロックしない
- 翻訳結果のコピーに対応

---

### translations/ — 言語リソース

<details>
<summary>ディレクトリ構造を表示</summary>

```text
translations/
├── app_zh.xml / app_en.xml  # 中国語 / 英語ソースファイル
├── app_ja.xml / app_ko.xml  # 日本語 / 韓国語ソースファイル
└── app_*.xml.qm             # コンパイル済み Qt バイナリ（app_zh.xml.qm 等）
```

</details>

`.xml` = 編集可能なソースファイル、`*.xml.qm` = Qtランタイムで読み込むコンパイル済みファイル。変更後は `compile_translations.py` を実行して再コンパイルしてください。

---

### ui/ — UIモジュール

共通UIコンポーネントライブラリ。

<details>
<summary>ディレクトリ構造を表示</summary>

```text
ui/
├── toolbar.py               # Toolbar / _DragHandle — ドラッグ可能なツールバー基底クラス
├── toolbar_layout.py        # スクリーンショットツールバーのボタン配置（順序・表示方法）の正規化と読み書き
├── toolbar_layout_dialog.py # ToolbarLayoutDialog — スクリーンショットツールバーの配置編集ダイアログ
├── reorderable_rows.py      # DragGrip / DraggableRow / ReorderableRowList — ドラッグで並べ替えられる行リスト
├── tray_menu.py             # TrayMenu — システムトレイメニュー
├── screenshot_window.py     # ScreenshotWindow — フルスクリーンキャプチャウィンドウ
├── capture_countdown.py     # CaptureCountdown — フォーカスを奪わないキャンセル可能な遅延撮影
├── image_layout_dialog.py   # 画像収集、並べ替え、プレビューと非同期出力
├── image_compare.py         # 読み取り専用の並列・スライダー・差分表示
├── image_editor.py          # 貼り付け画像キャンバスと注釈ツールを再利用する画像エディター
├── multi_region_dialog.py   # 全画面の複数範囲選択と一括収集
├── dialogs.py               # StandardDialog — 確認、警告、情報、エラーダイアログ
├── component_gallery.py     # 共通 Qt コンポーネントの操作ギャラリー（docs/qt-components.md）
├── magnifier.py             # MagnifierOverlay — ピクセルレベル拡大鏡
├── color_picker_dialog.py   # ColorPickerDialog — カスタムHSVカラーピッカー
├── color_picker_button.py   # ColorPickerButton — カラー選択ボタン
├── hotkey_edit.py           # HotkeyEdit — グローバルホットキーエディター
├── inapp_key_edit.py        # InAppKeyEdit — アプリ内ショートカットエディター
├── key_chip.py              # KeyChipLineEdit / StatusIcon — ショートカットのキー表示と状態アイコン
├── mask_overlay.py          # マスクオーバーレイヤー
├── selection_overlay.py     # SelectionOverlayWidget — マスク上に重なる選択装飾レイヤー
├── base_settings_panel.py   # BaseSettingsPanel / StepperWidget — 設定パネル基底クラス
├── paint_settings_panel.py  # PaintSettingsPanel — ブラシ設定パネル
├── shape_settings_panel.py  # ShapeSettingsPanel — 形状設定パネル
├── text_settings_panel.py   # TextSettingsPanel — テキスト設定パネル
├── arrow_settings_panel.py  # ArrowSettingsPanel — 矢印設定パネル
├── number_settings_panel.py # 番号ツール設定パネル
├── mosaic_settings_panel.py # モザイクツール設定パネル
├── apple_style.py           # Apple スタイルのデザイントークンと QSS ヘルパー（クリップボード／管理ウィンドウ共用）
├── motion.py                # モーションヘルパー — ウィンドウのフェード／ライズとホバーアニメーション
│
├── glass.py / glyphs.py / outline_icons.py  # Native glass and Lucide SVG rendering
├── fluent_lite/             # Fluent スタイル軽量コンポーネントライブラリ
│   ├── icon_label.py        # アイコンとテキストの共通配置
│   ├── button_base.py / popups.py / primitives.py  # Shared animated controls
│   ├── buttons.py / cards.py / icons.py / inputs.py  # ボタン、カード、アイコン、入力欄
│   ├── labels.py / navigation.py / segmented.py      # ラベル、ナビゲーション、セグメントコントロール
│   ├── switch.py / theme.py / titlebar.py            # スイッチ、テーマ、タイトルバー
│   ├── frameless.py         # フレームレスウィンドウ
│   └── text_context_menu.py # テキスト右クリックメニュー
│
├── settings_ui/             # アプリ設定ダイアログ
│   ├── dialog.py            # SettingsDialog — タブ式設定ダイアログ
│   ├── components.py        # SettingCardGroup / ToggleSwitch — 設定コンポーネント
│   ├── page_appearance.py   # 外観設定（テーマ、言語）
│   ├── page_capture.py      # キャプチャ設定
├── watermark_controls.py  # Export watermark settings group (TF-0038)
├── metadata_controls.py   # Capture metadata settings group (TF-0040)
├── markdown_report_dialog.py # Markdown レポートダイアログ（TF-0041）
├── preset_dialog.py       # Annotation style presets dialog (TF-0039)
│   ├── color_format_dialog.py # ColorFormatDialog — 拡大鏡のカラー形式を管理するダイアログ
│   ├── page_clipboard.py    # クリップボード設定
│   ├── page_hotkey.py       # ホットキー設定
│   ├── page_translation.py  # 翻訳設定
│   ├── provider_fields.py   # 服务商字段的读写（按声明）
│   ├── page_log.py          # ログ設定
│   ├── page_developer.py    # 開発者設定
│   ├── page_misc.py         # その他設定
│   ├── page_about.py        # アバウトページ
│   └── mock_config.py       # MockConfig — テスト用モック設定
│
├── welcome/                 # 初回起動ウェルカムウィザード（6ページガイド）
│   ├── wizard.py            # WelcomeWizard — ウィザードメインウィンドウ
│   ├── base_page.py         # BasePage — ウィザードページ基底クラス
│   ├── page1_welcome.py     # ウェルカムページ
│   ├── page2_screenshot.py  # スクリーンショットホットキー設定ページ
│   ├── page3_clipboard.py   # クリップボードホットキー設定ページ
│   ├── page5_translation.py # 翻訳機能説明ページ
│   ├── page6_finish.py      # 完了ページ
│   └── page_hotkeys.py      # グローバルホットキーページ — 6 つのキーは同一の衝突領域、まとめて設定・重複判定
│
└── selection_info/          # 選択情報UI
    ├── controller.py        # 選択情報コントローラー
    ├── panel.py             # 選択情報パネル（サイズ、座標）
    ├── geometry_dialog.py   # 座標・サイズ・縦横比の編集
    ├── hook_manager.py      # フックマネージャー
    ├── border_shadow.py     # 選択ボーダーシャドウエフェクト
    ├── lock_ratio.py        # アスペクト比ロック
    └── rounded_corners.py   # 角丸スクリーンショット
```

</details>

---

### tests/ — テストモジュール

<details>
<summary>ディレクトリ構造を表示</summary>

```text
tests/
├── conftest.py              # pytest設定＆共通フィクスチャ
├── pytest.ini               # pytest実行設定
├── run_tests.py             # テスト実行スクリプト
├── test_drawing_tools.py    # 描画ツールテスト（ペン/矩形/矢印/テキスト/番号/蛍光ペン）
├── test_mosaic_tool.py      # モザイクツールテスト
├── test_spotlight.py        # スポットライトテスト
├── test_magnify_callout.py  # 拡大枠テスト
├── test_text_callout.py     # 組み合わせ注釈（矢印 + 吹き出し）テスト
├── test_functional_handles.py # コントロールポイント編集テスト
├── test_capture_service.py  # キャプチャサービステスト
├── test_clipboard_api.py    # クリップボード公開 API テスト
├── test_clipboard_manage_dialog.py # クリップボード管理ウィンドウテスト
├── test_frame_recorder.py   # GIFフレーム録画テスト
├── test_playback_engine.py  # GIF再生エンジンテスト
├── test_ocr_text_layer.py   # OCRテキストレイヤーテスト
├── test_pin_window_zoom.py  # ピンウィンドウズームテスト
├── test_smart_translation.py # スマート翻訳テスト
├── test_translation_architecture.py # 翻訳プロバイダーアーキテクチャテスト
├── test_stitch_dedup.py     # 長いスクリーンショット結合重複除去テスト
├── test_settings_dialog_state.py # 設定ダイアログ状態テスト
├── test_welcome_translation.py # ウェルカムウィザード翻訳ページテスト
└── …（その他 70 以上のユニット/統合テストファイル）
```

</details>

ローカルのスクリーンショット拡張には GIF のサイズ・フレームレート設定が含まれます。このチェックアウトの `rust_libs/gifrecorder` をビルドしてインストールしてください。公開版 j-gif 0.3.1 のバイナリには新しいインターフェースがありません。手順はネイティブモジュールの README を参照してください。インストーラーの検証・リリースは未完了です。

録画の再生 → 保存 → MP4 から、トリム・速度・カーソル効果を保った無音 H.264 動画を出力できます。奇数サイズは右端・下端に余白を追加し、伸縮しません。音声収録はありません。`versepic.exe --verify-mp4-export <空の出力先>` は通常起動を回避し、合成素材と結果を指定先だけに書き出す明示的なチェックです。PyAV のライセンスを同梱しますが、FFmpeg/x264 の再配布条件と完全なインストーラー検証はリリース前の確認事項です。

スマート墨消しに、中国身分証の日付・検査符号、カードの Luhn 検査、限定的な OCR O/I/l 補正を追加しました。名前付きプリセットはルール設定のみ保存し、キーワード、OCR テキスト、画像は保存しません。候補は人が確認してください。検査符号は身元や口座の実在を証明せず、OCR 誤読や分割行を見逃す場合があります。PNG/JPEG/PDF は元の解像度で黒塗りを画像に統合して新規保存し、既存ファイルは上書きしません。

ローカル版のトレイに「機密キャプチャ（今回のみ）」を接続しました。ピンと墨消しもポリシーを維持し、保存・録画・テキスト・翻訳の出力を禁止、明示的なマーク付き画像コピーのみ許可します。ローカルの機密クリップボードプロトコルが必要です。分離ウィンドウステーションの作成が拒否され、実際の履歴非保存検証は未完了です。ネイティブUI検証ではOSコピーを代替しています。他アプリの読み取り、OSページング、クラッシュダンプの消去を保証しません。

履歴画像の右クリック → 画像の文字索引で、待機・認識中・失敗・対象外・索引済み・文字なしの状態を確認し、再試行・再認識・除外・再開を操作できます。除外は現在の OCR 検索情報を削除し、明示的に再開するまで再起動後も保持します。元画像と貼り付け形式は変更しません。失敗は再起動のたびに再試行せず、ジョブトークンで削除・除外・画像変更・DB移行後の古い結果を拒否します。SQLiteページ、バックアップ、以前コピーした文字の安全な消去ではありません。

文字認識 → 表を確認では、元の OCR 枠（プレーンテキスト編集後の内容ではありません）から単純で分離したセルの表を再構築し、原画像と比較して編集できます。セル・複数行・行列の修正、引用符付きTSVコピー、エスケープ済みMarkdown出力に対応します。最大200行、32列、4000セル、50万文字、画像3200万画素です。結合セルや折返し、連結OCR行は手動修正が必要です。数式風文字は既定でアポストロフィを付加しますが、貼り付け先の設定により日付・先頭ゼロ・制御文字が変わることがあります。自動クラウド送信や履歴保存は追加しません。

PDF収集で画像のみ（既定）と新しいローカルOCRによる検索PDFを選べ、画像を0/90/180/270度回転できます。検索出力は白背景に合成した回転後の実際のピクセルだけを認識し、履歴や墨消し前のOCRを再利用しません。文字を不透明画像の下に配置するため、画像の外観を維持して検索・抽出できます。空白、OCR失敗、字形不足は画像のみで保存しページ別レポートで報告します。誤認識や複雑な読み順は確認が必要です。文字認識画面からも現在の画像のPDF出力を開けます。

トレイの「1回限りの機密スクリーンショット」は実装済みです。方針はピンと墨消し窓に引き継ぎ、保存・履歴・録画・文字/翻訳の出口を止め、明示的なコピーだけが印付き画像を書き込みます。この作業コピーの私的クリップボードプロトコルが必要です。隔離ウィンドウステーション作成は WinError5 で拒否され、本物の監視ゼロ残留は未完了です。開発中の経路を検証済みのプライバシー保証と見なせません。

スクリーンショット・ピン・ファイル編集キャンバスでは、選んだ元領域を書き出し可能な拡大枠にできます。表示されるのは元画像ピクセル（最近傍）だけで、他の注釈・枠自身・編集ハンドルは入りません。枠を動かしてもサンプリング位置は変わりません。スポイト用ルーペとは別機能です。スクリーンショットツールバーでは「…」に入り、ピンとファイル編集では描画列に出ます。この図元を含まない古い工程はそのまま開けます。含む新しい工程を古い版で開くと、普通の矩形にはならず未対応注釈として報告します。

スクリーンショット・ピン・ファイル編集キャンバスでは、「矢印 + 吹き出し」の注釈を一度のドラッグで作れます。吹き出しを置く位置から指したい場所へドラッグし、そのまま説明を入力します。空のまま別の場所をクリックすると注釈ごと破棄されます。吹き出しを動かしたり文字を増やしたりすると、矢印の根元が吹き出しの縁に付き直し、先端は元の対象を指したままです。削除・一括削除・取り消しは両方をひとまとまりとして扱い、単体の矢印とテキストの動作は変わりません。スクリーンショットのツールバーでは「…」に入り、ピンとファイル編集では描画列に出ます。保存した工程を開き直すと両方は同じ座標に描かれますが、連動は復元されません。

番号注釈に番号ごとの説明を付けられるようになりました（番号を選び、番号パネルの入力欄に記入）。書き出し時は説明を手順リストとして画像の下または右に配置できます。リストは番号順で、削除・取り消し・番号の振り直しでも説明は自分の番号に付いたままです。長い説明はピクセル幅で折り返し、CJK とラテンの混在や明示的な改行も切り捨てません。既定は「説明リストなし」なので既存の書き出しは変わりません。説明は編集プロジェクトに保存され、ピンのクローンにも引き継がれます。

スクリーンショットのツールバー「…」に「画像を挿入…」を追加しました。ローカルのビットマップ（PNG/JPG/BMP/WebP）を選択領域の中央に挿入し、移動・角ハンドルでの等比拡縮・削除・取り消しができます。重なり順は通常の注釈より上、テキストより下です。透明部分はそのまま合成され、ピクセルは挿入時に一度だけ読み込むため元ファイルを移動・削除しても成図は変わりません。サイズ・画素・ファイル上限を超える場合や、ファイルが無い・画像でない場合は警告を出して拒否します。挿入画像は編集プロジェクトに保存され、ピンの継承でも保持されます。

## 今回追加したスクリーンショット機能（開発バッチ）

以下は定向/全量回帰と実機のネイティブドライバで検証済みです（批次ごとの証跡は docs/screenshot-expansion-progress.md の第20〜29批）：

- **吹き出し注釈（TF-0035）**：一度のドラッグで「矢印 + 吹き出し」を作成。吹き出しを動かすと矢印の根元が付き直し、先端は動きません。削除・取り消しは両方をひとまとまりとして扱います。
- **番号の説明リスト（TF-0036）**：番号ごとに説明を入力し、画像の下または右に手順リストとして書き出せます（既定はオフ）。
- **画像の挿入（TF-0037）**：PNG/JPG/BMP/WebP をファイルから挿入し、等比拡縮・取り消しが可能。サイズ超過や壊れたファイルは拒否します。
- **出力ウォーターマーク（TF-0038）**：文字/画像、四隅/中央、不透明度とサイズ。既定はオフで、設定ページにライブプレビューがあります。
- **注釈スタイルのプリセット（TF-0039）**：ツールごとに名前付きスタイルを保存/適用/名前変更/削除。新規既定値か選択中の図元（取り消し可）に適用します。
- **キャプチャのメタ情報（TF-0040）**：来源/時刻/メモ。既定は全オフで、残した内容だけが出力され、ウィンドウタイトルをファイル名に書きません。
- **Markdown 問題レポート（TF-0041）**：複数画像を report.md と相対パスの images/ に出力。順序とメモを保ちます。
- **混合 DPI 検証（TF-0042）**：150% 単一画面で Win32 / mss / Qt の物理矩形が一致。100%/125%/200% と負座標モニタは未検証です。
- **キャプチャ互換性（TF-0043）**：通常・遮蔽・最小化ウィンドウと DWM 合成の実測結果あり。HDR、ハードウェアアクセラレーション、保護コンテンツは未検証で、保護の回避は行いません。

**未検証/未提供**：実リスナーの零残留（TF-0030、隔離された Windows 環境か明示的な許可が必要）、HDR と保護コンテンツ、完全なインストーラ経路（TF-0045 以降）。
