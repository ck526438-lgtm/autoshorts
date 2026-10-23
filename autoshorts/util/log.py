"""Tiny logging helper so CLI output stays readable without a logging framework."""

from __future__ import annotations

import os
import sys
import time

LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_started = time.time()


def _use_utf8_streams() -> None:
    """Windows pipes default to cp1252, which crashes on the status glyphs.

    Reconfiguring once here means every module can print ✓/• without guarding.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_use_utf8_streams()


def set_level(name: str) -> None:
    os.environ["AUTOSHORTS_LOG_LEVEL"] = (name or "INFO").upper()


def _level() -> int:
    return LEVELS.get(os.environ.get("AUTOSHORTS_LOG_LEVEL", "INFO"), 20)


def _emit(symbol: str, message: str, level: int) -> None:
    if _level() <= level:
        stream = sys.stderr if level >= 40 else sys.stdout
        print(f"{symbol} {message}", file=stream, flush=True)


def debug(message: str) -> None:
    _emit("·", message, 10)


def info(message: str) -> None:
    _emit("•", message, 20)


def ok(message: str) -> None:
    _emit("✓", message, 20)


def warn(message: str) -> None:
    _emit("!", message, 30)


def error(message: str) -> None:
    _emit("✗", message, 40)


def step(n: int, total: int, message: str) -> None:
    _emit(f"[{n}/{total}]", message, 20)


def elapsed() -> str:
    return f"{time.time() - _started:.1f}s"
