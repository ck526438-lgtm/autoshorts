"""The pipeline: five resumable stages, one mp4 out.

    topic ─▶ script ─▶ voice ─▶ b-roll ─▶ captions ─▶ render
                              │           │
                              └─ word clock┘  (TTS timings → Whisper → estimate)

Each stage writes JSON/WAV/MP4 into the job folder and is skipped when its
artefacts already exist, so `--force voice` re-does the take without re-paying
the LLM or re-downloading footage.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from autoshorts import __version__
from autoshorts.config import Niche, Settings, build_settings
from autoshorts.llm import writer
from autoshorts.models import JobPaths, Media, Script
from autoshorts.render import align, ass, clips, mux
from autoshorts.tts import synthesize
from autoshorts.util import log
from autoshorts.util.media import Tools, pick_video_encoder, probe_duration, resolve
from autoshorts.util.text import slugify
from autoshorts.visuals import plan_media


class StageError(RuntimeError):
    pass


@dataclass
class Options:
    topic: str = ""
    script_file: Path | None = None
    niche_file: Path | None = None
    offline: bool = False
    keep_clips: bool = True
    force: set[str] = field(default_factory=set)
    until: str = "render"

    def forced(self, stage: str) -> bool:
        return "*" in self.force or stage in self.force

    def past(self, stage: str) -> bool:
        """True when `stage` should run, given --until."""
        try:
            return STAGES.index(stage) <= STAGES.index(self.until)
        except ValueError:
            return True


STAGES = ("script", "voice", "visuals", "captions", "render")


@dataclass
class JobResult:
    video: Path
    job: Path
    duration: float
    segments: int
    captions: int
    providers: dict[str, str]
    seconds_elapsed: float

    def summary(self) -> str:
        return (
            f"{self.video} — {self.duration:.1f}s, {self.segments} segments, "
            f"{self.captions} caption events, {self.seconds_elapsed:.0f}s render"
        )


def make_job_dir(output_dir: Path, topic: str, name: str = "") -> Path:
    label = name or slugify(topic or "untitled")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = output_dir / f"{stamp}-{label}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class Job:
    def __init__(self, settings: Settings, options: Options, root: Path) -> None:
        self.settings = settings
        self.options = options
        self.paths = JobPaths(root)
        self.tools: Tools = resolve(settings.ffmpeg_bin, settings.ffprobe_bin)
        self.encoder = pick_video_encoder(self.tools)
        self.script: Script | None = None
        self.voice_engine = ""

    # ------------------------------------------------------------ stage 1
    def stage_script(self) -> Script:
        cached = self.paths.load(self.paths.script)
        if cached and not self.options.forced("script"):
            log.ok(f"script: reused cached draft ({len(cached['segments'])} segments)")
            return Script.from_dict(cached)
        niche = Niche.load(self.options.niche_file)
        script = writer.build_script(
            self.options.topic, self.settings, niche, self.options.script_file
        )
        if not script.segments:
            raise StageError("script writer returned zero segments")
        self.paths.save(script.to_dict(), self.paths.script)
        log.ok(f"script: {len(script.segments)} segments, {len(script.narration)} chars "
               f"({script.provider})")
        return script

    # ------------------------------------------------------------ stage 2
    def stage_voice(self, script: Script) -> float:
        cursor = 0.0
        forced = self.options.forced("voice")
        for segment in script.segments:
            wav = self.paths.segment_audio(segment.index)
            raw = wav.with_name(f"{wav.stem}_raw.wav")
            cached = wav.is_file() and wav.stat().st_size > 1024
            if cached and not forced and segment.words:
                log.debug(f"voice seg {segment.index:02d}: cached take + clock")
            elif cached and not forced:
                segment.duration = round(probe_duration(self.tools, wav), 3)
                segment.words = align.align_segment(
                    segment, self.settings, self.tools, None, wav, cursor
                )
            else:
                # The engine writes to a temp file: ffmpeg cannot read and write
                # the same wav while normalising.
                words, used = synthesize(
                    segment.text, self.settings, raw, self.tools,
                    offline=self.options.offline,
                )
                self.voice_engine = used
                mux.normalize_segment(self.tools, raw, wav)
                raw.unlink(missing_ok=True)
                segment.duration = round(probe_duration(self.tools, wav), 3)
                segment.words = align.align_segment(
                    segment, self.settings, self.tools, words, wav, cursor
                )
                log.debug(f"voice seg {segment.index:02d}: {segment.duration:.2f}s via {used}")
            segment.audio_path = str(wav)
            if not segment.duration:
                segment.duration = round(probe_duration(self.tools, wav), 3)
            if segment.duration <= 0:
                raise StageError(f"segment {segment.index} has no readable audio duration")
            cursor += segment.duration
        log.ok(f"voiceover: {cursor:.1f}s over {len(script.segments)} segments "
               f"({self.voice_engine or 'cached takes'})")
        parts = [Path(s.audio_path) for s in script.segments if Path(s.audio_path).is_file()]
        if len(parts) != len(script.segments):
            raise StageError("some segments are missing audio files")
        mux.concat(self.tools, parts, self.paths.voice, audio=True)
        self.paths.save(script.to_dict(), self.paths.script)
        return cursor

    # ------------------------------------------------------------ stage 3
    def stage_visuals(self, script: Script) -> None:
        niche = Niche.load(self.options.niche_file)
        cached = self.paths.load(self.paths.plan) or {}
        by_index = {int(k): v for k, v in cached.items()}
        if by_index and not self.options.forced("visuals"):
            for segment in script.segments:
                entry = by_index.get(segment.index)
                if entry and Path(entry.get("source", "")).is_file():
                    segment.media = Media.from_dict(entry)
        if all(s.media and Path(s.media.source).is_file() for s in script.segments):
            log.ok("b-roll: reused the cached shot list")
        else:
            plan = plan_media(script.segments, self.settings, self.tools, niche, script.topic)
            log.ok(f"b-roll: {plan.assigned} shots — "
                   + ", ".join(f"{k}:{v}" for k, v in plan.by_provider.items()))
            for note in plan.notes[:3]:
                log.debug(note)
        self.paths.save(
            {str(s.index): _media_dict(s.media) for s in script.segments if s.media},
            self.paths.plan,
        )

    # ------------------------------------------------------------ stage 4
    def stage_captions(self, script: Script, duration: float) -> list[ass.Group]:
        groups = ass.flatten(script.segments, self.settings)
        ass.write_ass(groups, self.settings, self.paths.captions)
        ass.write_srt(groups, self.paths.captions.with_suffix(".srt"))
        if not groups:
            log.warn("no caption events were produced")
        else:
            covered = sum(g.end - g.start for g in groups)
            log.ok(f"captions: {len(groups)} events, on screen {covered / max(1e-6, duration):.0%} "
                   f"of the runtime")
        return groups

    # ------------------------------------------------------------ stage 5
    def stage_render(self, script: Script) -> Path:
        if self.paths.final.is_file() and not self.options.forced("render"):
            log.ok("render: final.mp4 already exists (use --force render)")
            return self.paths.final
        missing = [s.index for s in script.segments if not Path(s.audio_path).is_file()]
        if missing:
            raise StageError(f"segments without audio: {missing} — run the voice stage first")
        no_visual = [s.index for s in script.segments if not s.media]
        if no_visual:
            raise StageError(f"segments without b-roll: {no_visual}")

        clip_paths: list[Path] = []
        total = len(script.segments)
        for position, segment in enumerate(script.segments, start=1):
            target = self.paths.segment_clip(segment.index)
            clip_paths.append(target)
            if target.is_file() and not self.options.forced("clips"):
                log.step(position, total, f"clip {segment.index:02d} (cached)")
                continue
            clips.render_clip(self.tools, segment, self.settings, target, self.encoder)
            log.step(position, total, f"clip {segment.index:02d} ({segment.duration:.1f}s)")
        mux.concat(self.tools, clip_paths, self.paths.base_video)
        srt = self.paths.captions.with_suffix(".srt")
        log.info("burning captions and mixing audio…")
        return mux.mux(self.tools, self.paths.base_video, self.paths.voice,
                       self.paths.captions, self.settings, self.paths.final, srt)

    # ------------------------------------------------------------- metadata
    def write_metadata(self, script: Script, duration: float, groups: list[ass.Group]) -> None:
        niche = Niche.load(self.options.niche_file)
        normalised = [h if h.startswith("#") else "#" + h.replace(" ", "") for h in script.hashtags]
        tags = list(dict.fromkeys(normalised + list(niche.hashtags)))
        description = "\n\n".join(
            part for part in [script.hook.strip(), script.narration.strip()] if part
        )[:1800]
        self.paths.save(
            {
                "title": script.title or script.topic,
                "description": description,
                "hashtags": tags[:12],
                "duration_seconds": round(duration, 2),
                "caption_events": len(groups),
                "language": self.settings.caption_language,
                "vertical_resolution": f"{self.settings.width}x{self.settings.height}",
                "generator": f"autoshorts {__version__}",
                "providers": {
                    "script": script.provider,
                    "voice": self.voice_engine or self.settings.tts_provider,
                    "media": self.paths.load(self.paths.plan) or {},
                },
                "source_attribution": _sources(script),
            },
            self.paths.metadata,
        )

    def run(self) -> JobResult:
        started = time.time()
        log.info(f"job folder: {self.paths.root}")
        script = self.stage_script()
        duration = self.stage_voice(script)
        if not self.options.past("visuals"):
            return self._partial(script, duration, [], started)
        self.stage_visuals(script)
        groups = self.stage_captions(script, duration)
        if not self.options.past("render"):
            log.ok(f"stopped after {self.options.until}: {self.paths.captions.name} is ready")
            return self._partial(script, duration, groups, started)
        video = self.stage_render(script)
        self.write_metadata(script, duration, groups)
        if not self.options.keep_clips:
            for path in self.paths.root.glob("clips/*.mp4"):
                path.unlink(missing_ok=True)
        return self._result(script, duration, groups, video, started)

    def _partial(self, script: Script, duration: float, groups: list[ass.Group],
                 started: float) -> JobResult:
        return self._result(script, duration, groups, self.paths.root, started)

    def _result(self, script: Script, duration: float, groups: list[ass.Group],
                video: Path, started: float) -> JobResult:
        return JobResult(
            video=video,
            job=self.paths.root,
            duration=duration,
            segments=len(script.segments),
            captions=len(groups),
            providers={"script": script.provider, "voice": self.voice_engine},
            seconds_elapsed=round(time.time() - started, 1),
        )


def _media_dict(media) -> dict:
    return {"kind": media.kind, "source": media.source, "label": media.label,
            "provider": media.provider, "duration": media.duration}


def _sources(script: Script) -> list[dict[str, str]]:
    """Keep a paper trail for every clip — licence questions come later."""
    seen: dict[str, dict[str, str]] = {}
    for segment in script.segments:
        media = segment.media
        if not media or media.provider in {"procedural", ""}:
            continue
        key = media.label or media.source
        seen.setdefault(key, {"provider": media.provider, "label": media.label,
                              "file": media.source})
    return list(seen.values())


def run_job(
    topic: str,
    settings: Settings | None = None,
    niche_file: Path | None = None,
    script_file: Path | None = None,
    name: str = "",
    force: set[str] | None = None,
    offline: bool = False,
) -> JobResult:
    settings = settings or build_settings(niche=Niche.load(niche_file))
    options = Options(
        topic=topic,
        script_file=script_file,
        niche_file=niche_file,
        offline=offline,
        force=force or set(),
    )
    root = make_job_dir(Path(settings.output_dir), topic, name)
    return Job(settings, options, root).run()
