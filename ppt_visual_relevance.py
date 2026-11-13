"""Strict, token-based relevance checks for presentation stock imagery.

Metadata matching is a conservative filter, not visual recognition. When confidence is
insufficient the caller should fall back to an authored diagram rather than guess.
"""
from __future__ import annotations

import re
import unicodedata

_STOP = {
    "with", "from", "that", "this", "over", "under", "into", "near", "dark",
    "light", "mysterious", "dramatic", "beautiful", "photo", "image", "scene",
    "and", "the", "for", "with", "about", "view", "high", "quality",
}
_BIOLOGY_CONTEXT = {
    "biology", "biological", "medical", "medicine", "anatomy", "cardiovascular",
    "heart", "organ", "organoid", "tissue", "cell", "genetic", "dna", "sheep",
    "dolly", "cloning", "clone", "cloned", "nuclear", "embryo", "phenotype",
}
_BIOLOGY_FALSE_POSITIVES = {
    "lego", "toy", "toys", "stormtrooper", "beetle", "insect", "bug",
    "ladybug", "scarab", "figurine", "actionfigure", "minifigure",
}


def _tokens(value: str) -> set[str]:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return set(re.findall(r"[a-z0-9]+", value))


def metadata_relevant(query: str, metadata: str, minimum: int = 2) -> bool:
    """Require exact whole-token overlap; substrings such as 'art' in 'artificial' do not count."""
    terms = _tokens(query) - _STOP
    if not terms:
        return False
    tags = _tokens(metadata)
    required = max(1, min(int(minimum), len(terms)))
    return len(terms & tags) >= required


def contextually_irrelevant(context: str, metadata: str) -> bool:
    """Reject known cross-domain stock-photo traps for biology/medical presentations."""
    context_terms = _tokens(context)
    if not (context_terms & _BIOLOGY_CONTEXT):
        return False
    # Do not block a subject explicitly requested by the slide (e.g. beetle biology).
    return bool((_tokens(metadata) & _BIOLOGY_FALSE_POSITIVES) - context_terms)
