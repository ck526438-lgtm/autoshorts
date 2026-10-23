import wave
from pathlib import Path

from autoshorts.config import Niche, Settings
from autoshorts.models import Segment
from autoshorts.render import align
from autoshorts.tts import providers
from autoshorts.util import rss
from autoshorts.util.media import Tools, concat_list
from autoshorts.visuals import local, planner, procedural

SAMPLE_RSS = """<?xml version="1.0"?>
<rss><channel>
 <item><title>Why <b>Postgres</b> slows down</title><description>Vacuum &lt;tables&gt; first.
 Second line.</description><link>https://x/1</link></item>
 <item><title>Only a title</title></item>
</channel></rss>"""


def test_estimate_covers_the_whole_take():
    words = align.estimate("Ship the rough version today.", 4.0)
    assert words[0].start == 0.0
    assert abs(words[-1].end - 4.0) < 0.01
    assert all(a.end >= a.start for a in words)


def test_align_offsets_onto_the_job_timeline():
    segment = Segment(index=2, text="one two three", duration=1.5)
    words = align.align_segment(segment, Settings(), Tools(Path("ffmpeg"), None, "test"),
                                provided=None, audio=None, offset=10.0)
    assert words[0].start >= 10.0
    assert words[-1].end <= 11.5 + 1e-6


def test_silence_engine_writes_a_real_wav(tmp_path: Path):
    out = tmp_path / "seg.wav"
    words = providers.silence("One two three four five.", Settings(target_seconds=5), out,
                              Tools(Path("ffmpeg"), None, "test"))
    with wave.open(str(out), "rb") as handle:
        assert handle.getnchannels() == 1 and handle.getframerate() == 24000
    assert len(words) == 5


def test_procedural_art_matches_resolution(tmp_path: Path):
    from PIL import Image

    art = procedural.generate("night city rain", tmp_path / "a.png", 540, 960, variant=1)
    with Image.open(art) as image:
        assert image.size == (540, 960)
    again = procedural.generate("night city rain", tmp_path / "b.png", 540, 960, variant=1)
    assert art.read_bytes() == again.read_bytes()  # deterministic per query


def test_local_folder_ranking(tmp_path: Path):
    (tmp_path / "city_timelapse_night.mp4").write_bytes(b"x")
    (tmp_path / "desk.png").write_bytes(b"y")
    hits = local.candidates(tmp_path, "city night timelapse")
    assert hits[0]["label"] == "city_timelapse_night.mp4"
    assert hits[0]["kind"] == "video"
    assert local.candidates(tmp_path / "nope", "city") == []


def test_planner_falls_back_to_generated_art(tmp_path: Path):
    settings = Settings(download_dir=tmp_path / "media", stock_priority=("procedural",),
                        width=360, height=640)
    tools = Tools(Path("ffmpeg"), None, "test")
    segments = [Segment(index=0, text="hook line", visual_query="office desk", duration=2.0)]
    plan = planner.plan_media(segments, settings, tools, Niche(), "cold outreach")
    assert segments[0].media.kind == "image"
    assert Path(segments[0].media.source).is_file()
    assert plan.by_provider["procedural"] == 1


def test_rss_parser_strips_html_and_caps_limit():
    items = rss.parse(SAMPLE_RSS.encode(), limit=5)
    assert items[0].title == "Why Postgres slows down"
    assert "<" not in items[0].summary and "&" not in items[0].summary
    assert len(items) == 2


def test_concat_list_uses_version_header(tmp_path: Path):
    listing = concat_list(tmp_path / "list.txt", [tmp_path / "it's here.mp4"])
    assert "ffconcat version 1.0" in listing.read_text(encoding="utf-8")
