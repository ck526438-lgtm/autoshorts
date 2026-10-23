"""Cached HTTP downloads so re-runs never re-fetch the same b-roll."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

UA = "Mozilla/5.0 (compatible; AutoShorts/0.1; +https://github.com/ck526438-lgtm/autoshorts)"


def get_json(url: str, params: dict[str, Any] | None = None, timeout: float = 25.0) -> Any:
    try:
        with httpx.Client(
            timeout=timeout, headers={"User-Agent": UA}, follow_redirects=True
        ) as client:
            response = client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()
    except Exception as exc:  # network/API errors degrade the run, never crash it
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 180.0,
) -> Any:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(url, json=payload, headers=headers or {})
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def download(url: str, dest_dir: Path, referer: str = "") -> Path | None:
    """Stream `url` into dest_dir, keyed by its hash. Returns the local path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    suffix = Path(url.split("?")[0]).suffix or ".bin"
    target = dest_dir / f"{key}{suffix}"
    meta = dest_dir / f"{key}.json"
    if target.is_file() and target.stat().st_size > 1024:
        return target

    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                partial = target.with_suffix(target.suffix + ".part")
                with partial.open("wb") as fh:
                    for chunk in response.iter_bytes(1 << 16):
                        fh.write(chunk)
                partial.replace(target)
    except Exception:
        return None
    if target.stat().st_size < 1024:
        target.unlink(missing_ok=True)
        return None
    meta.write_text(
        json.dumps({"url": url, "fetched_at": int(time.time())}), encoding="utf-8"
    )
    return target
