"""Offline script writer — no key, no network.

Structure is real (hook / escalation / CTA) but the substance is generic on
purpose: it exists so `pip install` → `autoshorts demo` works, and so runs
continue when an API is down. Point `LLM_PROVIDER` at a model for actual copy.
"""

from __future__ import annotations

import hashlib
import random

from autoshorts.config import Niche, Settings
from autoshorts.models import Script, Segment
from autoshorts.util import text as T

_HOOKS = [
    "Most people get {topic} backwards. Here is the fix.",
    "The {topic} advice nobody repeats out loud.",
    "If {topic} feels slow, you are skipping one step.",
    "{Topic} in {seconds} seconds, no fluff.",
    "Stop optimising {topic}. Do this instead.",
]

_BEATS = [
    "Start with the smallest version of {topic} you can finish today.",
    "Write down what done looks like, then work backwards from it.",
    "Cut anything that does not move that number this week.",
    "Do the boring repeat for fourteen days before changing a thing.",
    "Track one signal, ignore the other nine.",
    "Ship the rough version. Feedback is cheaper than planning.",
    "Every session, remove one step instead of adding one.",
]

_CTAS = [
    "Follow for the next one, it goes deeper.",
    "Comment the word start if you want the full breakdown.",
    "Save this before you forget the first step.",
]

_GENERIC_QUERIES = [
    "close up hands writing notebook desk",
    "city timelapse night traffic",
    "person working laptop morning light",
    "minimal desk coffee overhead",
    "slow motion pouring water studio",
    "walking first pov urban street",
]


def _pick(options: list[str], topic: str, offset: int = 0) -> str:
    digest = hashlib.sha1(f"{topic}:{offset}".encode()).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def build(topic: str, niche: Niche, settings: Settings, max_words: int) -> Script:
    rng = random.Random(f"{topic}|{niche.name}")
    seconds = settings.target_seconds
    hook = _pick(_HOOKS, topic, 1).format(topic=topic.lower(), seconds=seconds, Topic=topic[:1].upper() + topic[1:].lower())
    beats: list[str] = [hook]
    pool = list(_BEATS)
    rng.shuffle(pool)
    for beat in pool:
        candidate = " ".join([*beats, beat])
        if T.word_count(candidate) > max_words:
            break
        beats.append(beat.format(topic=topic.lower()))
        if len(beats) >= 6:
            break
    cta = _pick(_CTAS, topic, 2)
    if T.word_count(" ".join([*beats, cta])) <= max_words:
        beats.append(cta)

    keywords = list(niche.keywords) or _GENERIC_QUERIES
    segments: list[Segment] = []
    for index, line in enumerate(beats):
        query = keywords[index % len(keywords)] if index < len(keywords) else _GENERIC_QUERIES[index % len(_GENERIC_QUERIES)]
        segments.append(Segment(index=index, text=line, visual_query=query))
    return Script(
        topic=topic,
        title=topic[:70],
        hook=hook,
        segments=segments,
        cta=cta,
        language=niche.language,
        hashtags=list(niche.hashtags) or ["#shorts"],
        provider="template",
    )


def from_text(
    raw: str, topic: str, niche: Niche, settings: Settings, max_words: int
) -> Script:
    """Turn a pasted script/article into segments with derived visual queries."""
    blocks = T.chunk_text(raw, max_seconds=min(12.0, settings.target_seconds / 3.0),
                          words_per_minute=settings.words_per_minute)
    if not blocks:
        raise ValueError("script file contained no usable text")
    keywords = list(niche.keywords)
    segments: list[Segment] = []
    running = 0
    for index, block in enumerate(blocks):
        if running + T.word_count(block) > max_words * 1.15 and index >= 3:
            break
        running += T.word_count(block)
        segments.append(Segment(index=len(segments), text=block, visual_query=visual_query_for(block, keywords, index)))
    if not segments:
        raise ValueError("script too short after budgeting")
    return Script(
        topic=topic,
        title=segments[0].text[:70],
        hook=segments[0].text,
        segments=segments,
        cta=segments[-1].text if len(segments) > 2 else "",
        language=niche.language,
        hashtags=list(niche.hashtags) or ["#shorts"],
        provider="user",
    )


_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "your", "you", "are",
    "have", "will", "just", "like", "when", "what", "which", "into", "over",
    "they", "them", "then", "than", "but", "not", "can", "get", "got", "its",
    "est", "dans", "les", "des", "une", "pour", "avec", "que", "qui", "sur",
    "plus", "par", "nous", "vous", "cette", "comme", "aussi", "tout", "tous",
}


def visual_query_for(sentence: str, keywords: list[str], index: int) -> str:
    """Visual query = the nouns a search engine can actually match on."""
    tokens = [w for w in T.words(sentence.lower()) if len(w) > 3 and w not in _STOP]
    picked = keywords[index % len(keywords)] if keywords and index % 2 == 0 else ""
    return " ".join([picked, *tokens[:4]]).strip() or f"abstract motion background {index}"
