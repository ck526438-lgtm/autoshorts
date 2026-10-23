"""Word-level timings for captions.

Order of preference: real timings from the TTS engine (edge-tts and OpenAI
tts-1 streams report them for free), then local Whisper if the user installed
it, then a proportional estimator. All three produce the same shape, so the
caption generator never has to care where the clock came from.
"""

from __future__ import annotations

from pathlib import Path

from autoshorts.config import Settings
from autoshorts.models import Segment, Word
from autoshorts.util import log
from autoshorts.util.media import Tools, probe_duration

_PUNCT_PAUSE = {".": 1.9, "!": 1.9, "?": 1.9, ",": 1.35, ";": 1.25, ":": 1.15}


def estimate(text: str, total: float) -> list[Word]:
    """Distribute `total` seconds across words, weighting punctuation and length."""
    raw = text.split()
    if not raw or total <= 0:
        return []
    weights: list[float] = []
    for token in raw:
        weight = 1.0 + max(0, len(token.strip(".,!?;:"))) * 0.06
        last = token[-1] if token else ""
        weight *= _PUNCT_PAUSE.get(last, 1.0)
        weights.append(weight)
    scale = total / sum(weights)
    out: list[Word] = []
    cursor = 0.0
    for token, weight in zip(raw, weights, strict=True):
        word = token.strip(".,!?;:\"'()")
        duration = weight * scale
        if word:
            out.append(Word(word, round(cursor, 3), round(cursor + duration, 3)))
        cursor += duration
    return out


def from_whisper(audio: Path, settings: Settings, duration: float) -> list[Word] | None:
    model_name = settings.whisper_model or "small"
    language = None if settings.caption_language in ("", "auto") else settings.caption_language
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception:
        return None
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(str(audio), language=language, word_timestamps=True,
                                           condition_on_previous_text=False)
        words: list[Word] = []
        for piece in segments:
            for item in piece.words or []:
                text = (item.word or "").strip()
                if text:
                    words.append(Word(text, round(float(item.start), 3), round(float(item.end), 3)))
        return words or None
    except Exception as exc:
        log.warn(f"whisper alignment failed ({exc}); falling back to estimated timings")
        return None


def align_segment(
    segment: Segment,
    settings: Settings,
    tools: Tools,
    provided: list[Word] | None = None,
    audio: Path | None = None,
    offset: float = 0.0,
) -> list[Word]:
    """Attach an absolute (job-timeline) word clock to one segment."""
    duration = segment.duration or (probe_duration(tools, audio) if audio else 0.0)
    segment.duration = round(duration, 3)
    words = [w for w in (provided or []) if w.text]
    if not words and audio is not None:
        words = from_whisper(audio, settings, duration) or []
    if not words:
        words = estimate(segment.text, duration)
        log.debug(f"segment {segment.index}: estimated timings ({len(words)} words)")
    # Re-scale engine timings onto the measured audio so captions cannot drift.
    span = words[-1].end if words else 0.0
    if span > 0 and duration > 0 and abs(span - duration) > 0.35:
        factor = duration / span
        words = [Word(w.text, w.start * factor, min(duration, w.end * factor)) for w in words]
    return [
        Word(w.text, round(w.start + offset, 3), round(min(w.end + offset, offset + duration), 3))
        for w in words
    ]
