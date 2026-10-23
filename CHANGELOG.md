# Changelog

## 0.1.0

First release of the pipeline.

- Five resumable stages: script → voice → b-roll → captions → render.
- Script writers: OpenAI, Anthropic, Ollama (plain HTTPS, no SDKs) plus an
  offline template writer so a missing key degrades instead of failing.
- Retention-shaped prompt with a hard word budget derived from `TTS_RATE`.
- Voice engines: edge-tts (free, no key, real word timings), OpenAI TTS, Piper,
  OS voices (SAPI / `say` / espeak-ng) and a `silence` engine for CI.
- Word clocks fall back TTS timings → Whisper → proportional estimate, then get
  rescaled onto the measured take so captions cannot drift.
- ASS karaoke captions: per-word fill, line pop, thought-boundary grouping,
  safe-zone margins, per-channel font and colour; `.srt` fallback for ffmpeg
  builds without libass.
- B-roll: Pexels, Pixabay, your own clip folder, or generated art (Pillow) —
  cached downloads, licence trail in `metadata.json`.
- ffmpeg: auto-discovery including `imageio-ffmpeg`, stream-copy concat with a
  duration-drift safety net, `-14 LUFS` voice, side-chain-ducked music bed.
- CLI: `demo`, `run` (`--until`, `--force`, `--job`, `--count`, `--dry-run`),
  `batch --rss/--topics-file`, `doctor`, `niche init/list`.
- Docs: README, CONTRIBUTING, troubleshooting, CI matrix (Linux/macOS/Windows,
  Python 3.10–3.13) with an offline render smoke test.
