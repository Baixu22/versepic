# j-gif

Screen recording to GIF for Python, implemented in Rust.

Frames are captured through Win32 GDI (BitBlt), compressed to JPEG and kept in a
native frame store, then encoded to GIF -- all on native threads, so the GIL is
never held during recording or export.

- `FrameStore` -- accepts BGRA/RGB frames, stores them JPEG-compressed, exports GIF
- `FrameDecoder` -- background decoding for playback over a bounded channel
- `RecordSession` -- recording state machine (recording / paused / stopped)

The distribution is `j-gif`; the module imports as `gifrecorder`.

```python
import gifrecorder

store = gifrecorder.FrameStore(width, height, fps, jpeg_quality=90)
store.push_bgra(bgra_bytes, elapsed_ms)      # once per captured frame
store.export_gif("out.gif", repeat=0)
```

Playback can start directly at a frame without decoding earlier JPEGs:

```python
decoder = store.start_decoder(display_w=640, display_h=360, start_frame=100)
try:
    frame = decoder.next_frame()  # (RGB bytes, original elapsed_ms), or None
finally:
    decoder.stop()
```

`start_frame` defaults to zero. An index at or beyond the end produces an empty
decoder. `total_frames` counts frames from the chosen start to the end, and
`fetched_count` starts at zero. Timestamps remain relative to the original recording.
This parameter is available in j-gif 0.3.1 and later.

Windows x86_64 or ARM64, CPython 3.11+ (abi3). Part of
[jietuba](https://github.com/1003129155/jietuba). MIT licensed.

## Local screenshot-expansion checkout

This checkout extends `FrameStore.export_gif` with `fps=0` (preserve timing,
subject to GIF's 20 ms minimum delay) and an optional maximum output rate from
1 to 50. Frames are dropped rather than duplicated. Absolute timeline boundaries
are rounded to centiseconds, preserving total speed-adjusted duration to within
5 ms, except clips shorter than 20 ms. A recording's last frame has no stop
timestamp; its last positive interval is reused, falling back to source FPS.

`frame_end=None` means the last frame; an explicit `frame_end=0` now means
only the first frame. Trim endpoints are inclusive and invalid ranges fail.
Odd output dimensions are supported, bounded to 16 megapixels and 65535 per edge.
Long holds are split across GIF delay blocks instead of overflowing u16.

These changes are local source, **not a published j-gif release**. The package
version is still 0.3.1; a version check alone does not establish this capability.
Build/install this checkout's module in the application's virtual environment:

```powershell
.\venv312\Scripts\python.exe -m pip install --no-deps --force-reinstall .\rust_libs\gifrecorder
```

The application checks for the new `fps` interface and disables export with an
explicit message if an older binary is loaded. Application exports stage files
through SaveService and atomically commit only success; calling the low-level
`export_gif` method directly is not an atomic overwrite API.
