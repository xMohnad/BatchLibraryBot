import unicodedata

from rapidfuzz import fuzz, process


def normalize(text: str) -> str:
    """Normalize text for comparison."""
    text = text.replace("\u0640", "").strip().lower()
    return unicodedata.normalize("NFKC", text)


def resolve_best_match(
    query: str,
    candidates: list[str],
    threshold: int = 78,
    scorer=fuzz.WRatio,
) -> str | None:
    """Return the best fuzzy match for `query` among `candidates`."""
    normalized_query = normalize(query)
    normalized_map = {candidate: normalize(candidate) for candidate in candidates}

    for original, normalized in normalized_map.items():
        if normalized == normalized_query:
            return original

    match = process.extractOne(normalized_query, normalized_map, scorer=scorer)
    if match and match[1] >= threshold:
        return match[2]

    return None


def fuzzy_score(
    query: str,
    *fields: str | None,
    threshold: int = 70,
    scorer=fuzz.WRatio,
) -> float | None:
    """Return the best fuzzy match score of `query` across `fields`."""
    normalized_query = normalize(query)
    best = 0.0
    for field in fields:
        if not field:
            continue
        best = max(best, scorer(normalized_query, normalize(field)))
    return best if best >= threshold else None
