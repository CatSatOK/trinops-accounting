"""Spend categorisation via keyword rules — no API calls.

Scores each category by how many of its keywords appear in the invoice text
(vendor name weighted double, since 'X Travel Ltd' is a strong signal).
"""

from accounting.config import Settings
from accounting.logging_conf import get_logger

logger = get_logger(__name__)

DEFAULT_CATEGORY = "Uncategorised"


def categorise(text: str, vendor: str | None, settings: Settings) -> str:
    body = text.lower()
    vendor_lower = (vendor or "").lower()

    scores: dict[str, int] = {}
    for category, keywords in settings.category_keywords.items():
        score = 0
        for keyword in keywords:
            if keyword in vendor_lower:
                score += 2
            if keyword in body:
                score += 1
        if score:
            scores[category] = score

    if not scores:
        return DEFAULT_CATEGORY
    best = max(scores, key=lambda c: scores[c])
    logger.info("categorised %r as %s (scores=%s)", vendor, best, scores)
    return best
