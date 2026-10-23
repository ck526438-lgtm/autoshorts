"""Prompt assembly for the script writer."""

from __future__ import annotations

from autoshorts.config import Niche, Settings

SCHEMA = """{
  "title": "≤ 60 characters, for the post caption",
  "hook": "the first spoken line, ≤ 14 words",
  "segments": [
    { "text": "1-2 short spoken sentences", "visual_query": "2-5 english keywords for b-roll" }
  ],
  "cta": "one spoken line asking for a follow or comment",
  "hashtags": ["#shorts", "#niche"]
}"""

SYSTEM = """You write voiceover scripts for faceless short-form videos.
You optimise for one metric: the share of viewers still watching at the end.
You never sound like a press release, never use a metaphor you have not earned,
and never waste a syllable. Your lines must survive being read aloud."""


def user_prompt(topic: str, niche: Niche, settings: Settings, max_words: int) -> str:
    language = settings.caption_language if settings.caption_language != "auto" else niche.language
    hooks = "; ".join(niche.hook_styles) if niche.hook_styles else (
        "bold claim, counter-intuitive fact, specific number, direct callout of the viewer"
    )
    return f"""{niche.brief()}

TASK: write one {settings.target_seconds}s voiceover script about: {topic}

Structure
1. Hook — first line, spoken, ≤ 14 words. Open a loop the rest of the script closes.
   Try one of: {hooks}.
2. Body — {2 if settings.target_seconds < 30 else 6} segments, one idea each,
   1-2 sentences of ≤ 18 words. Concrete numbers beat adjectives.
   Between segments, keep momentum: each line must raise a question the next answers.
3. CTA — one line, spoken, ask for a comment or follow tied to the topic.

Hard rules
- Language: {language}.
- Total narration ≤ {max_words} words (spoken at ~{settings.words_per_minute} wpm).
- Do not include the hook in "segments"; it is segment 0 and must also appear in "segments"[0].
- Never use: {", ".join(niche.banned)}.
- No emoji, no asterisks, no brackets, no camera directions.
- "visual_query" = english keywords describing what is on screen, not the idea
  (e.g. "night city traffic rain", not "success mindset").

Return exactly this JSON shape:
{SCHEMA}"""


def topic_variations(topic: str, count: int = 3) -> list[str]:
    """Cheap angle expansion so batch runs do not produce clones."""
    base = topic.strip().rstrip(".")
    angles = [
        base,
        f"{base}: the mistake almost everyone makes",
        f"3 things about {base} I wish I knew earlier",
        f"Why {base} fails for most people",
        f"{base} explained in 30 seconds",
    ]
    return angles[:count]
