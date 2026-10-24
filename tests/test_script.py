import json
from pathlib import Path

import pytest

from autoshorts.config import Niche, Settings, build_settings
from autoshorts.llm import chat, template, writer

MODEL_REPLY = json.dumps({
    "title": "Why your ads lose money",
    "hook": "**Your best ad is losing money.** 🚀",
    "segments": [
        {"text": "Your best ad is losing money.", "visual_query": "laptop dashboard red graph"},
        {"text": "The creative was never the problem.", "visual_query": "advertising billboard empty street"},
        {"text": "Audiences scroll past polish, not past clarity.", "visual_query": ""},
    ],
    "cta": "Follow for the next teardown.",
    "hashtags": ["#shorts", "ads"],
})


def test_extract_json_rescues_fenced_output():
    wrapped = f"Sure!\n```json\n{MODEL_REPLY}\n```"
    assert chat.extract_json(wrapped)["title"].startswith("Why")


def test_extract_json_raises_on_noise():
    with pytest.raises(chat.LLMUnavailable):
        chat.extract_json("I cannot help with that.")


def test_parse_cleans_markdown_and_emoji():
    script = writer._parse(MODEL_REPLY, "ads", Niche(), "openai")
    assert "*" not in script.hook and "🚀" not in script.hook
    assert len(script.segments) == 3  # the duplicated hook is not inserted twice
    assert script.segments[0].text == script.hook
    assert script.segments[0].visual_query == "laptop dashboard red graph"
    assert script.segments[-1].visual_query == ""  # the model was lazy here


def test_finalise_fills_missing_visual_queries():
    script = writer._finalise(writer._parse(MODEL_REPLY, "ads", Niche(), "openai"),
                              Settings(), max_words=200)
    assert all(seg.visual_query for seg in script.segments)


def test_parse_accepts_plain_string_segments():
    payload = json.dumps({"hook": "Stop.", "segments": ["One line.", "Two line."]})
    script = writer._parse(payload, "topic", Niche(), "openai")
    assert len(script.segments) == 3  # hook + 2 lines


def test_budget_trim_keeps_at_least_three_segments():
    settings = Settings(target_seconds=6, tts_rate="+0%")
    script = writer._finalise(
        writer._parse(json.dumps({
            "hook": "One.",
            "segments": [{"text": f"Line {i} with quite a few words in it."} for i in range(12)],
        }), "t", Niche(), "template"),
        settings,
        max_words=15,
    )
    assert 3 <= len(script.segments) <= 8


def test_offline_template_builds_hook_first_script():
    script = template.build("cold outreach", Niche(name="sales"), Settings(), max_words=70)
    assert script.segments[0].text == script.hook
    assert script.provider == "template"
    assert all(s.visual_query for s in script.segments)


def test_offline_writer_prefers_the_niche_beat_bank():
    niche = Niche(name="sleep", beats=(
        "The phone does not stop because the room went dark.",
        "Same wake time beats same bedtime, {topic} in {seconds} seconds.",
        "Broken {nope} placeholder stays literal",
    ))
    script = template.build("3 habits that ruin your sleep", niche, Settings(), max_words=70)
    body = " ".join(segment.text for segment in script.segments)
    assert "The phone does not stop" in body
    assert "in 45 seconds" in body
    assert "{nope}" in body


def test_from_text_reuses_user_script():
    script = template.from_text(
        "Most funnels leak at step two. Fix the form, not the traffic. "
        "Then measure the drop again tomorrow.",
        "funnels", Niche(), Settings(), 80,
    )
    assert len(script.segments) >= 1
    assert script.provider == "user"


def test_settings_overrides_and_niche(tmp_path: Path):
    niche_file = tmp_path / "n.yaml"
    niche_file.write_text("name: test\nlanguage: fr\nduration: 33\nbanned: [donc]\n", encoding="utf-8")
    niche = Niche.load(niche_file)
    settings = build_settings(
        env_file=tmp_path / "missing.env",
        niche=niche,
        overrides={"tts_provider": "silence"},
        environ={"LLM_PROVIDER": "ollama", "VIDEO_WIDTH": "720"},
    )
    assert settings.llm_provider == "ollama"
    assert settings.width == 720
    assert settings.target_seconds == 33
    assert settings.caption_language == "fr"
    assert settings.tts_provider == "silence"
    assert niche.banned == ("donc",)


def test_local_clips_dir_is_read_from_the_environment(tmp_path: Path):
    settings = build_settings(
        env_file=tmp_path / "absent.env",
        environ={"LOCAL_CLIPS_DIR": "my/footage", "STOCK_PRIORITY": "local,procedural"},
    )
    assert settings.local_clips_dir == Path("my/footage")
    assert settings.stock_priority == ("local", "procedural")
    assert build_settings(env_file=tmp_path / "absent.env", environ={}).local_clips_dir == Path("assets/clips")


def test_words_per_minute_tracks_rate():
    assert Settings(tts_rate="+20%").words_per_minute == 180
    assert Settings(tts_rate="garbage").words_per_minute == 150


def test_llm_dispatch_without_keys_is_not_fatal():
    with pytest.raises(chat.LLMUnavailable):
        chat.complete("sys", "user", Settings(llm_provider="openai", openai_api_key=""))
