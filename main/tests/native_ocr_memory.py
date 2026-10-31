# -*- coding: utf-8 -*-
r"""Opt-in real PP-OCR memory regression against current models.

Runs a large real screenshot through OCRManager three times, samples the
process Private Bytes before/after each run, and fails unless the engine is
closed and memory stays below an explicit ceiling. This is deliberately a
native opt-in check, not part of the GUI-only pytest matrix.

Usage:
    venv312\Scripts\python.exe main\tests\native_ocr_memory.py --run \
        --image C:\path\to\large.png --output .ui_review\ocr-memory
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "main"))

DEFAULT_IMAGE = ROOT / "main" / "tests" / "fixtures" / "ocr_memory_probe.png"
MAX_PRIVATE_MB = 180.0
MAX_GROWTH_MB = 80.0

class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]

def private_mb() -> float:
    psapi = ctypes.WinDLL("psapi")
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    current = ctypes.windll.kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(current, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PrivateUsage / (1024 * 1024)

def _baseline(manager) -> float:
    """A fresh process has no native engine, so this also guards test setup."""
    if manager.is_engine_loaded():
        raise AssertionError("ppocr_rust engine was already loaded before the measurement")
    return private_mb()

def run(image_path: Path, output: Path, runs: int = 3) -> dict:
    from ocr import ocr_manager as om

    manager = om.OCRManager()
    manager._current_engine = om.OCRManager.ENGINE_PP_RUST
    output.mkdir(parents=True, exist_ok=True)
    before = _baseline(manager)
    samples = [{"stage": "before", "private_mb": before, "engine_loaded": manager.is_engine_loaded()}]
    for index in range(runs):
        from PySide6.QtGui import QImage
        image = QImage(str(image_path))
        if image.isNull():
            raise RuntimeError(f"Could not load image: {image_path}")
        image_size = [image.width(), image.height()]
        started = time.perf_counter()
        result = manager._recognize_with_ppocr_rust(image, "dict")
        elapsed = time.perf_counter() - started
        if not isinstance(result, dict) or result.get("code") != 100:
            raise RuntimeError(f"OCR failed on run {index + 1}: {result}")
        sample = {
            "stage": f"run_{index + 1}",
            "private_mb": private_mb(),
            "engine_loaded": manager.is_engine_loaded(),
            "elapsed_s": round(elapsed, 3),
            "lines": len(result.get("data", [])),
        }
        samples.append(sample)
        print(json.dumps(sample, ensure_ascii=False))
        if sample["engine_loaded"]:
            raise AssertionError("ppocr_rust engine stayed loaded after recognition")
    after = private_mb()
    growth = after - samples[0]["private_mb"]
    report = {
        "image": str(image_path),
        "image_size": image_size,
        "samples": samples,
        "final_private_mb": round(after, 1),
        "growth_mb": round(growth, 1),
        "max_private_mb": MAX_PRIVATE_MB,
        "max_growth_mb": MAX_GROWTH_MB,
        "passed": after <= MAX_PRIVATE_MB and growth <= MAX_GROWTH_MB,
    }
    (output / "result.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["passed"]:
        raise AssertionError(f"Memory regression: {after:.1f} MB after OCR (limit {MAX_PRIVATE_MB} MB)")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true", help="actually run OCR")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--output", type=Path, default=ROOT / ".ui_review" / "ocr-memory")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    run(args.image, args.output, max(1, args.runs))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
