"""Runtime configuration: `.env` + niche YAML + CLI overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

try:  # optional at runtime; settings still work with plain env vars
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*_a: Any, **_k: Any) -> bool:
        return False

DEFAULTS: dict[str, str] = {
    "LLM_PROVIDER": "template",
    "LLM_MODEL": "",
    "LLM_TEMPERATURE": "0.8",
    "TTS_PROVIDER": "edge",
    "TTS_RATE": "+8%",
    "EDGE_VOICE": "en-US-GuyNeural",
    "PIPER_VOICE": "en_US-lessac-medium",
    "PIPER_BIN": "piper",
    "STOCK_PRIORITY": "procedural",
    "STOCK_ORIENTATION": "portrait",
    "DOWNLOAD_DIR": "cache/media",
    "LOCAL_CLIPS_DIR": "assets/clips",
    "VIDEO_WIDTH": "1080",
    "VIDEO_HEIGHT": "1920",
    "VIDEO_FPS": "30",
    "TARGET_SECONDS": "45",
    "CAPTION_LANGUAGE": "auto",
    "CAPTION_FONT": "Arial Black",
    "CAPTION_HIGHLIGHT_COLOR": "#FFE81A",
    "CAPTION_BASE_COLOR": "#FFFFFF",
    "CLIP_LOOK": "natural",
    "MUSIC_VOLUME": "0.16",
    "OUTPUT_DIR": "output",
    "LOG_LEVEL": "INFO",
    "WHISPER_MODEL": "small",
}


def _s(env: Mapping[str, str], key: str) -> str:
    return (env.get(key) or DEFAULTS.get(key) or "").strip()


def _i(env: Mapping[str, str], key: str) -> int:
    return int(float(_s(env, key) or 0))


def _f(env: Mapping[str, str], key: str) -> float:
    return float(_s(env, key) or 0.0)


def _b(env: Mapping[str, str], key: str) -> bool:
    return _s(env, key).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # script
    llm_provider: str = "template"
    llm_model: str = ""
    llm_temperature: float = 0.8
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    # voice
    tts_provider: str = "edge"
    tts_rate: str = "+8%"
    edge_voice: str = "en-US-GuyNeural"
    openai_tts_voice: str = "alloy"
    piper_voice: str = "en_US-lessac-medium"
    piper_bin: str = "piper"
    whisper_model: str = "small"
    # visuals
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    stock_priority: tuple[str, ...] = ("procedural",)
    stock_orientation: str = "portrait"
    download_dir: Path = Path("cache/media")
    local_clips_dir: Path | None = None
    # look
    width: int = 1080
    height: int = 1920
    fps: int = 30
    target_seconds: int = 45
    caption_language: str = "auto"
    caption_font: str = "Arial Black"
    caption_highlight: str = "#FFE81A"
    caption_base: str = "#FFFFFF"
    ken_burns: bool = True
    clip_look: str = "natural"
    music_file: Path | None = None
    music_volume: float = 0.16
    # plumbing
    output_dir: Path = Path("output")
    log_level: str = "INFO"
    ffmpeg_bin: str = ""
    ffprobe_bin: str = ""

    @property
    def vertical(self) -> bool:
        return self.height >= self.width

    @property
    def words_per_minute(self) -> int:
        """Speech rate implied by `TTS_RATE`, used to budget script length."""
        raw = self.tts_rate.replace("%", "").replace("+", "").strip()
        try:
            pct = float(raw or 0)
        except ValueError:
            pct = 0.0
        return int(150 * (1 + pct / 100))


@dataclass
class Niche:
    """A reusable 'channel brief' — tone, audience, recurring keywords."""

    name: str = "general"
    language: str = "en"
    persona: str = "a sharp, no-nonsense narrator"
    audience: str = "curious scrollers"
    tone: str = "punchy, concrete, zero fluff"
    duration: int = 45
    hook_styles: tuple[str, ...] = ()
    beats: tuple[str, ...] = ()
    banned: tuple[str, ...] = ("very", "actually", "in conclusion")
    hashtags: tuple[str, ...] = ()
    visual_style: str = "cinematic b-roll, moody lighting"
    keywords: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None) -> Niche:
        if not path:
            return cls()
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key == "extra":
                kwargs["extra"] = dict(value or {})
            elif key in known:
                if isinstance(value, list):
                    value = tuple(value)
                kwargs[key] = value
        return cls(**kwargs)

    def brief(self) -> str:
        lines = [
            f"Channel: {self.name}",
            f"Language: {self.language}",
            f"Narrator: {self.persona}",
            f"Audience: {self.audience}",
            f"Tone: {self.tone}",
            f"Visual style: {self.visual_style}",
        ]
        if self.hook_styles:
            lines.append("Preferred hooks: " + " | ".join(self.hook_styles))
        if self.banned:
            lines.append("Never use: " + ", ".join(self.banned))
        return "\n".join(lines)


def build_settings(
    env_file: str | Path | None = None,
    niche: Niche | None = None,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    env: dict[str, str] = dict(DEFAULTS)
    dotenv_path = Path(env_file) if env_file else Path.cwd() / ".env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path, override=False)
    raw = dict(os.environ) if environ is None else dict(environ)
    env.update({k: v for k, v in raw.items() if v is not None})

    priority = [p.strip() for p in _s(env, "STOCK_PRIORITY").split(",") if p.strip()]
    music = _s(env, "MUSIC_FILE")
    settings = Settings(
        llm_provider=_s(env, "LLM_PROVIDER").lower(),
        llm_model=_s(env, "LLM_MODEL"),
        llm_temperature=_f(env, "LLM_TEMPERATURE") or 0.8,
        openai_api_key=raw.get("OPENAI_API_KEY", ""),
        anthropic_api_key=raw.get("ANTHROPIC_API_KEY", ""),
        ollama_base_url=_s(env, "OLLAMA_BASE_URL") or "http://127.0.0.1:11434",
        tts_provider=_s(env, "TTS_PROVIDER").lower(),
        tts_rate=_s(env, "TTS_RATE"),
        edge_voice=_s(env, "EDGE_VOICE"),
        openai_tts_voice=_s(env, "OPENAI_TTS_VOICE") or "alloy",
        piper_voice=_s(env, "PIPER_VOICE"),
        piper_bin=_s(env, "PIPER_BIN"),
        whisper_model=_s(env, "WHISPER_MODEL"),
        pexels_api_key=raw.get("PEXELS_API_KEY", ""),
        pixabay_api_key=raw.get("PIXABAY_API_KEY", ""),
        stock_priority=tuple(priority) or ("procedural",),
        stock_orientation=_s(env, "STOCK_ORIENTATION"),
        download_dir=Path(_s(env, "DOWNLOAD_DIR")),
        local_clips_dir=Path(_s(env, "LOCAL_CLIPS_DIR")),
        width=_i(env, "VIDEO_WIDTH"),
        height=_i(env, "VIDEO_HEIGHT"),
        fps=_i(env, "VIDEO_FPS") or 30,
        target_seconds=_i(env, "TARGET_SECONDS"),
        caption_language=_s(env, "CAPTION_LANGUAGE"),
        caption_font=_s(env, "CAPTION_FONT"),
        caption_highlight=_s(env, "CAPTION_HIGHLIGHT_COLOR"),
        caption_base=_s(env, "CAPTION_BASE_COLOR"),
        ken_burns=_b(env, "IMAGE_KEN_BURNS") or _s(env, "IMAGE_KEN_BURNS") == "",
        clip_look=_s(env, "CLIP_LOOK"),
        music_file=Path(music) if music else None,
        music_volume=_f(env, "MUSIC_VOLUME"),
        output_dir=Path(_s(env, "OUTPUT_DIR")),
        log_level=_s(env, "LOG_LEVEL").upper(),
        ffmpeg_bin=_s(env, "FFMPEG_BIN"),
        ffprobe_bin=_s(env, "FFPROBE_BIN"),
    )

    if niche:
        settings = replace(
            settings,
            target_seconds=niche.duration or settings.target_seconds,
            caption_language=settings.caption_language
            if settings.caption_language != "auto"
            else niche.language,
        )
    if overrides:
        clean = {k: v for k, v in overrides.items() if v not in (None, "")}
        if clean:
            settings = replace(settings, **clean)
    return settings
