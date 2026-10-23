"""One normalised video clip per narration segment, cut to the exact voice length."""

from __future__ import annotations

import math
import random
from pathlib import Path

from autoshorts.config import Settings
from autoshorts.models import Segment
from autoshorts.util import log
from autoshorts.util.media import Tools, has_filter, probe_duration, run

_LOOK = {
    "natural": "eq=contrast=1.03:saturation=1.10",
    "punchy": "eq=contrast=1.09:saturation=1.28:gamma=1.02",
    "flat": "",
}


def _video_filter(tools: Tools, settings: Settings) -> str:
    parts = [
        f"fps={settings.fps}",
        f"scale={settings.width}:{settings.height}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={settings.width}:{settings.height}",
        "setsar=1",
    ]
    grade = _LOOK.get(settings.clip_look, "")
    if grade and has_filter(tools, "eq"):
        parts.append(grade)
    return ",".join(parts)


def _image_filter(settings: Settings, frames: int, zoom_out: bool) -> str:
    """Ken Burns, written without commas inside the zoom expression.

    `zoompan` splits its options on commas, so the usual `min(zoom+0.001,1.2)`
    cap needs quoting; a linear ramp in the output frame number `on` needs none.
    """
    pad = 2  # oversample so the zoom never runs out of pixels
    width, height = settings.width * pad, settings.height * pad
    rate = 0.18 / max(1, frames)
    if not settings.ken_burns:
        zoom = "'1.0'"
    elif zoom_out:
        zoom = f"'{1.18 - 0.0:.2f}-on*{rate:.6f}'"
    else:
        zoom = f"'1.0+on*{rate:.6f}'"
    zoompan = (
        f"zoompan=z={zoom}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={settings.width}x{settings.height}:fps={settings.fps}"
    )
    return ",".join([
        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
        f"crop={width}:{height}",
        zoompan,
        "setsar=1",
    ])


def _encode_tail(encoder: str) -> list[str]:
    quality = ["-preset", "veryfast", "-crf", "20"] if encoder == "libx264" else ["-q:v", "4"]
    return ["-an", "-c:v", encoder, *quality, "-g", "60", "-pix_fmt", "yuv420p"]


def render_clip(
    tools: Tools,
    segment: Segment,
    settings: Settings,
    out: Path,
    encoder: str,
) -> Path:
    media = segment.media
    if media is None or not Path(media.source).is_file():
        raise FileNotFoundError(f"segment {segment.index} has no usable media")
    duration = max(0.4, round(segment.duration, 3))
    frames = max(1, math.ceil(duration * settings.fps))
    head = [tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]

    if media.kind == "image":
        cmd = [
            *head, "-i", media.source,
            "-vf", _image_filter(settings, frames, zoom_out=bool(segment.index % 2)),
            "-frames:v", str(frames), "-r", str(settings.fps),
        ]
    else:
        available = media.duration or probe_duration(tools, Path(media.source))
        if available >= duration + 0.4:
            # A different in-point per segment so repeated clips never look looped.
            offset = round(random.Random(segment.index).uniform(0, max(0.0, available - duration - 0.2)), 2)
            cmd = [*head, "-ss", str(offset), "-i", media.source, "-t", str(duration)]
        else:
            cmd = [*head, "-stream_loop", "-1", "-i", media.source, "-t", str(duration)]
        cmd += ["-vf", _video_filter(tools, settings), "-r", str(settings.fps)]

    cmd += [*_encode_tail(encoder), str(out)]
    try:
        run(cmd, timeout=1200)
    except Exception as exc:
        if media.kind == "image":
            raise
        log.warn(f"segment {segment.index}: clip failed ({exc}); falling back to a still frame")
        media.kind = "image"
        return render_clip(tools, segment, settings, out, encoder)
    if not out.is_file() or out.stat().st_size < 2048:
        raise RuntimeError(f"segment {segment.index} produced an empty clip")
    return out
