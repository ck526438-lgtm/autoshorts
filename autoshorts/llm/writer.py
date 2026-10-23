"""Write the narration: LLM if configured, offline template otherwise."""

from __future__ import annotations

import re
from pathlib import Path

from autoshorts.config import Niche, Settings
from autoshorts.llm import chat, template
from autoshorts.llm.prompt import SYSTEM, user_prompt
from autoshorts.models import Script, Segment
from autoshorts.util import log
from autoshorts.util.text import clean, word_count

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\u2190-\u21FF\u2600-\u27BF\uFE0F]+"
)


def build_script(
    topic: str,
    settings: Settings,
    niche: Niche | None = None,
    script_file: str | Path | None = None,
) -> Script:
    niche = niche or Niche()
    max_words = max(20, int(settings.target_seconds * settings.words_per_minute / 60.0))

    if script_file:
        raw = Path(script_file).read_text(encoding="utf-8", errors="replace")
        script = template.from_text(clean(raw), topic or _first_line(raw), niche, settings, max_words)
        log.ok(f"script from file: {len(script.segments)} segments, {word_count(script.narration)} words")
        return _finalise(script, settings, max_words)

    prompt = user_prompt(topic, niche, settings, max_words)
    try:
        raw = chat.complete(SYSTEM, prompt, settings, expect_json=True)
        script = _parse(raw, topic, niche, settings.llm_provider)
        log.ok(f"script via {settings.llm_provider}: {len(script.segments)} segments")
    except chat.LLMUnavailable as exc:
        log.warn(f"LLM unavailable ({exc}) — using the offline template writer")
        script = template.build(topic, niche, settings, max_words)
    return _finalise(script, settings, max_words)


def _first_line(raw: str) -> str:
    for line in raw.splitlines():
        if line.strip():
            return clean(line)[:80]
    return "untitled"


def _parse(raw: str, topic: str, niche: Niche, provider: str) -> Script:
    data = chat.extract_json(raw)
    segments: list[Segment] = []
    for item in data.get("segments") or []:
        if isinstance(item, str):
            item = {"text": item}
        body = _spoken(item.get("text") or item.get("line") or "")
        if not body:
            continue
        segments.append(
            Segment(
                index=len(segments),
                text=body,
                visual_query=clean(str(item.get("visual_query") or item.get("query") or "")),
            )
        )
    if not segments:
        raise chat.LLMUnavailable("model returned no usable segments")
    hook = _spoken(data.get("hook") or "") or segments[0].text
    if hook and hook.lower() != segments[0].text.lower():
        segments.insert(0, Segment(index=0, text=hook, visual_query=""))
    for index, segment in enumerate(segments):
        segment.index = index
    return Script(
        topic=topic,
        title=clean(str(data.get("title") or topic))[:90],
        hook=hook,
        segments=segments,
        cta=_spoken(data.get("cta") or ""),
        language=niche.language,
        hashtags=[str(h) for h in (data.get("hashtags") or [])][:12],
        provider=provider,
    )


def _spoken(value: object) -> str:
    text = clean(str(value or ""))
    text = _EMOJI.sub("", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and text[-1] not in ".!?…:":
        text += "."
    return text


def _finalise(script: Script, settings: Settings, max_words: int) -> Script:
    """Enforce the time budget and make sure every segment can be illustrated."""
    budget = int(max_words * 1.18)
    running = 0
    kept: list[Segment] = []
    for segment in script.segments:
        size = word_count(segment.text)
        if kept and running + size > budget and len(kept) >= 3:
            log.warn(f"trimming to fit {settings.target_seconds}s: dropped {size} words")
            break
        running += size
        kept.append(segment)
    script.segments = kept
    for index, segment in enumerate(script.segments):
        segment.index = index
        if not segment.visual_query:
            from autoshorts.llm.template import visual_query_for  # one heuristic, one home

            segment.visual_query = visual_query_for(segment.text, [], index)
    if not script.hashtags:
        script.hashtags = ["#shorts"]
    script.provider = script.provider or settings.llm_provider
    return script
