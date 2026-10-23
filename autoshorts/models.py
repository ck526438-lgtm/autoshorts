"""Shared data structures passed between pipeline stages."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Word:
    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Media:
    kind: str  # "video" | "image"
    source: str  # local path once downloaded
    label: str = ""
    provider: str = ""
    duration: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Media:
        return cls(
            kind=data["kind"],
            source=data["source"],
            label=data.get("label", ""),
            provider=data.get("provider", ""),
            duration=float(data.get("duration", 0.0)),
        )


@dataclass
class Segment:
    index: int
    text: str
    visual_query: str = ""
    audio_path: str = ""
    duration: float = 0.0
    words: list[Word] = field(default_factory=list)
    media: Media | None = None
    clip_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["words"] = [{"text": w.text, "start": w.start, "end": w.end} for w in self.words]
        data["media"] = asdict(self.media) if self.media else None
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        return cls(
            index=int(data["index"]),
            text=data["text"],
            visual_query=data.get("visual_query", ""),
            audio_path=data.get("audio_path", ""),
            duration=float(data.get("duration", 0.0)),
            words=[Word(w["text"], float(w["start"]), float(w["end"])) for w in data.get("words", [])],
            media=Media.from_dict(data["media"]) if data.get("media") else None,
            clip_path=data.get("clip_path", ""),
        )


@dataclass
class Script:
    topic: str
    title: str
    hook: str
    segments: list[Segment]
    cta: str = ""
    language: str = "en"
    hashtags: list[str] = field(default_factory=list)
    provider: str = ""

    @property
    def narration(self) -> str:
        return " ".join(seg.text for seg in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "title": self.title,
            "hook": self.hook,
            "cta": self.cta,
            "language": self.language,
            "hashtags": self.hashtags,
            "provider": self.provider,
            "segments": [seg.to_dict() for seg in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Script:
        return cls(
            topic=data.get("topic", ""),
            title=data.get("title", ""),
            hook=data.get("hook", ""),
            cta=data.get("cta", ""),
            language=data.get("language", "en"),
            hashtags=list(data.get("hashtags", [])),
            provider=data.get("provider", ""),
            segments=[Segment.from_dict(s) for s in data.get("segments", [])],
        )


@dataclass
class JobPaths:
    """Every artefact of one rendered short, on disk, resumable."""

    root: Path

    def __post_init__(self) -> None:
        for name in ("audio", "clips", "work"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @property
    def script(self) -> Path:
        return self.root / "script.json"

    @property
    def plan(self) -> Path:
        return self.root / "plan.json"

    @property
    def captions(self) -> Path:
        return self.root / "captions.ass"

    @property
    def base_video(self) -> Path:
        return self.root / "work" / "video_base.mp4"

    @property
    def voice(self) -> Path:
        return self.root / "work" / "voice.wav"

    @property
    def final(self) -> Path:
        return self.root / "final.mp4"

    @property
    def metadata(self) -> Path:
        return self.root / "metadata.json"

    def segment_audio(self, index: int) -> Path:
        return self.root / "audio" / f"seg_{index:03d}.wav"

    def segment_clip(self, index: int) -> Path:
        return self.root / "clips" / f"seg_{index:03d}.mp4"

    def save(self, payload: dict[str, Any], path: Path) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
