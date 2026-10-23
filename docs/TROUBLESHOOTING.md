# Troubleshooting

## "ffmpeg was not found"

The resolver already tries `PATH`, then `imageio-ffmpeg`, then the usual install
folders. If it still fails:

```bash
pip install "autoshorts[ffmpeg]"        # any OS, no admin rights
brew install ffmpeg                     # macOS
sudo apt install ffmpeg                 # Debian/Ubuntu
winget install Gyan.FFmpeg              # Windows
```

Or point at a binary directly: `FFMPEG_BIN=C:/Tools/ffmpeg-7.1/bin/ffmpeg.exe`.

`autoshorts doctor` prints the exact path and where it came from.

## Captions are out of sync

1. Which clock was used? `script.json → segments[].words`. If it came from the
   estimator (visible with `--verbose`), install `edge-tts` (`[voice]`) or
   `faster-whisper` (`[whisper]`) — both give real timestamps.
2. The aligner rescales engine timings onto the measured take length, so a
   residual drift usually means the take was re-used from an older run. Fix it
   with `--force voice`.
3. Captions longer than the group budget overlap and get clipped — that is
   intentional (`flatten` cuts the previous event). Lower `max_seconds` in
   `render/ass.py:group_words` for faster talkers.

## Subtitles do not appear at all

Your ffmpeg build has no libass. AutoShorts detects this and embeds a
switchable `mov_text` track instead (the log says so). TikTok/YouTube will not
burn it, so install a full build — `ffmpeg -filters | grep ass` should list
`subtitles` and `ass`.

## Font looks wrong, or boxes instead of letters

`CAPTION_FONT` must name a font that is *installed on the machine doing the
render*. `Arial Black` is present on Windows and macOS; on Linux try
`DejaVu Sans` or install a heavy face, then set `CAPTION_FONT`. Extra fonts:
drop them in a folder and add that folder to `FONTCONFIG_PATH` (Linux) — libass
does not read a `fontsdir` that ffmpeg was not built with.

## edge-tts: "returned no audio"

Microsoft rate-limits this free endpoint. Either slow the batch down, set
`TTS_PROVIDER=system` (offline, no key), or use `TTS_PROVIDER=openai` /
`piper`. AutoShorts already falls back to the OS voice and tells you when it
does.

## Voice sounds robotic

`TTS_RATE` and voice choice matter more than the engine for most listeners.
Try `en-US-EmmaMultilingualNeural`, `fr-FR-DenisNeural`,
`es-ES-XimenaNeural`, and set `TTS_RATE=+12%` — short-form audiences read
slower than they listen.

## Stock footage is off-topic

`STOCK_PRIORITY=pexels,pixabay` and check `plan.json` — it records which shot
was chosen for which segment and the query that found it. Weak `visual_query`
strings usually mean a weak model answer; the prompt asks for
*what is on screen*, not the abstract idea. Keeping a `keywords:` list in your
niche file fixes 80 % of this.

## Render is huge

`final.mp4` is CRF 19 at 1080×1920 — about 4–8 MB for 45 s. For a smaller post
build, raise `crf` in `render/mux.py` or render at 720×1280
(`--width 720 --height 1280`).

## Platform rules

TikTok, YouTube and Instagram all require labeling AI-generated realistic
content, and Shorts monetisation can be withheld for mass-produced or repeated
content. Concretely:

- Turn on the "AI-generated" label when you upload. It is a checkbox, and
  skipping it risks removal or demonetisation.
- Do not post the same narration across accounts; vary `--count`, the niche
  file, and the source.
- Do not let an unreviewed script make medical, financial or political claims.
- Respect the stock libraries' licences: Pexels and Pixabay both forbid
  reselling the footage as-is and imply no endorsement — `metadata.json` keeps
  the trail so you can prove where a clip came from.

## Jobs pile up

`output/` grows fast because every take and clip is kept for resume.
`--prune` deletes `clips/*.mp4` after a successful render; the audio stays so
captions can still be rebuilt for free.
