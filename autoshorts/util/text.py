"""Text utilities: sentence splitting, word tokens, duration budgets."""

from __future__ import annotations

import re
import unicodedata

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e", "u.s", "uk",
    "m.", "pt.", "approx", "inc", "ltd", "jr", "sr",
}
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
_WS_RE = re.compile(r"[ \t\u00a0]+")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_SMART_QUOTES = {
    "“": '"', "”": '"', "‘": "'", "’": "'", " ": " ", "–": "-", "—": "-",
}


def clean(text: str) -> str:
    """Normalise whitespace, smart quotes and stray markdown from LLM output."""
    for bad, good in _SMART_QUOTES.items():
        text = text.replace(bad, good)
    text = re.sub(r"\*\*?|__?", "", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def slugify(text: str, maxlen: int = 48) -> str:
    raw = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = _SLUG_RE.sub("-", raw.lower()).strip("-")
    return slug[:maxlen].rstrip("-") or "clip"


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def word_count(text: str) -> int:
    return len(words(text))


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for chunk in _SENT_SPLIT.split(clean(text)):
        piece = (chunk or "").strip()
        if not piece:
            continue
        if out and _looks_truncated(out[-1], piece):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def _looks_truncated(previous: str, following: str) -> bool:
    """True when `previous` ends on an abbreviation, not a real sentence end."""
    tail = previous.rstrip()
    if not tail.endswith("."):
        return False
    last = tail.split(" ")[-1].strip(".").lower()
    return last in _ABBREVIATIONS or (len(last) <= 2 and last.isalpha())


def estimate_seconds(text: str, words_per_minute: int = 150) -> float:
    """Rough narration budget: 150 wpm plus a beat per sentence."""
    per_word = 60.0 / max(60, words_per_minute)
    total = word_count(text) * per_word
    total += max(0, len(sentences(text)) - 1) * 0.22
    return round(total, 2)


def chunk_text(text: str, max_seconds: float, words_per_minute: int = 150) -> list[str]:
    """Split narration into TTS-sized blocks that each stay under `max_seconds`."""
    blocks: list[str] = []
    budget_words = max(4, int(max_seconds * words_per_minute / 60.0))
    for sentence in sentences(text) or ([clean(text)] if clean(text) else []):
        if blocks and word_count(" ".join([blocks[-1], sentence])) <= budget_words:
            blocks[-1] = f"{blocks[-1]} {sentence}"
        else:
            blocks.append(sentence)
    return [b for b in blocks if b]
