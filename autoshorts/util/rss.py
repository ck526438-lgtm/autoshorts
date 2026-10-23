"""Read topics straight from a feed — stdlib XML, no feedparser dependency."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass
class FeedItem:
    title: str
    summary: str = ""
    link: str = ""


def _text(node: ET.Element | None) -> str:
    """itertext, because RSS titles embed markup like `<b>Postgres</b>`."""
    if node is None:
        return ""
    return _WS.sub(" ", _TAG.sub(" ", "".join(node.itertext()) or "")).strip()


def parse(xml_bytes: bytes, limit: int = 10) -> list[FeedItem]:
    root = ET.fromstring(xml_bytes)
    items: list[FeedItem] = []
    for item in list(root.iter("item")) + list(root.iter(f"{_ATOM}entry")):
        title = _text(item.find("title")) or _text(item.find(f"{_ATOM}title"))
        if not title:
            continue
        summary = (_text(item.find("description"))
                   or _text(item.find("summary"))
                   or _text(item.find(f"{_ATOM}summary"))
                   or _text(item.find(f"{_ATOM}content")))
        link = (_text(item.find("link")) or _text(item.find(f"{_ATOM}link")))
        items.append(FeedItem(title=title, summary=summary[:600], link=link))
        if len(items) >= limit:
            break
    return items


def fetch(url: str, limit: int = 10, timeout: float = 20.0) -> list[FeedItem]:
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "autoshorts/0.1 (RSS reader)"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return parse(response.content, limit=limit)
