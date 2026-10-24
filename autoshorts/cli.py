"""`autoshorts` command line.

    autoshorts demo --topic "3 habits that quietly ruin your sleep"
    autoshorts run --niche examples/niches/finance.yaml --topic "…" --duration 38
    autoshorts batch --rss https://blog/feed.xml --limit 5
    autoshorts doctor
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path

from autoshorts import __version__
from autoshorts.config import Niche, Settings, build_settings
from autoshorts.pipeline import STAGES, Job, Options, StageError, make_job_dir
from autoshorts.util import log, rss
from autoshorts.util.media import FfmpegNotFound, resolve

DEMO_TOPIC = "3 habits that quietly ruin your sleep"

EPILOGUE = """examples:
  autoshorts demo                          # no keys, no accounts, one mp4
  autoshorts run -t "why your ads lose money" --niche examples/niches/ads.yaml
  autoshorts run -t "…" --llm openai --tts edge --stock pexels,pixabay
  autoshorts run -t "my script" --script my_script.txt --until captions
  autoshorts batch --rss https://hnrss.org/frontpage --limit 3 --count 1
  autoshorts doctor                        # what is installed, what is missing
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autoshorts",
        description="Faceless short-form video factory: topic in, subtitled 9:16 mp4 out.",
        epilog=EPILOGUE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"autoshorts {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    verbose = argparse.ArgumentParser(add_help=False)
    verbose.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    for name, help_text in (
        ("run", "render one short from a topic, a script file, or both"),
        ("demo", "render a short with zero API keys (offline writers and generated art)"),
    ):
        p = sub.add_parser(name, help=help_text, parents=[verbose])
        p.add_argument("-t", "--topic", default="", help="what the video is about")
        p.add_argument("-s", "--script", help="use this .txt/.md as the narration instead")
        p.add_argument("-n", "--niche", help="niche YAML (see examples/niches)")
        p.add_argument("--name", help="short slug for the job folder")
        p.add_argument("--duration", type=int, help="target seconds of narration")
        p.add_argument("--language", help="spoken + caption language, e.g. fr, en, es")
        p.add_argument("--llm", choices=["template", "openai", "anthropic", "ollama"])
        p.add_argument("--model", help="model id for the chosen provider")
        p.add_argument("--tts", choices=["edge", "openai", "piper", "system", "silence"])
        p.add_argument("--voice", help="engine voice id (e.g. fr-FR-DenisNeural)")
        p.add_argument("--stock", help="comma list: pexels,pixabay,local,procedural")
        p.add_argument("--music", help="background music file to duck under the voice")
        p.add_argument("--width", type=int)
        p.add_argument("--height", type=int)
        p.add_argument("--out", help="output root (default: ./output)")
        p.add_argument("--job", help="resume/re-render an existing job folder")
        p.add_argument("--until", choices=STAGES, help="stop after this stage")
        p.add_argument("--force", action="append", default=[],
                       help="redo a stage (script, voice, visuals, clips, captions, render, *); "
                            "visuals also re-cuts the clips it re-shot")
        p.add_argument("--count", type=int, help="render N angle variations of the topic")
        p.add_argument("--offline", action="store_true",
                       help="no network at all: template writer + system voice")
        p.add_argument("--dry-run", action="store_true", help="print the plan and exit")
        p.add_argument("--prune", action="store_true",
                       help="delete per-segment clips after the final render")

    p = sub.add_parser("batch", help="one video per headline from an RSS/Atom feed or a list",
                       parents=[verbose])
    p.add_argument("--rss", help="feed URL")
    p.add_argument("--topics-file", help="one topic per line")
    p.add_argument("-n", "--niche")
    p.add_argument("--limit", type=int, default=5, help="max feed items (default 5)")
    p.add_argument("--count", type=int, default=1, help="variations per topic")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--duration", type=int)
    p.add_argument("--language")
    p.add_argument("--llm", choices=["template", "openai", "anthropic", "ollama"])
    p.add_argument("--model")
    p.add_argument("--tts", choices=["edge", "openai", "piper", "system", "silence"])
    p.add_argument("--voice")
    p.add_argument("--stock")
    p.add_argument("--out")
    p.add_argument("--force", action="append", default=[])
    p.add_argument("--offline", action="store_true")

    sub.add_parser("doctor", help="report what this machine can and cannot do", parents=[verbose])

    p = sub.add_parser("niche", help="scaffold or list niche briefs", parents=[verbose])
    p.add_argument("action", choices=["init", "list"])
    p.add_argument("name", nargs="?", default="my-niche")
    p.add_argument("--dir", default="niches")

    return parser


