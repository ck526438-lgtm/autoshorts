"""Audio prep, clip concatenation and the final caption burn."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from autoshorts.config import Settings
from autoshorts.util import log
from autoshorts.util.media import (
    Tools,
    concat_list,
    has_filter,
    pick_video_encoder,
    probe_duration,
    run,
)


def normalize_segment(tools: Tools, src: Path, dst: Path, tail: float = 0.07) -> Path:
    """Broadcast-ish voice: cut the dead air, pad one breath, hit -14 LUFS."""
    silence_cut = ("highpass=f=80,"
                   "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.04")
    if not has_filter(tools, "loudnorm"):
        base = silence_cut
    else:
        base = silence_cut + ",loudnorm=I=-14:TP=-1.5:LRA=11"
    chain = f"{base},apad=pad_dur={tail}"
    before = probe_duration(tools, src)
    run([tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
         "-af", chain, "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", dst])
    after = probe_duration(tools, dst)
    if before and after < before * 0.6:
        # A quiet or synthetic take reads as "all silence" and gets eaten alive;
        # keep the length and only pad it.
        log.warn(f"silence trim collapsed {src.name} ({before:.1f}s -> {after:.2f}s), skipping it")
        run([tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
             "-af", f"apad=pad_dur={tail}", "-ar", "48000", "-ac", "1",
             "-c:a", "pcm_s16le", dst])
    return dst


def concat(tools: Tools, parts: list[Path], out: Path, *, audio: bool = False) -> Path:
    if not parts:
        raise ValueError("nothing to concatenate")
    listing = concat_list(out.with_suffix(".txt"), parts)
    mapping = ["-c:a", "copy", "-vn"] if audio else ["-an", "-c:v", "copy"]
    run([tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", listing, *mapping, out])
    if not audio:
        expected = sum(probe_duration(tools, part) for part in parts)
        got = probe_duration(tools, out)
        if expected and got and abs(expected - got) > max(0.8, len(parts) * 0.15):
            log.warn(f"concat drift ({got:.1f}s vs {expected:.1f}s) — re-encoding the track")
            run([tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-f", "concat", "-safe", "0", "-i", listing, "-an",
                 "-c:v", pick_video_encoder(tools), "-crf", "18", "-preset", "veryfast", out])
    listing.unlink(missing_ok=True)
    return out


def _audio_filter(tools: Tools, settings: Settings) -> str:
    """Graph labels: [0]=base video, [1]=voice, [2]=music bed (only if present)."""
    if not settings.music_file:
        return "[1:a]aresample=48000[aout]"
    if not has_filter(tools, "sidechaincompress"):
        return (
            f"[2:a]volume={settings.music_volume}[bg];"
            "[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
    # Duck the bed under the voice instead of just burying it.
    return (
        f"[2:a]volume={settings.music_volume}[bg];"
        "[bg][1:a]sidechaincompress=threshold=0.03:ratio=6:attack=25:release=420[ducked];"
        "[1:a][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
    )


def mux(
    tools: Tools,
    video: Path,
    voice: Path,
    captions: Path,
    settings: Settings,
    out: Path,
    srt: Path | None = None,
) -> Path:
    """Burn captions + mix the voice (and optional music) in a single pass.

    ffmpeg runs with the job folder as cwd and the .ass as a relative path:
    Windows drive letters need escaping inside filter arguments otherwise.
    """
    encoder = pick_video_encoder(tools)
    # Absolute everywhere except the .ass: libass resolves that name against the
    # filter's cwd, and a Windows path inside a filter argument needs escaping.
    video, voice, out = video.resolve(), voice.resolve(), out.resolve()
    captions = captions.resolve()
    music = settings.music_file.resolve() if settings.music_file and settings.music_file.is_file() else None
    burn = captions.is_file() and has_filter(tools, "ass")

    cmd = [tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-i", voice]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]

    if burn:
        chain = f"[0:v]ass={captions.name},format=yuv420p[vout];" + _audio_filter(tools, settings)
        cmd += ["-filter_complex", chain, "-map", "[vout]", "-map", "[aout]"]
    else:
        log.warn("this ffmpeg build has no libass — embedding a switchable subtitle track instead")
        if srt is None or not srt.is_file():
            raise FileNotFoundError("no .srt available for the no-libass fallback")
        cmd += ["-i", srt.resolve()]
        cmd += ["-map", "0:v", "-map", "1:a", "-map", "2:s"]

    cmd += [
        "-c:v", encoder, "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-r", str(settings.fps),
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest",
        *([] if burn else ["-c:s", "mov_text", "-metadata:s:s:0", f"language={settings.caption_language or 'und'}"]),
        str(out),
    ]
    try:
        run(cmd, timeout=2400, cwd=captions.parent)
    except Exception as exc:
        if not music:
            raise
        # Older ffmpeg chokes on amix's normalize=0 — retry without the bed.
        log.warn(f"music mix failed ({exc}); rendering voice only")
        return mux(tools, video, voice, captions, replace(settings, music_file=None), out, srt)
    if not out.is_file() or out.stat().st_size < 4096:
        raise RuntimeError("final render produced no file")
    return out
