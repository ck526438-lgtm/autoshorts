"""Your own footage folder — the provider that keeps a channel on-brand."""

from __future__ import annotations

from pathlib import Path
from typing import Any

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def candidates(folder: Path, query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Rank files by keyword overlap with the segment's visual query."""
    if not folder.is_dir():
        return []
    tokens = {t.lower() for t in query.split() if len(t) > 2}
    scored: list[tuple[int, int, Path]] = []
    for order, path in enumerate(sorted(folder.iterdir())):
        if path.suffix.lower() not in VIDEO_EXT | IMAGE_EXT:
            continue
        stem = path.stem.lower().replace("_", " ").replace("-", " ")
        score = sum(1 for token in tokens if token in stem)
        scored.append((-score, order, path))
    scored.sort()
    out: list[dict[str, Any]] = []
    for _, _, path in scored[:limit]:
        out.append({
            "kind": "video" if path.suffix.lower() in VIDEO_EXT else "image",
            "url": path.resolve().as_uri(),
            "referrer": "",
            "label": path.name,
            "duration": 0.0,
            "provider": "local",
            "local_path": str(path.resolve()),
        })
    return out
