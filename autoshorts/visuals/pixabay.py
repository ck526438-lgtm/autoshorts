"""Pixabay: free API, useful when Pexels comes back thin (or the other way)."""

from __future__ import annotations

from typing import Any

from autoshorts.util import http

VIDEO_SEARCH = "https://pixabay.com/api/videos/"
PHOTO_SEARCH = "https://pixabay.com/api/"


def _pick_quality(videos: dict[str, Any], min_height: int) -> dict[str, Any] | None:
    ordered = [videos.get(k) for k in ("large", "medium", "small", "tiny")]
    ordered = [v for v in ordered if isinstance(v, dict) and v.get("url")]
    tall = [v for v in ordered if int(v.get("height") or 0) >= min_height]
    pool = tall or ordered
    return pool[0] if pool else None


def search(query: str, key: str, orientation: str = "portrait", min_height: int = 1080,
           per_page: int = 6) -> list[dict[str, Any]]:
    if not key:
        return []
    results: list[dict[str, Any]] = []
    params = {"key": key, "q": query, "per_page": per_page, "safesearch": "true"}
    if orientation == "vertical":
        params["min_height"] = min_height
    payload = http.get_json(VIDEO_SEARCH, params=params)
    if isinstance(payload, dict) and "__error__" not in payload:
        for item in payload.get("hits") or []:
            chosen = _pick_quality(item.get("videos") or {}, min_height)
            if not chosen:
                continue
            results.append({
                "kind": "video",
                "url": chosen["url"],
                "referrer": item.get("pageURL", "https://pixabay.com/"),
                "label": f"pixabay:{item.get('id')}",
                "duration": float(item.get("duration") or 0),
                "provider": "pixabay",
            })
    photos = http.get_json(PHOTO_SEARCH, params={**params, "image_type": "photo"})
    if isinstance(photos, dict) and "__error__" not in photos:
        for item in photos.get("hits") or []:
            url = item.get("largeImageURL") or item.get("webformatURL")
            if not url:
                continue
            results.append({
                "kind": "image",
                "url": url,
                "referrer": item.get("pageURL", "https://pixabay.com/"),
                "label": f"pixabay:{item.get('id')}",
                "duration": 0.0,
                "provider": "pixabay",
            })
    return results
