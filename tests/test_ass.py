from itertools import pairwise
from pathlib import Path

from autoshorts.config import Settings
from autoshorts.models import Segment, Word
from autoshorts.render import ass


def clock(sequence: list[str], step: float = 0.32) -> list[Word]:
    out, cursor = [], 0.0
    for token in sequence:
        out.append(Word(token, round(cursor, 3), round(cursor + step, 3)))
        cursor += step + 0.01
    return out


def test_hex_to_ass_is_bgr():
    assert ass.hex_to_ass("#FFE81A") == "&H001AE8FF&"
    assert ass.hex_to_ass("#abc") == "&H00CCBBAA&"
    assert ass.hex_to_ass("nonsense") == "&H00FFFFFF&"


def test_groups_are_small_and_ordered():
    groups = ass.group_words(clock(["The", "first", "hook", "line.", "And", "a", "second"]), Settings())
    assert len(groups) >= 2
    assert groups[0].words[0].text == "The"
    assert all(len(g.words) <= 3 for g in groups)
    assert all(g.end >= g.start for g in groups)


def test_ass_output_has_styles_and_karaoke():
    groups = ass.group_words(clock(["Stop", "scrolling", "now."]), Settings())
    payload = ass.build_ass(groups, Settings())
    assert "[V4+ Styles]" in payload and "Style: Caption," in payload
    assert r"\kf" in payload and "Dialogue: 0," in payload
    assert "PlayResX: 1080" in payload


def test_ass_survives_braces_in_narration():
    groups = [ass.Group(start=0.0, end=1.0, lines=[[Word("{evil}", 0.0, 1.0)]], segment=1)]
    payload = ass.build_ass(groups, Settings())
    event = payload.splitlines()[-1]
    assert "{evil}" not in event
    assert "(evil)" in event


def test_flatten_removes_overlap():
    segments = [
        Segment(index=0, text="alpha beta", words=clock(["alpha", "beta"])),
        Segment(index=1, text="gamma", words=[Word("gamma", 0.9, 1.4)]),
    ]
    groups = ass.flatten(segments, Settings())
    assert groups
    for previous, current in pairwise(groups):
        assert previous.end < current.start


def test_srt_fallback(tmp_path: Path):
    groups = ass.group_words(clock(["One", "two", "three."]), Settings())
    out = ass.write_srt(groups, tmp_path / "c.srt")
    body = out.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 -->" in body
    assert "one" in body.lower()
