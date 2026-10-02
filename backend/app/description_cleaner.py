"""HTML description cleaning utilities."""

from __future__ import annotations

import html
import re


_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&[a-zA-Z0-9#]+;")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def strip_tags(text: str) -> str:
    """Remove all HTML tags."""
    text = _TAG_RE.sub(" ", text)
    return text


def decode_html_entities(text: str) -> str:
    """Decode HTML entities like &lt; &gt; &amp; &#x27; etc."""
    return html.unescape(text)


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs to single space; collapse 3+ newlines to 2."""
    text = _WHITESPACE_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def clean_html_description(raw: str, max_length: int = 4000) -> str:
    """Full pipeline: decode entities → strip tags → normalize whitespace → truncate."""
    if not raw:
        return ""
    text = decode_html_entities(raw)
    text = strip_tags(text)
    text = normalize_whitespace(text)
    if max_length and len(text) > max_length:
        text = text[:max_length].rsplit(" ", 1)[0] + "…"
    return text


def truncate_description_cleanly(text: str, length: int = 300) -> str:
    """Truncate a cleaned description to a snippet at a word boundary."""
    text = clean_html_description(text, max_length=length + 200)
    if len(text) <= length:
        return text
    return text[:length].rsplit(" ", 1)[0] + "…"
