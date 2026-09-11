"""Shared string/date helpers used by the OCR, validation and scoring modules."""
from __future__ import annotations

import re
from datetime import date, datetime


def jaro_winkler(s1: str, s2: str) -> float:
    """Jaro-Winkler similarity in [0, 1]."""
    s1, s2 = s1.strip().upper(), s2.strip().upper()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    match_dist = max(len(s1), len(s2)) // 2 - 1
    s1_matches = [False] * len(s1)
    s2_matches = [False] * len(s2)
    matches = 0
    for i, ch in enumerate(s1):
        lo = max(0, i - match_dist)
        hi = min(len(s2), i + match_dist + 1)
        for j in range(lo, hi):
            if not s2_matches[j] and s2[j] == ch:
                s1_matches[i] = s2_matches[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions = 0
    k = 0
    for i, ch in enumerate(s1):
        if s1_matches[i]:
            while not s2_matches[k]:
                k += 1
            if ch != s2[k]:
                transpositions += 1
            k += 1
    jaro = (matches / len(s1) + matches / len(s2) +
            (matches - transpositions / 2) / matches) / 3
    prefix = 0
    for a, b in zip(s1, s2):
        if a == b:
            prefix += 1
        else:
            break
    return jaro + min(prefix, 4) * 0.1 * (1 - jaro)


def levenshtein_ratio(s1: str, s2: str) -> float:
    s1, s2 = s1.strip().upper(), s2.strip().upper()
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1, 1):
        cur = [i]
        for j, c2 in enumerate(s2, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (c1 != c2)))
        prev = cur
    return 1 - prev[-1] / max(len(s1), len(s2))


_DATE_PATTERNS = [
    (re.compile(r"^(\d{2})[ ./\-]?(\d{2})[ ./\-]?(\d{4})$"), "dmy4"),
    (re.compile(r"^(\d{4})[ ./\-]?(\d{2})[ ./\-]?(\d{2})$"), "ymd"),
    (re.compile(r"^(\d{2})[ ./\-]?(\d{2})[ ./\-]?(\d{2})$"), "dmy2"),
    (re.compile(r"^(\d{2})[ ./\-]?(\d{2})[ ./\-]?(\d{2})$"), "ymd2"),
]


def parse_date(raw):
    """Parse DD MM YYYY style dates found on ID documents. Returns date|None."""
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw
    text = re.sub(r"[.\-/]", " ", str(raw).strip())
    text = re.sub(r"\s+", " ", text)
    m = re.match(r"^(\d{1,2}) (\d{1,2}) (\d{4})$", text)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    m = re.match(r"^(\d{4}) (\d{1,2}) (\d{1,2})$", text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))
