"""Voiceover dispatch with a graceful fallback chain.

Never let a missing voice kill a run: `edge` -> `system` -> `silence`. The
`silence` track keeps timings honest, which is what captions actually need.
"""

from __future__ import annotations

from pathlib import Path

from autoshorts.config import Settings
from autoshorts.models import Word
from autoshorts.tts import providers
from autoshorts.util import log
from autoshorts.util.media import Tools

__all__ = ["synthesize", "providers", "TtsError"]
TtsError = providers.TtsError

_ORDER = ("edge", "openai", "piper", "system", "silence")


def _chain(requested: str, offline: bool = False) -> list[str]:
    requested = (requested or "edge").lower()
    fallbacks = [requested, "silence"]
    if not offline and requested != "edge":
        fallbacks.insert(1, "edge")
    if "system" not in fallbacks:
        fallbacks.insert(-1, "system")
    seen: list[str] = []
    for name in fallbacks:
        if name in providers.PROVIDERS and name not in seen:
            seen.append(name)
    return seen


def synthesize(
    text: str,
    settings: Settings,
    out: Path,
    tools: Tools,
    provider: str | None = None,
    offline: bool = False,
) -> tuple[list[Word], str]:
    out.parent.mkdir(parents=True, exist_ok=True)
    wanted = (provider or settings.tts_provider)
    errors: list[str] = []
    for name in _chain(wanted, offline=offline):
        try:
            words = providers.PROVIDERS[name](text, settings, out, tools)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            log.debug(f"tts {name} failed — {exc}")
            continue
        if out.is_file() and out.stat().st_size > 512:
            if name != wanted:
                log.warn(f"voiceover used fallback engine {name!r}")
            else:
                log.debug(f"voiceover via {name}")
            return list(words), name
        errors.append(f"{name}: no audio written")
    raise TtsError("no voice engine available:\n  " + "\n  ".join(errors))
