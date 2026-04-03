"""Helpers for weakly-obscured protected term storage."""

from __future__ import annotations

import base64


DEFAULT_ENCODING = "base64"


def encode_term(term: str, encoding: str = DEFAULT_ENCODING) -> str:
    if encoding != "base64":
        raise ValueError(f"Unsupported protected term encoding: {encoding}")
    return base64.b64encode(term.encode("utf-8")).decode("ascii")


def decode_term(term_encoded: str, encoding: str = DEFAULT_ENCODING) -> str:
    if encoding != "base64":
        raise ValueError(f"Unsupported protected term encoding: {encoding}")
    return base64.b64decode(term_encoded.encode("ascii")).decode("utf-8")
