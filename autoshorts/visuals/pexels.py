"""Pexels: free API, best portrait b-roll library, no attribution required."""

from __future__ import annotations

from typing import Any

from autoshorts.util import http

VIDEO_SEARCH = "https://api.pexels.com/videos/search"
PHOTO_SEARCH = "https://api.pexels.com/v1/search"


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": key, "User-Agent": "autoshorts/0.1"}


def _best_video_file(files: list[dict[str, Any]], min_height: int) -> dict[str, Any] | None:
    candidates = [f for f in files if f.get("link")]
    if not candidates:
        return None
    tall = [f for f in candidates if int(f.get("height") or 0) >= min_height]
    pool = tall or candidates
    return sorted(pool, key=lambda f: int(f.get("width") or 0) * int(f.get("height") or 0))[-1]


def search(query: str, key: str, orientation: str = "portrait", min_height: int = 1080,
           per_page: int = 6) -> list[dict[str, Any]]:
    """Return [{kind,url,referrer,label,duration,provider}] newest-match first."""
    if not key:
        return []
    results: list[dict[str, Any]] = []
    payload = http.get_json(
        VIDEO_SEARCH,
        params={"query": query, "per_page": per_page, "orientation": orientation, "size": "large"},
    )
    if isinstance(payload, dict) and "__error__" not in payload:
        for item in payload.get("videos") or []:
            chosen = _best_video_file(item.get("video_files") or [], min_height)
            if not chosen:
                continue
            results.append({
                "kind": "video",
                "url": chosen["link"],
                "referrer": item.get("url", "https://www.pexels.com/"),
                "label": f"pexels:{item.get('id')}",
                "duration": float(item.get("duration") or 0),
                "provider": "pexels",
            })
    photos = http.get_json(PHOTO_SEARCH, params={"query": query, "per_page": per_page, "orientation": orientation})
    if isinstance(photos, dict) and "__error__" not in photos:
        for item in photos.get("photos") or []:
            url = (item.get("src") or {}).get("large2x") or (item.get("src") or {}).get("large")
            if not url:
                continue
            results.append({
                "kind": "image",
                "url": url,
                "referrer": item.get("url", "https://www.pexels.com/"),
                "label": f"pexels:{item.get('id')}",
                "duration": 0.0,
                "provider": "pexels",
            })
    return results