def _settings(args, base: Settings | None = None) -> Settings:
    niche = Niche.load(args.niche if hasattr(args, "niche") else None)
    overrides: dict[str, object] = {}
    if getattr(args, "duration", None):
        overrides["target_seconds"] = args.duration
    if getattr(args, "language", None):
        overrides["caption_language"] = args.language
    if getattr(args, "llm", None):
        overrides["llm_provider"] = args.llm
    if getattr(args, "model", None):
        overrides["llm_model"] = args.model
    if getattr(args, "tts", None):
        overrides["tts_provider"] = args.tts
    if getattr(args, "voice", None):
        overrides["edge_voice"] = args.voice
    if getattr(args, "stock", None):
        overrides["stock_priority"] = tuple(
            part.strip() for part in str(args.stock).split(",") if part.strip()
        )
    if getattr(args, "music", None):
        overrides["music_file"] = Path(args.music)
    if getattr(args, "width", None):
        overrides["width"] = args.width
    if getattr(args, "height", None):
        overrides["height"] = args.height
    if getattr(args, "out", None):
        overrides["output_dir"] = Path(args.out)
    if getattr(args, "offline", False):
        overrides.update({
            "llm_provider": "template",
            "tts_provider": "system",
            "stock_priority": ("local", "procedural"),
        })
    if base is not None:
        return replace(base, **overrides) if overrides else base
    return build_settings(niche=niche, overrides=overrides)


def _options(args, topic: str) -> Options:
    return Options(
        topic=topic or (Path(args.script).stem if getattr(args, "script", None) else ""),
        script_file=Path(args.script) if getattr(args, "script", None) else None,
        niche_file=Path(args.niche) if getattr(args, "niche", None) else None,
        offline=bool(getattr(args, "offline", False)),
        keep_clips=not bool(getattr(args, "prune", False)),
        force={f.strip() for f in (getattr(args, "force", []) or [])},
        until=getattr(args, "until", None) or "render",
    )


def _render(settings: Settings, options: Options, job: Path) -> dict[str, object]:
    result = Job(settings, options, job).run()
    return {
        "video": str(result.video),
        "job": str(result.job),
        "seconds": round(result.duration, 2),
        "segments": result.segments,
        "caption_events": result.captions,
        "wall_clock_seconds": result.seconds_elapsed,
        "providers": result.providers,
    }


def cmd_run(args, settings: Settings) -> int:
    if not (args.topic or args.script or args.job):
        log.error("need --topic, --script or --job (see `autoshorts run --help`)")
        return 2
    from autoshorts.llm.prompt import topic_variations

    topics = topic_variations(args.topic, args.count or 1) if args.topic else [args.topic or ""]
    root = Path(args.job) if getattr(args, "job", None) else Path(settings.output_dir)
    if getattr(args, "dry_run", False):
        print(json.dumps({
            "would_render": topics,
            "job_root": str(root),
            "settings": {k: str(v) for k, v in settings.__dict__.items()
                         if "api_key" not in k},
        }, indent=2, ensure_ascii=False))
        return 0
    reports = []
    for topic in topics:
        job = Path(args.job) if getattr(args, "job", None) else make_job_dir(
            root, topic, getattr(args, "name", "") or ""
        )
        log.info(f"topic: {topic}" if topic else f"resuming: {job}")
        reports.append(_render(settings, _options(args, topic), job))
    print(json.dumps(reports if len(reports) > 1 else reports[0], indent=2, ensure_ascii=False))
    return 0


def cmd_batch(args, settings: Settings) -> int:
    topics: list[str] = []
    if args.rss:
        try:
            items = rss.fetch(args.rss, limit=args.limit)
        except Exception as exc:
            log.error(f"feed failed: {exc}")
            return 1
        topics = [item.title for item in items]
        log.ok(f"{len(topics)} feed items from {args.rss}")
    elif args.topics_file:
        path = Path(args.topics_file)
        if not path.is_file():
            log.error(f"no such file: {path}")
            return 2
        topics = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")][: args.limit or 5]
        log.ok(f"{len(topics)} topics from {path}")
    else:
        log.error("batch needs --rss or --topics-file")
        return 2

    root = Path(settings.output_dir)
    succeeded, failed = [], []
    for index, topic in enumerate(topics, start=1):
        log.info(f"[{index}/{len(topics)}] {topic[:90]}")
        try:
            if args.skip_existing and _already_rendered(root, topic):
                log.ok("skipped (a render for this topic already exists)")
                continue
            succeeded.append(_render(settings, _options(args, topic), make_job_dir(root, topic)))
        except Exception as exc:  # one bad topic must not kill the batch
            log.error(f"topic failed: {exc}")
            failed.append({"topic": topic, "error": str(exc)})
    report = root / f"batch-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(json.dumps({"ok": succeeded, "failed": failed}, indent=2,
                                 ensure_ascii=False), encoding="utf-8")
    log.ok(f"batch done: {len(succeeded)} rendered, {len(failed)} failed — {report}")
    return 0 if succeeded else 1


def _already_rendered(root: Path, topic: str) -> bool:
    from autoshorts.util.text import slugify

    needle = slugify(topic)[:24]
    return any((job / "final.mp4").is_file() for job in root.glob(f"*{needle}*"))


