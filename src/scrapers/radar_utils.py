"""Shared helpers for the product and open-source radar scrapers."""

import re
from typing import Iterable


def matches_keywords(parts: Iterable[object], keywords: Iterable[str]) -> bool:
    """Return whether text contains at least one configured radar keyword.

    Short keywords such as ``ai`` are matched as tokens to avoid false
    positives in words such as ``maintainable``.
    """
    haystack = " ".join(str(part or "") for part in parts).lower()
    for raw_keyword in keywords:
        keyword = raw_keyword.strip().lower()
        if not keyword:
            continue
        if len(keyword) <= 3 and keyword.isalnum():
            if re.search(rf"\b{re.escape(keyword)}\b", haystack):
                return True
        elif keyword in haystack:
            return True
    return False


def coerce_int(value: object) -> int:
    """Convert API or human-formatted integer values to an integer."""
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
