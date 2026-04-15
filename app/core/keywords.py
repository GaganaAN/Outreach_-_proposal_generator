import re
from typing import Iterable, List


def normalize_keywords(raw_keywords: Iterable[str]) -> List[str]:
    """
    Normalize keywords that may be entered as:
    - one per line
    - comma/semicolon-separated
    - with surrounding quotes or brackets
    """
    if not raw_keywords:
        return []

    tokens: List[str] = []
    for item in raw_keywords:
        if item is None:
            continue
        text = str(item).strip()
        if not text:
            continue

        parts = re.split(r"[,\n;]+", text)
        for part in parts:
            cleaned = part.strip()
            if not cleaned:
                continue
            cleaned = cleaned.strip("[](){}")
            cleaned = cleaned.strip().strip('"').strip("'").strip()
            cleaned = re.sub(r"\s+", " ", cleaned)
            if cleaned:
                tokens.append(cleaned)

    seen = set()
    deduped: List[str] = []
    for token in tokens:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(token)
    return deduped