def cmd_demo(args, settings: Settings) -> int:
    # The demo guarantees "no key needed", so only the writer is pinned; the
    # b-roll chain stays whatever the user configured (default: generated art).
    settings = replace(settings, llm_provider="template")
    if settings.tts_provider in ("openai", "piper"):
        settings = replace(settings, tts_provider="edge")
    args.topic = args.topic or DEMO_TOPIC
    args.count = args.count or 1
    log.info("demo: no API key required — template script, your configured voice and b-roll chain")
    return cmd_run(args, settings)


def cmd_doctor(args) -> int:
    settings = build_settings()
    print(f"autoshorts {__version__} · Python {platform.python_version()} · {platform.system()}")
    print("-" * 62)
    ok = True
    try:
        tools = resolve(settings.ffmpeg_bin, settings.ffprobe_bin)
        print(f"✓ ffmpeg        {tools.ffmpeg}  [{tools.source}]")
    except FfmpegNotFound as exc:
        ok = False
        print(f"✗ ffmpeg\n  {exc}")
    checks = [
        ("edge-tts (free neural voice)", _has("edge_tts")),
        ("imageio-ffmpeg (fallback ffmpeg)", _has("imageio_ffmpeg")),
        ("faster-whisper (offline alignment)", _has("faster_whisper")),
        ("Pillow (generated art)", _has("PIL")),
    ]
    for label, available in checks:
        print(f"{'✓' if available else '!'} {label}")
    print("-" * 62)
    for label, value in (("OPENAI_API_KEY", settings.openai_api_key),
                         ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
                         ("PEXELS_API_KEY", settings.pexels_api_key),
                         ("PIXABAY_API_KEY", settings.pixabay_api_key)):
        print(f"{'✓' if value else '!'} {label:<22}{'set' if value else 'not set — that provider falls back'}")
    print("-" * 62)
    print(f"default providers   script={settings.llm_provider} voice={settings.tts_provider} "
          f"stock={','.join(settings.stock_priority)}")
    print(f"resolution          {settings.width}x{settings.height} @ {settings.fps}fps, "
          f"target {settings.target_seconds}s")
    print(f"system TTS          {shutil.which('powershell') or shutil.which('espeak-ng') or shutil.which('say') or 'none'}")
    print("-" * 62)
    if ok:
        print("Ready. Try:  autoshorts demo")
    else:
        print("Install ffmpeg first:  pip install \"autoshorts[ffmpeg]\"")
    return 0 if ok else 1


def _has(module: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(module) is not None
    except Exception:
        return False


def cmd_niche(args) -> int:
    if args.action == "list":
        folders = [Path(args.dir), Path(__file__).parent.parent / "examples" / "niches"]
        found = sorted({p for folder in folders if folder.is_dir() for p in folder.glob("*.yaml")})
        for path in found:
            print(path)
        if not found:
            print("no niche files yet — run: autoshorts niche init my-niche")
        return 0
    target = Path(args.dir) / f"{args.name}.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        log.error(f"{target} already exists — pick another name or edit it directly")
        return 1
    template = Path(__file__).parent.parent / "examples" / "niches" / "finance.yaml"
    seed = template.read_text(encoding="utf-8") if template.is_file() else _BLANK_NICHE
    target.write_text(seed.replace("name: finance", f"name: {args.name}", 1), encoding="utf-8")
    log.ok(f"wrote {target} — edit the persona, then pass it with --niche {target}")
    return 0


_BLANK_NICHE = """name: my-niche
language: en
persona: a blunt operator who has done the thing
audience: people who already know the basics
tone: concrete, fast, zero motivation-speak
duration: 42
hook_styles:
  - "counter-intuitive claim with a number"
  - "call out the viewer's mistake"
# Optional bank used by the offline writer when no API key is configured.
# {topic} and {seconds} are substituted; a human still owns the claims.
beats:
  - "Do the boring version twice a week for six weeks."
  - "Cut the step you are proudest of, it is usually the delay."
banned: [very, actually, in conclusion, guys]
hashtags: ["#shorts", "#business"]
visual_style: "cinematic b-roll, moody lighting, shallow depth of field"
keywords:
  - "office desk morning light"
  - "city timelapse night"
  - "close up hands writing notebook"
"""


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log.set_level("DEBUG" if args.verbose else "INFO")
    try:
        if args.command == "doctor":
            return cmd_doctor(args)
        if args.command == "niche":
            return cmd_niche(args)
        settings = _settings(args)
        log.set_level("DEBUG" if args.verbose else settings.log_level)
        if args.command == "demo":
            return cmd_demo(args, settings)
        if args.command == "run":
            return cmd_run(args, settings)
        if args.command == "batch":
            return cmd_batch(args, settings)
    except FfmpegNotFound as exc:
        log.error(str(exc))
        return 1
    except KeyboardInterrupt:
        log.error("interrupted")
        return 130
    except StageError as exc:
        log.error(f"stage failed: {exc}")
        return 1
    except Exception as exc:  # keep the traceback for --verbose only
        log.error(f"{type(exc).__name__}: {exc}")
        if args.verbose:
            raise
        log.info("re-run with --verbose for the full traceback")
        return 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
