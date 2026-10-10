# j-clipboard

Windows clipboard access and history management for Python, implemented in Rust.

Reads and writes text, images, HTML, RTF and file lists, and keeps a searchable
history in SQLite with grouping, pagination and paste counts. Payloads over
100 KB are zstd-compressed.

The distribution is `j-clipboard`; the module imports as `pyclipboard`.

```python
import pyclipboard

pyclipboard.set_clipboard_text("hello")
print(pyclipboard.get_clipboard_text())

manager = pyclipboard.ClipboardManager()      # defaults to a per-user data dir
manager.add_item("hello")
for item in manager.get_history():
    print(item.content)
```

Windows x86_64 or ARM64, CPython 3.11+ (abi3). Part of
[jietuba](https://github.com/1003129155/jietuba). MIT licensed.

## Private clipboard protocol in the local screenshot-expansion checkout

The local source advertises `PRIVATE_CAPTURE_PROTOCOL = 1` on Windows.
The watcher rejects clipboard snapshots carrying `VersePic.PrivateCapture.v1`
or `ExcludeClipboardContentFromMonitorProcessing` before creating history
rows, raw-format records, image files, thumbnails or Python callbacks. It verifies
that the clipboard sequence did not change between its separate API reads and
discards mixed snapshots. Busy/unreadable checkpoints are not permission to save.
This applies to monitor ingestion; direct `add_item` calls are not made private.

This is local code, not a published j-clipboard release. Package version 0.4.2
alone does not prove protocol support. Application private-copy calls check the
capability and fail rather than falling back to ordinary unmarked copying.
Rebuild with the project's virtual-environment Python when testing this checkout:

```powershell
.\venv312\Scripts\python.exe -m pip install --no-deps --force-reinstall .\rust_libs\pyclipboard
```

The opt-in `main/tests/native_private_clipboard.py --run --output <empty-dir>`
uses a separate noninteractive Windows window station. If Windows denies station
creation, it exits before accessing clipboard contents; it never falls back to
the interactive clipboard. Unit checks are not a replacement for that native
acceptance. The single-capture UI and propagation into pins/redaction are separate
work and must not be described as delivered by this protocol alone.
