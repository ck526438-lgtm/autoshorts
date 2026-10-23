"""ffmpeg/ffprobe discovery + safe command execution.

Auto-detection order: explicit env/setting -> PATH -> `imageio-ffmpeg` wheel ->
common install folders. This matters most on Windows, where ffmpeg is usually
missing and the wheel is the least painful fix.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FfmpegNotFound(RuntimeError):
    pass


class FfmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tools:
    ffmpeg: Path
    ffprobe: Path | None
    source: str

    def describe(self) -> str:
        return f"{self.ffmpeg} ({self.source})"


_EXTRA_DIRS = (
    r"C:\ffmpeg\bin",
    r"C:\Program Files\ffmpeg\bin",
    r"C:\Program Files (x86)\ffmpeg\bin",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"),
    os.path.expanduser(r"~\scoop\apps\ffmpeg\current\bin"),
    os.path.expanduser(r"~\AppData\Local\Programs\ffmpeg\bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
)


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def _from_imageio(name: str) -> Path | None:
    try:
        import imageio_ffmpeg  # type: ignore

        root = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None
    if name == "ffmpeg":
        return root if root.is_file() else None
    sibling = root.with_name(_exe("ffprobe"))
    return sibling if sibling.is_file() else None


def _search(name: str, explicit: str = "") -> tuple[Path | None, str]:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate, "configured"
        found = shutil.which(explicit)
        if found:
            return Path(found), "configured"
    found = shutil.which(name)
    if found:
        return Path(found), "PATH"
    from_path = _from_imageio(name)
    if from_path:
        return from_path, "imageio-ffmpeg"
    for base in _EXTRA_DIRS:
        root = Path(base)
        if not root.is_dir():
            continue
        for hit in (root / _exe(name), *sorted(root.rglob(_exe(name)))[:1]):
            if hit.is_file():
                return hit, f"scan:{root}"
    return None, ""


def resolve(ffmpeg: str = "", ffprobe: str = "") -> Tools:
    ffmpeg_path, source = _search("ffmpeg", ffmpeg)
    if ffmpeg_path is None:
        raise FfmpegNotFound(
            "ffmpeg was not found.\n"
            "  • Windows / any OS:  pip install \"autoshorts[ffmpeg]\"\n"
            "  • macOS:  brew install ffmpeg\n"
            "  • Debian/Ubuntu:  sudo apt install ffmpeg\n"
            "  • or set FFMPEG_BIN=/path/to/ffmpeg in your .env"
        )
    probe_path, _ = _search("ffprobe", ffprobe)
    return Tools(ffmpeg=ffmpeg_path, ffprobe=probe_path, source=source or "PATH")


def run(args: list[str | Path], *, quiet: bool = True, timeout: int = 1800,
        cwd: Path | None = None) -> str:
    cmd = [str(a) for a in args]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    output = proc.stdout or ""
    if proc.returncode != 0:
        tail = "\n".join(output.strip().splitlines()[-12:])
        raise FfmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    return output if not quiet else ""


def probe_duration(tools: Tools, path: Path) -> float:
    if tools.ffprobe is None:
        return _duration_from_log(tools, path)
    proc = subprocess.run(
        [str(tools.ffprobe), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace",
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}),
    )
    try:
        return float((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return _duration_from_log(tools, path)


def _duration_from_log(tools: Tools, path: Path) -> float:
    """Fallback when no ffprobe ships next to ffmpeg."""
    try:
        out = run([tools.ffmpeg, "-hide_banner", "-i", path], timeout=60, quiet=False)
    except FfmpegError as exc:
        out = str(exc)
    import re

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", out or "")
    if not match:
        return 0.0
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


_CAPS: dict[str, set[str]] = {}


_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _parse_listing(text: str) -> set[str]:
    """Names from `ffmpeg -encoders` / `-filters`, skipping the legends.

    Both listings indent differently across builds, so parsing the columns
    rather than the leading whitespace is what keeps `ass` from being wrongly
    reported as missing (that used to silently disable burned captions).
    """
    names: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].startswith("="):
            continue
        candidate = parts[1]
        if _NAME_RE.match(candidate):
            names.add(candidate)
    return names


def _capabilities(tools: Tools) -> dict[str, set[str]]:
    if not _CAPS:
        encoders: set[str] = set()
        filters: set[str] = set()
        try:
            encoders = _parse_listing(
                run([tools.ffmpeg, "-hide_banner", "-encoders"], timeout=120, quiet=False))
            filters = _parse_listing(
                run([tools.ffmpeg, "-hide_banner", "-filters"], timeout=120, quiet=False))
        except Exception:
            pass
        _CAPS["encoders"] = encoders
        _CAPS["filters"] = filters
    return _CAPS


def has_encoder(tools: Tools, name: str) -> bool:
    return name in _capabilities(tools).get("encoders", set())


def has_filter(tools: Tools, name: str) -> bool:
    return name in _capabilities(tools).get("filters", set())


def pick_video_encoder(tools: Tools) -> str:
    for candidate in ("libx264", "libopenh264", "h264_nvenc", "mpeg4"):
        if has_encoder(tools, candidate):
            return candidate
    return "libx264"  # let ffmpeg report the real error if the build is exotic


def concat_list(list_path: Path, files: list[Path]) -> Path:
    lines = ["ffconcat version 1.0"]
    for item in files:
        # The concat demuxer quotes paths with single quotes and unescapes `\'`.
        safe = str(item.resolve()).replace("\\", "/").replace("'", "\\'")
        lines.append(f"file '{safe}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_path
