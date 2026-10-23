"""Voiceover engines. Each returns a WAV file and, when possible, word timings.

Providers are ordered by how little they ask of the user:
  edge    free Microsoft neural voices, no key, real word timings (needs internet)
  openai  best quality, needs OPENAI_API_KEY
  piper   fully local neural voices
  system  your OS voice: SAPI (Windows), `say` (macOS), espeak-ng (Linux)
  silence synthesised timing track — lets the render path run in CI
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import wave
from pathlib import Path

import httpx

from autoshorts.config import Settings
from autoshorts.models import Word
from autoshorts.util import log
from autoshorts.util.media import Tools, run


class TtsError(RuntimeError):
    pass


def _to_wav(tools: Tools, src: Path, dst: Path) -> Path:
    run([tools.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
         "-ar", "48000", "-ac", "1", dst])
    if src.suffix.lower() != ".wav" and src != dst:
        src.unlink(missing_ok=True)  # keep job folders tidy
    return dst


# --------------------------------------------------------------------------- edge
def edge(text: str, settings: Settings, out: Path, tools: Tools) -> list[Word]:
    try:
        import edge_tts
    except Exception as exc:  # pragma: no cover - optional dependency
        raise TtsError("edge-tts not installed — pip install \"autoshorts[voice]\"") from exc

    rate = settings.tts_rate or "+0%"
    if not rate.startswith(("+", "-")):
        rate = f"+{rate}"
    communicate = edge_tts.Communicate(text, voice=settings.edge_voice, rate=rate)
    mp3 = out.with_suffix(".mp3")

    async def _stream() -> list[Word]:
        audio = bytearray()
        timed: list[Word] = []
        async for chunk in communicate.stream():
            kind = chunk.get("type")
            if kind == "audio":
                audio.extend(chunk.get("data") or b"")
            elif kind == "WordBoundary":
                start = float(chunk.get("offset", 0)) / 1e7
                dur = float(chunk.get("duration", 0)) / 1e7
                word = (chunk.get("text") or "").strip()
                if word:
                    timed.append(Word(word, round(start, 3), round(start + dur, 3)))
        if not audio:
            raise TtsError("edge-tts returned no audio (rate limit or no internet)")
        mp3.write_bytes(bytes(audio))
        return timed

    try:
        words = asyncio.run(_stream())
    except TtsError:
        raise
    except Exception as exc:
        raise TtsError(f"edge-tts failed: {type(exc).__name__}: {exc}") from exc
    _to_wav(tools, mp3, out)
    return words


# -------------------------------------------------------------------------- openai
def openai_tts(text: str, settings: Settings, out: Path, tools: Tools) -> list[Word]:
    if not settings.openai_api_key:
        raise TtsError("OPENAI_API_KEY is empty")
    model = settings.llm_model or "gpt-4o-mini-tts"
    for candidate in (model, "gpt-4o-mini-tts", "tts-1"):
        try:
            with httpx.Client(timeout=180.0) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={"model": candidate, "voice": settings.openai_tts_voice,
                          "input": text, "response_format": "mp3"},
                )
                if response.status_code != 200:
                    continue
                body = response.content
            if len(body) < 1024:
                continue
            mp3 = out.with_suffix(".mp3")
            mp3.write_bytes(body)
            _to_wav(tools, mp3, out)
            log.debug(f"openai tts model={candidate} bytes={len(body)}")
            return []  # no word timestamps; the aligner estimates them
        except Exception:
            continue
    raise TtsError("OpenAI TTS rejected every model tried")


# --------------------------------------------------------------------------- piper
def piper(text: str, settings: Settings, out: Path, tools: Tools) -> list[Word]:
    binary = shutil.which(settings.piper_bin)
    if not binary:
        raise TtsError(f"piper binary {settings.piper_bin!r} not on PATH")
    txt = out.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    raw = out.with_suffix(".raw.wav")
    try:
        subprocess.run(
            [binary, "--model", settings.piper_voice, "--output_file", str(raw)],
            stdin=txt.open("r", encoding="utf-8"),
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}),
        )
    except subprocess.CalledProcessError as exc:
        raise TtsError(f"piper failed: {(exc.stderr or '').strip()[:200]}") from exc
    finally:
        txt.unlink(missing_ok=True)
    if not raw.is_file():
        raise TtsError("piper produced no audio file")
    _to_wav(tools, raw, out)
    raw.unlink(missing_ok=True)
    return []


# -------------------------------------------------------------------------- system
def system(text: str, settings: Settings, out: Path, tools: Tools) -> list[Word]:
    import os
    import sys
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        text_file = Path(fh.name)
    flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
    try:
        if sys.platform == "win32":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            if not shell:
                raise TtsError("powershell not found")
            # Voice name and rate travel through the environment, never the
            # command line, so a hostile niche file cannot inject PowerShell.
            ps = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$v = [Environment]::GetEnvironmentVariable('AUTOSHORTS_SAPI_VOICE');"
                "if ($v) { try { $s.SelectVoice($v) } catch {} };"
                "$r = [Environment]::GetEnvironmentVariable('AUTOSHORTS_SAPI_RATE');"
                "if ($r -ne $null) { $s.Rate = [int]$r };"
                f"$s.SetOutputToWaveFile('{out.as_posix()}');"
                f"$s.Speak([IO.File]::ReadAllText('{text_file.as_posix()}'));"
                "$s.Dispose();"
            )
            subprocess.run(
                [shell, "-NoProfile", "-Command", ps],
                check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                env={**os.environ,
                     "AUTOSHORTS_SAPI_VOICE": os.environ.get("SAPI_VOICE", ""),
                     "AUTOSHORTS_SAPI_RATE": str(_sapi_rate(settings.tts_rate))},
                **flags,
            )
            if not out.is_file():
                raise TtsError("SAPI wrote no wave file")
            return []
        if sys.platform == "darwin":
            aiff = out.with_suffix(".aiff")
            subprocess.run(["say", "-o", str(aiff), "--data-format=LEI16@22050", text],
                           check=True, capture_output=True)
            _to_wav(tools, aiff, out)
            aiff.unlink(missing_ok=True)
            return []
        for binary in ("espeak-ng", "espeak"):
            if shutil.which(binary):
                subprocess.run([binary, "-w", str(out), "-s", "165", text],
                               check=True, capture_output=True)
                return []
        raise TtsError("no system TTS found (install espeak-ng)")
    except subprocess.CalledProcessError as exc:
        raise TtsError(f"system TTS failed: {(exc.stderr or '').strip()[:200]}") from exc
    finally:
        text_file.unlink(missing_ok=True)


def _sapi_rate(tts_rate: str) -> int:
    """SAPI speaks in -10..10 semitone-ish steps; map a percent string onto it."""
    raw = (tts_rate or "+0%").replace("%", "").replace("+", "")
    try:
        return max(-10, min(10, round(float(raw) / 4)))
    except ValueError:
        return 1


# ------------------------------------------------------------------------- silence
def silence(text: str, settings: Settings, out: Path, tools: Tools) -> list[Word]:
    """Deterministic fake speech: keeps the render path testable without a voice."""
    from autoshorts.util.text import estimate_seconds
    from autoshorts.util.text import words as split

    tokens = split(text) or ["…"]
    total = max(1.0, estimate_seconds(text, settings.words_per_minute))
    step = total / len(tokens)
    timed = [
        Word(token, round(i * step, 3), round((i + 1) * step, 3))
        for i, token in enumerate(tokens)
    ]
    sample_rate = 24000
    frames = bytearray()
    for index in range(int(total * sample_rate)):
        # Very quiet noise floor so ffmpeg has real audio to work with.
        frames += (200 if index % 97 else 120).to_bytes(2, "little", signed=True)
    with wave.open(str(out), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(frames))
    return timed


PROVIDERS = {
    "edge": edge,
    "openai": openai_tts,
    "piper": piper,
    "system": system,
    "silence": silence,
}
