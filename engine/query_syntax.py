"""Query syntax parsing for SelfIndex.

This module implements the "unlock-style" prefixes:
- By default, only the "default" recall domain is searchable.
- Users must explicitly opt-in to additional recall domains by typing a prefix.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedQuery:
    raw: str
    cleaned: str
    allowed_domains: tuple[str, ...]
    used_prefixes: tuple[str, ...]


def parse_unlock_prefixes(
    query: str,
    *,
    identity_prefix: str = ":",
    sensitive_prefix: str = "!",
) -> ParsedQuery:
    raw = (query or "").strip()
    if not raw:
        return ParsedQuery(raw="", cleaned="", allowed_domains=("default",), used_prefixes=())

    prefixes = []
    idx = 0
    while idx < len(raw):
        ch = raw[idx]
        if ch.isspace():
            idx += 1
            continue
        if ch == identity_prefix or ch == sensitive_prefix:
            prefixes.append(ch)
            idx += 1
            continue
        break

    cleaned = raw[idx:].strip()
    allowed = {"default"}
    if identity_prefix in prefixes:
        allowed.add("identity")
    if sensitive_prefix in prefixes:
        allowed.add("sensitive")

    used_prefixes = tuple(dict.fromkeys(prefixes).keys())
    return ParsedQuery(
        raw=raw,
        cleaned=cleaned,
        allowed_domains=tuple(sorted(allowed)),
        used_prefixes=used_prefixes,
    )

