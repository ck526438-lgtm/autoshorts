# Contributing

Thanks for reading this far. AutoShorts is deliberately small: five stages, one
dataclass per artefact, no orchestration framework. Keep it that way.

## Setup

```bash
git clone https://github.com/ck526438-lgtm/autoshorts
cd autoshorts
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[voice,ffmpeg,dev]"
pytest -q
autoshorts doctor
autoshorts demo --offline           # no network, no keys, still an mp4
```

## Where things live

```
autoshorts/
├── config.py          settings + niche YAML (never read os.environ elsewhere)
├── models.py          Script / Segment / Word / Media / JobPaths — the contracts
├── pipeline.py        the five resumable stages
├── llm/               chat providers (raw HTTPS), prompt, offline template writer
├── tts/               engines + fallback chain
├── visuals/           pexels, pixabay, your folder, generated art, the planner
├── render/            align (word clocks), ass (captions), clips, mux (ffmpeg)
└── util/              log, text, media (ffmpeg discovery), http (cache), rss
```

## Conventions

- Type hints on public functions, `from __future__ import annotations`, no
  `Any` in return types unless the API really is untyped.
- **Optional dependencies import lazily** (`edge_tts`, `faster_whisper`,
  `piper`, `imageio_ffmpeg`). A missing extra must degrade, never crash import.
- **Never shell out with a string.** `subprocess.run([...])` only — scripts are
  data, not concatenated shell.
- Providers must return the same shapes as everything else (`list[Word]`,
  `Media`), so the pipeline stays agnostic.
- Comments explain *why* a constraint exists (see the zoompan and the ASS
  path-escaping notes). No comments that restate the code.
- Add a test for every stage you touch. Tests must not need network, ffmpeg, or
  an API key.

## Adding a provider

```python
# autoshorts/tts/myengine.py
def synth(text, settings, out, tools) -> list[Word]: ...
# register it in tts/providers.py PROVIDERS and mention the extra in pyproject
```

Visual providers only need `search(query, …) -> list[dict]` with the keys the
planner already reads (`kind`, `url`, `referrer`, `label`, `duration`,
`provider`), plus one line in `visuals/planner.py:_search`.

## Pull requests

One concern per PR. Include the command you ran and the output it produced —
rendering claims without a job folder is the fastest way to a close. `ruff check .`
and `pytest -q` must pass; CI runs both on Python 3.10 → 3.12.

## Issues

Bug reports need: OS + Python version, `autoshorts doctor` output, the command,
and the job folder (`script.json`, `captions.ass`, and the last 20 lines with
`--verbose`). Delete nothing from the folder — the intermediate wavs usually
explain the desync.
