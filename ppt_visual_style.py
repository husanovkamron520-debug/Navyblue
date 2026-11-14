"""Photographic-first visual style policy for Navyblue slide assets.

Searches for scene-specific photographs or photorealistic 3D renders. Flat vector,
cartoon, anime, clipart and hand-drawn assets are rejected as photo replacements.
"""
from __future__ import annotations

import re
import unicodedata


_NON_PHOTO_TERMS = {
    "cartoon", "cartoons", "vector", "vectors", "illustration", "illustrations",
    "clipart", "icon", "icons", "anime", "manga", "comic", "comics", "drawing",
    "drawings", "painting", "paintings", "flat", "sticker", "storybook",
    "2d", "watercolor", "sketch", "lineart", "miniature", "engraving", "etching",
    "lithograph", "fresco", "woodcut", "manuscript", "illumination",
    "digital art", "concept art", "oil painting", "watercolor painting", "pencil drawing",
    "vector art", "graphic illustration", "3d cartoon", "animated", "cgi cartoon",
}


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def is_nonphotographic_metadata(metadata: str) -> bool:
    """Reject explicitly illustrated/cartoon-style results in photographic slots.

    Phrase checks catch common stock labels; token checks catch variants such as
    'vector artwork' and 'anime portrait'. Photorealistic 3D renders remain allowed.
    """
    folded = _fold(metadata)
    tokens = set(folded.split())
    if tokens & _NON_PHOTO_TERMS:
        return True
    return any(phrase in folded for phrase in (
        "digital art", "concept art", "oil painting", "watercolor painting",
        "pencil drawing", "vector art", "graphic illustration", "3d cartoon",
        "animated character",
    ))


def build_photorealistic_query(domain: str, topic: str, title: str, body: str = "") -> str:
    """Build a scene-specific English query with a photographic/realistic-render target."""
    text = _fold(" ".join((topic, title, body)))
    domain = _fold(domain)

    if domain in {"biology", "science"}:
        rules = (
            (("dna", "genome", "genetic", "adn"), "photorealistic scientific 3D render DNA molecular structure laboratory visualization"),
            (("cell", "hujayra", "membrane", "organelle"), "photorealistic scientific 3D render biological cell membrane organelles"),
            (("plant", "o simlik", "leaf", "photosynthesis", "barg"), "high detail macro photograph real plant leaf photosynthesis nature"),
            (("animal", "hayvon", "wildlife", "mammal"), "wildlife documentary photograph animal in natural habitat"),
            (("bacteria", "bacterium", "virus", "microbe", "mikrob"), "photorealistic scientific microscopic 3D visualization microorganism"),
            (("ecosystem", "ekosistema", "food chain", "ozuqa zanjiri"), "photorealistic nature documentary photograph ecosystem biodiversity"),
        )
        for terms, query in rules:
            if any(term in text for term in terms):
                return query
        subject = " ".join(x for x in (topic, title) if x).strip()[:140]
        return f"photorealistic scientific documentary photograph or accurate 3D render {subject}".strip()

    if domain in {"medical", "cardiovascular"}:
        rules = (
            (("ecg", "electrocardiogram", "heart rhythm", "pulse", "yurak ritm", "puls"),
             "clinical electrocardiogram monitor real hospital photograph"),
            (("erythrocyte", "red blood cell", "blood cells", "eritrotsit", "eritrosit", "leykotsit", "trombotsit", "qon tarkib", "qon hujay", "platelet"),
             "photorealistic 3D medical render red blood cells inside human blood vessel"),
            (("artery", "vein", "capillary", "arteriya", "vena", "kapillyar", "tomir devor"),
             "photorealistic 3D medical render human artery vein capillary anatomy"),
            (("circulation", "blood flow", "qon aylanish", "pulmonary"),
             "photorealistic 3D medical render human cardiovascular circulation anatomy"),
            (("valve", "klapan", "qopqoq", "mitral", "aortic"),
             "photorealistic 3D medical render human heart valve anatomy closeup"),
            (("chamber", "atrium", "ventricle", "bo lmacha", "qorincha"),
             "photorealistic 3D medical render four chambers human heart anatomy"),
        )
        for terms, query in rules:
            if any(term in text for term in terms):
                return query
        subject = " ".join(x for x in (topic, title) if x).strip()[:140]
        return f"photorealistic anatomically accurate 3D medical render {subject}".strip()

    if domain in {"fiction", "fantasy", "remus", "remus lupin"} or "remus lupin" in text:
        rules = (
            (("patronus", "expecto patronum"),
             "cinematic photorealistic silver spectral wolf glowing moonlit forest fantasy film still"),
            (("werewolf", "likantrop", "bo ri", "full moon", "to lin oy"),
             "cinematic photorealistic werewolf silhouette full moon misty forest dark fantasy film still"),
            (("marauders", "marauder", "map", "xarita"),
             "photorealistic antique parchment magical castle map ink handwriting cinematic closeup"),
            (("tonks", "love", "sevgi"),
             "cinematic photorealistic young witch and wizard standing together gothic castle courtyard"),
            (("professor", "teacher", "dars", "hogwarts", "xogvarts"),
             "cinematic photorealistic wizard professor in ancient gothic classroom dramatic natural light"),
            (("phoenix", "feniks", "war", "jang", "battle", "urush"),
             "cinematic photorealistic fantasy resistance fighters gothic castle battle mist dramatic film still"),
        )
        for terms, query in rules:
            if any(term in text for term in terms):
                return query
        subject = " ".join(x for x in (topic, title) if x).strip()[:140]
        return f"cinematic photorealistic live action film still {subject} natural dramatic lighting".strip()

    # Keep the presentation topic in every generic query; slide titles like
    # "Conclusion" or "Introduction" are not meaningful search subjects alone.
    subject = re.sub(r"[^A-Za-z0-9 ]+", " ", " ".join((str(topic or ""), str(title or "")))).strip()
    subject = re.sub(r"\s+", " ", subject)[:150]
    return f"photorealistic editorial photograph {subject} natural cinematic lighting".strip()


_UZBEK_STOCK_MARKERS = {
    "haqida", "uchun", "orqali", "tizimi", "tarixi", "davlat", "imperiyasi",
    "sultonligi", "harbiy", "madaniyati", "iqtisodiy", "rivojlanish", "boshqaruv",
    "jarayoni", "xususiyatlari", "muammolari", "yechimlari", "qon", "yurak",
    "tomir", "ta'minot", "zanjiri", "ombor", "ishlab", "chiqarish", "samaradorligi",
    "tahlili", "asoslari", "mintaqasi", "hududi", "shahar", "sanoat", "o'zbekiston",
    "uzbekiston", "qadimgi", "o'rta", "asrlar", "imperiya", "sivilizatsiya",
}


def needs_english_stock_translation(query: str) -> bool:
    """Detect Uzbek/Russian/Cyrillic stock queries even when Uzbek uses Latin letters."""
    raw = str(query or "").strip()
    if not raw:
        return False
    if any(ord(char) > 127 for char in raw):
        return True
    tokens = set(_fold(raw).split())
    if tokens & _UZBEK_STOCK_MARKERS:
        return True
    # Common Uzbek suffixes on otherwise Latin-script words.
    return bool(re.search(r"\b[a-z]+(?:ning|lari|lar|dagi|dan|ga|ni|lik|chi)\b", _fold(raw)))
