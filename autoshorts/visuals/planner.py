"""B-roll planning: for every segment, find one shot that exists on disk.

Priority chain is configurable (`STOCK_PRIORITY=pexels,pixabay,local,procedural`)
and every level degrades instead of failing, because a render that dies at the
last step is worse than a render with generated backgrounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoshorts.config import Niche, Settings
from autoshorts.models import Media, Segment
from autoshorts.util import http, log
from autoshorts.util.media import Tools, probe_duration
from autoshorts.visuals import local, pexels, pixabay, procedural

_GENERIC = "cinematic abstract motion background dark"


@dataclass
class MediaPlan:
    assigned: int = 0
    by_provider: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def bump(self, provider: str) -> None:
        self.assigned += 1
        self.by_provider[provider] = self.by_provider.get(provider, 0) + 1


def _search(name: str, query: str, settings: Settings) -> list[dict[str, Any]]:
    if name == "pexels":
        return pexels.search(query, settings.pexels_api_key, _orientation(settings))
    if name == "pixabay":
        return pixabay.search(query, settings.pixabay_api_key, _orientation(settings))
    if name == "local":
        folder = settings.local_clips_dir or Path("assets/clips")
        return local.candidates(folder, query)
    return []


def _orientation(settings: Settings) -> str:
    if settings.stock_orientation in {"portrait", "landscape", "square", "any"}:
        return settings.stock_orientation
    return "portrait" if settings.vertical else "landscape"


def _materialise(candidate: dict[str, Any], settings: Settings, tools: Tools) -> Media | None:
    if candidate.get("local_path"):
        path = Path(candidate["local_path"])
    else:
        path = http.download(candidate["url"], settings.download_dir, referer=candidate.get("referrer", ""))
        if path is None:
            return None
    duration = float(candidate.get("duration") or 0.0)
    if candidate["kind"] == "video" and not duration:
        duration = probe_duration(tools, path)
    return Media(
        kind=candidate["kind"],
        source=str(path),
        label=candidate.get("label", ""),
        provider=candidate.get("provider", ""),
        duration=duration,
    )


def plan_media(
    segments: list[Segment],
    settings: Settings,
    tools: Tools,
    niche: Niche | None = None,
    topic: str = "",
) -> MediaPlan:
    niche = niche or Niche()
    plan = MediaPlan()
    used: set[str] = set()
    chain = [p for p in settings.stock_priority if p != "procedural"]
    queries = [topic, *niche.keywords] if topic else list(niche.keywords)

    for position, segment in enumerate(segments):
        needed = max(1.0, segment.duration or 2.0)
        search_terms = [segment.visual_query, *[q for q in queries if q], _GENERIC]
        placed: Media | None = None
        for term in [t for t in search_terms if t][:3]:
            for provider in chain:
                for candidate in _search(provider, term, settings)[:8]:
                    if candidate["label"] in used:
                        continue
                    if candidate["kind"] == "video" and 0 < candidate.get("duration", 0) < needed * 0.6:
                        continue
                    placed = _materialise(candidate, settings, tools)
                    if placed:
                        used.add(candidate["label"])
                        break
                if placed:
                    break
            if placed:
                break
        if placed is None:
            art = settings.download_dir / "generated" / f"seg_{segment.index:03d}.png"
            procedural.generate(segment.visual_query or topic or str(position), art,
                                settings.width, settings.height, variant=position)
            placed = Media(kind="image", source=str(art), label=art.name,
                           provider="procedural", duration=0.0)
            plan.notes.append(f"segment {segment.index}: generated art (no stock hit for {segment.visual_query!r})")
        segment.media = placed
        plan.bump(placed.provider)
        log.debug(f"seg {segment.index:02d} ← {placed.provider}:{placed.label}")
    return plan
