"""Every command printed in the docs must parse with the real CLI."""
import re
import shlex
from pathlib import Path

import pytest

from autoshorts.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
VERBS = {"run", "demo", "batch", "doctor", "niche"}


def _argv(body: str) -> list[str]:
    argv = shlex.split(body, posix=True)
    return argv[: argv.index("#")] if "#" in argv else argv


def _commands() -> list[str]:
    found = set()
    for name in ("README.md", "docs/index.html", "CONTRIBUTING.md"):
        text = re.sub(r"<[^>]+>", " ", (ROOT / name).read_text(encoding="utf-8"))
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("autoshorts "):
                continue
            body = line[len("autoshorts"):].strip()
            if "…" in body or "<" in body or "$" in body:
                continue
            argv = _argv(body)
            if argv and argv[0] in VERBS:
                found.add(body)
    return sorted(found)


@pytest.mark.parametrize("body", _commands(), ids=lambda b: b[:44])
def test_documented_command_parses(body):
    try:
        build_parser().parse_args(_argv(body))
    except SystemExit:
        pytest.fail(f"`autoshorts {body}` is not a command the CLI accepts")


def test_docs_cover_most_of_the_cli():
    assert len(_commands()) >= 12
