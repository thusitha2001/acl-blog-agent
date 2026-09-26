"""Keyword extraction and gap analysis from live page text."""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from collections import Counter
from functools import lru_cache
from typing import Any, Optional

from acl_agent.metrics import DEFAULT_METRICS, UNAVAILABLE, MetricProvider

logger = logging.getLogger(__name__)

_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "your", "our",
    "are", "was", "were", "have", "has", "had", "not", "but", "you",
    "all", "can", "will", "just", "about", "into", "more", "than",
    "also", "when", "what", "which", "their", "them", "they", "then",
    "some", "been", "each", "very", "here", "there", "over", "after",
    "before", "other", "only", "most", "such", "like", "best", "how",
    "to", "a", "an", "of", "in", "on", "at", "or", "by", "it", "is",
}

_QUESTION = re.compile(
    r"^(how|what|why|when|where|which|who|can|should|does|do|is|are)\b",
    re.I,
)
_BOILERPLATE = re.compile(
    r"\b(buy|shop|shopping|online|price|prices|cheap|deal|deals|cart|"
    r"checkout|collection|collections|store|marketplace|shipping|"
    r"best prices?|for men & women|men & women)\b",
    re.I,
)
_NAV = re.compile(
    r"\b(home|menu|login|sign in|account|wishlist|filter|sort|"
    r"related searches|skip to|add to cart|shop now|asked questions|faqs?|"
    r"final thoughts|table of contents|related posts)\b",
    re.I,
)
_BRANDISH = re.compile(
    r"\b(amazon|bewakoof|crazymonk|flipkart|myntra|ajio|nike|adidas|"
    r"zara|h&m|uniqlo|walmart|ebay|etsy|shopify|pinterest|instagram|"
    r"facebook|tiktok|youtube|twitter)\b",
    re.I,
)
_GARMENTS = {
    "hoodie", "hoodies", "shirt", "shirts", "tshirt", "tshirts", "tee", "tees",
    "jacket", "jackets", "jean", "jeans", "pant", "pants", "dress", "dresses",
    "sweater", "sweatshirt", "coat", "coats",
}
_MAX_KEYWORD_WORDS = 7
_MAX_KEYWORD_CHARS = 60

_ARTICLES = {"a", "an", "the"}
_CONJUNCTIONS = {
    "and", "but", "or", "nor", "so", "yet", "because", "while", "although",
    "if", "than", "as", "whether",
}
_PRONOUNS = {
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "she", "his",
    "her", "it", "its", "they", "them", "their", "this", "that", "these",
    "those", "one", "ones", "something", "anything", "everything", "what",
    "which", "who", "whom", "whose",
}
_VERBS = {
    "is", "are", "was", "were", "be", "been", "being", "am", "do", "does",
    "did", "done", "have", "has", "had", "can", "could", "will", "would",
    "shall", "should", "may", "might", "must", "come", "comes", "came", "get",
    "gets", "got", "go", "goes", "make", "makes", "made", "take", "takes",
    "add", "adds", "require", "requires", "need", "needs", "pair", "use",
    "uses", "used", "look", "looks", "keep", "keeps", "give", "gives", "find",
    "want", "try", "help", "helps", "work", "works", "become", "becomes",
    "seem", "seems", "feel", "feels", "let", "put", "choose", "create",
    "creates", "provide", "provides", "offer", "offers", "include",
    "includes", "ensure", "protect", "protects", "prevent", "allow", "allows",
    "bring", "brings", "turn", "show", "see", "know", "think", "say", "tell",
    "love", "enjoy", "consider", "last", "lasts", "stay", "stays", "tend",
    "tends", "depend", "depends", "vary", "varies", "replace", "clean", "wash",
    "buy", "wipe", "measure", "select", "pick", "decorate", "mix", "arrange",
    "remove", "apply", "place", "hang", "dry", "matter", "await", "explore",
    "discover", "learn", "combine", "define", "weave", "transform",
}
_ING_NOUNS = {
    "wedding", "bedding", "clothing", "sewing", "quilting", "stitching",
    "knitting", "printing", "dining", "lighting", "building", "painting",
    "ceiling", "spring", "string", "ring", "thing", "morning", "evening",
    "cooking", "cleaning", "washing", "ironing", "flooring", "seating",
    "serving", "setting", "layering", "padding", "lining", "piping",
    "binding", "backing", "stuffing", "trimming", "beading", "digitizing",
    "embroidering", "crocheting", "hemming", "packaging", "branding",
}
_EDITORIAL_ADJECTIVES = {
    "passionate", "favorite", "favourite", "ultimate", "amazing", "wonderful",
    "lovely", "stunning", "gorgeous", "fantastic", "awesome", "incredible",
    "delightful", "exciting", "fascinating", "charming", "magical",
    "exquisite", "breathtaking", "real", "pretty", "nice", "cute", "cool",
    "great", "perfect", "fun",
}
_ADJECTIVE_ONLY = {
    "cool", "chic", "casual", "neutral", "minimalist", "sporty", "trendy",
    "viral", "retro", "sleek", "bold", "feminine", "flirty", "comfy", "cozy",
    "everyday", "effortless", "honest", "fresh", "timeless", "chunky",
}
_ADVERB_SUFFIXES = (
    "ally", "fully", "ously", "ively", "ently", "antly", "ably", "ibly",
    "lessly", "edly", "ingly", "really",
)
_IDIOMS = [
    "hard way", "long run", "end of the day", "at the end", "for what its worth",
    "at the same time", "piece of cake", "best of both worlds", "game changer",
    "go to", "at a glance", "in a nutshell", "tip of the iceberg",
]
CLOSING_SECTIONS = [
    "final thoughts", "final words", "final verdict", "closing thoughts",
    "concluding thoughts", "last words", "parting words", "parting thoughts",
    "in conclusion", "to conclude", "wrapping up", "wrap up", "to sum up",
    "summing up", "in summary", "key takeaways", "bottom line", "conclusion",
    "summary", "verdict",
]
_FIGURATIVE_NOUNS = {
    "journey", "realm", "world", "magic", "beauty", "essence", "secret",
    "charm", "creativity", "passion", "inspiration", "adventure", "wonder",
}
_FIGURATIVE_OF_HEADS = _FIGURATIVE_NOUNS | {"art", "thread", "heart", "power", "touch", "tapestry"}
_PLURAL_MODIFIERS = {
    "kids", "mens", "womens", "sports", "arts", "news", "series", "species",
    "christmas", "always",
}
_YEAR = re.compile(r"^(19|20)\d{2}$")
_PREPOSITIONS = {
    "of", "to", "in", "on", "at", "by", "for", "with", "from", "into", "onto",
    "over", "under", "about", "around", "through", "between", "without",
    "within", "during", "before", "after", "above", "below", "off", "out",
    "up", "down", "per", "via", "like", "across", "along", "behind",
    "beyond", "near", "upon", "vs", "versus", "regarding", "concerning",
    "including",
}
_QUANTIFIERS = {
    "many", "much", "more", "most", "some", "any", "all", "each", "every",
    "few", "several", "various", "other", "another", "such", "same", "own",
    "very", "really", "just", "also", "even", "still", "only", "too",
    "quite", "often", "always", "never", "usually", "here", "there", "now",
    "then", "when", "where", "why", "how", "well", "not", "no", "lots",
    "both", "either", "neither",
}
_FILLER_NOUNS = {"kind", "kinds", "sort", "sorts", "lot", "bit", "number"}
_GENERIC_ADJECTIVES = {
    "different", "great", "good", "best", "better", "nice", "perfect", "easy",
    "simple", "important", "new", "right", "wrong", "big", "little",
    "beautiful", "ideal", "whole", "entire", "certain", "main", "possible",
    "available", "sure", "able", "true", "real", "ready", "popular", "common",
    "unique", "special", "typical", "usual", "general", "basic", "extra",
    "stylish", "elegant", "practical", "durable", "versatile",
}
_GENERIC_HEADS = {
    "type", "way", "thing", "idea", "option", "tip", "example", "variety",
    "choice", "piece",
}
_VAGUE_HEADS = {"thing", "stuff", "lot", "bit", "something", "everything", "anything"}
_INTERNAL_OK = {"of", "for", "with", "vs", "versus"}
GAP_HIGH_RELEVANCE = 0.35
GAP_MIN_RELEVANCE = 0.2
_FUNCTION_WORDS = (
    _ARTICLES | _CONJUNCTIONS | _PRONOUNS | _VERBS | _PREPOSITIONS
    | _QUANTIFIERS | _FILLER_NOUNS
)
_COMMON_NOUNS = {
    "size", "material", "design", "feature", "technique", "experience",
    "damage", "care", "color", "colour", "pattern", "shape", "fabric",
    "style", "decor", "table", "set", "mat", "linen", "cotton", "wool", "silk",
    "leather", "cork", "wood", "bamboo", "vinyl", "plastic", "jute", "denim",
    "velvet", "lace", "texture", "finish", "weight", "length", "width",
    "price", "cost", "budget", "guide", "list", "chart", "occasion", "party",
    "wedding", "dinner", "brunch", "holiday", "season", "home", "kitchen",
    "room", "bed", "bedding", "sheet", "napkin", "runner", "tablecloth",
    "placemat", "coaster", "quilt", "throw", "blanket", "towel", "hoodie",
    "shirt", "outfit", "wardrobe", "fit", "trip", "itinerary", "temple",
    "hotel", "food", "weather", "stain", "heat", "water", "surface",
    "history", "origin", "meaning", "benefit", "quality", "comfort", "layer",
    "theme", "palette", "centerpiece", "count", "stitch", "needle", "thread",
    "hoop", "machine", "wear", "top", "skirt", "jean", "sneaker", "shoe",
    "blazer", "sweater", "dress", "jacket", "boot",
}
_NOUN_SUFFIXES = (
    "tion", "sion", "ment", "ness", "ity", "ance", "ence", "ship", "ure",
    "ism", "age", "ery", "ics", "hood", "dom",
)
_ED_NOUNS = {"bed", "thread", "bread", "seed", "speed", "shed", "feed", "reed", "weed"}
_PHRASE_BOUNDARY = re.compile(r"[.!?;:,\n\r|()\[\]{}\"“”•·–—/]+|\s-\s")
_PHRASE_WORD = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def fold_accents(text: str) -> str:
    """Fold accented letters to ASCII (appliqué -> applique) instead of dropping them."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _clean(text: str) -> str:
    return fold_accents(text).lower().replace("'", "").replace("’", "")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{3,}", _clean(text))


def _stem(token: str) -> str:
    token = (token or "").lower()
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("sses"):
        return token
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def content_tokens(text: str) -> list[str]:
    return [_stem(token) for token in _tokens(text) if token not in _STOP]


def normalize_phrase(text: str) -> str:
    return " ".join(content_tokens(text))


def phrase_key(phrase: str) -> str:
    """Order-insensitive key so "come different" and "different come" collapse."""
    return " ".join(sorted(set(content_tokens(phrase)))) or (phrase or "").lower().strip()


def _phrase_words(text: str) -> list[str]:
    return _PHRASE_WORD.findall(_clean(text))


def phrase_segments(text: str) -> list[list[str]]:
    """Words per sentence/clause, so candidate phrases never cross a boundary."""
    segments = []
    for part in _PHRASE_BOUNDARY.split(text or ""):
        words = _phrase_words(part)
        if words:
            segments.append(words)
    return segments


_CHUNK_SKIP_POS = {"DET", "PRON", "NUM", "ADV", "PUNCT", "SYM", "AUX", "CCONJ", "PART", "SPACE"}
_CHUNK_HEAD_POS = {"NOUN", "PROPN"}
_CHUNK_TEXT_LIMIT = 60000


@lru_cache(maxsize=1)
def _spacy_nlp():
    """en_core_web_sm when installed and loadable; None keeps the word-list rules only."""
    if os.getenv("ACL_DISABLE_SPACY", "").strip().lower() in {"1", "true", "yes"}:
        return None
    try:
        import spacy

        return spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    except Exception as exc:
        logger.info("spaCy noun-chunk gate disabled: %s", exc)
        return None


def _chunk_tokens(chunk) -> list:
    tokens = list(chunk)
    while tokens and tokens[0].pos_ in _CHUNK_SKIP_POS:
        tokens = tokens[1:]
    return tokens


def _join_tokens(tokens) -> str:
    raw = "".join(getattr(token, "text_with_ws", f"{token.text} ") for token in tokens)
    return " ".join(_phrase_words(raw))


def noun_chunk_phrases(text: str) -> Optional[set[str]]:
    """Sub-spans of spaCy noun chunks that end on a noun, plus "X of/for/with/vs Y" joins.

    Returns None when spaCy is unavailable so callers fall back to search_phrase_check alone.
    """
    nlp = _spacy_nlp()
    if nlp is None:
        return None
    parts = [part for part in _PHRASE_BOUNDARY.split((text or "")[:_CHUNK_TEXT_LIMIT]) if part.strip()]
    allowed: set[str] = set()
    for doc in nlp.pipe(parts, batch_size=64):
        chunks = list(doc.noun_chunks)
        for chunk in chunks:
            tokens = _chunk_tokens(chunk)
            for end, token in enumerate(tokens):
                if token.pos_ not in _CHUNK_HEAD_POS:
                    continue
                for start in range(end + 1):
                    if tokens[start].pos_ not in _CHUNK_SKIP_POS:
                        allowed.add(_join_tokens(tokens[start:end + 1]))
        for left, right in zip(chunks, chunks[1:]):
            joiner = doc[left.end].text.lower() if left.end < len(doc) else ""
            if right.start != left.end + 1 or joiner not in _INTERNAL_OK:
                continue
            left_tokens, right_tokens = _chunk_tokens(left), _chunk_tokens(right)
            if not left_tokens or not right_tokens:
                continue
            if left_tokens[-1].pos_ not in _CHUNK_HEAD_POS or right_tokens[-1].pos_ not in _CHUNK_HEAD_POS:
                continue
            tail = _join_tokens(right_tokens)
            for start in range(len(left_tokens)):
                allowed.add(f"{_join_tokens(left_tokens[start:])} {joiner} {tail}")
    allowed.discard("")
    return allowed


def _is_function_word(word: str) -> bool:
    return word in _FUNCTION_WORDS or _stem(word) in _VERBS


def domain_nouns(*texts: str) -> set[str]:
    """Noun-ish stems from the title, H1/H2s, and target keyword."""
    nouns: set[str] = set()
    for text in texts:
        for word in _phrase_words(text):
            if len(word) < 3 or any(ch.isdigit() for ch in word):
                continue
            if _is_function_word(word) or word in _GENERIC_ADJECTIVES or word.endswith("ly"):
                continue
            if word in _EDITORIAL_ADJECTIVES or word in _ADJECTIVE_ONLY:
                continue
            if word.endswith("ing") and word not in _ING_NOUNS:
                continue
            nouns.add(_stem(word))
    return nouns


def _contains_run(words: list[str], target: list[str]) -> bool:
    size = len(target)
    return any(words[index:index + size] == target for index in range(len(words) - size + 1))


def is_closing_section(text: str) -> bool:
    """Conclusion/closing labels ("Final Words", "Wrapping Up", "Verdict") in any path."""
    words = fold_tokens(text)
    for item in CLOSING_SECTIONS:
        target = fold_tokens(item)
        if words == target or (len(target) > 1 and _contains_run(words, target)):
            return True
    return False


def _is_idiom(words: list[str]) -> bool:
    folded = [_stem(word) for word in words]
    return any(_contains_run(folded, fold_tokens(item)) for item in _IDIOMS)


def _plausible_noun(word: str, nouns: set[str]) -> bool:
    stem = _stem(word)
    if _is_function_word(word) or word in _GENERIC_ADJECTIVES or word.endswith("ly"):
        return False
    if word in _ADJECTIVE_ONLY or word in _EDITORIAL_ADJECTIVES:
        return False
    if word.endswith("ed") and len(word) > 4 and word not in _ED_NOUNS:
        return False
    if stem in nouns or stem in _COMMON_NOUNS or word in _ING_NOUNS:
        return True
    if word.endswith("ing"):
        return False
    if word.endswith(_NOUN_SUFFIXES):
        return True
    return _is_plural(word)


def _is_plural(word: str) -> bool:
    return word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3


def search_phrase_check(phrase: str, nouns: Optional[set[str]] = None) -> str:
    """Return "" when the phrase is noun-phrase shaped, else a rejection reason."""
    words = _phrase_words(phrase)
    if not 2 <= len(words) <= 4:
        return "word_count"
    if any(ch.isdigit() for word in words for ch in word):
        return "number"
    if is_closing_section(phrase):
        return "closing_section"
    if _is_idiom(words):
        return "idiom"
    if _is_function_word(words[0]):
        return "leading_function_word"
    if words[0].endswith(_ADVERB_SUFFIXES):
        return "leading_adverb"
    if words[0].endswith("ing") and words[0] not in _ING_NOUNS:
        return "leading_verb_form"
    if words[0] in _EDITORIAL_ADJECTIVES:
        return "subjective_modifier"
    if _is_function_word(words[-1]) or words[-1] in _GENERIC_ADJECTIVES:
        return "trailing_function_word"
    if words[-1] in {"mens", "womens"}:
        return "trailing_modifier"
    if _stem(words[-1]) in _VAGUE_HEADS or words[-1] in _VAGUE_HEADS:
        return "vague_head"
    if any(_is_function_word(word) and word not in _INTERNAL_OK for word in words[1:-1]):
        return "internal_function_word"
    if not _plausible_noun(words[-1], nouns or set()):
        return "not_noun_phrase"
    if _stem(words[-1]) in _FIGURATIVE_NOUNS or any(
        right == "of" and _stem(left) in _FIGURATIVE_OF_HEADS
        for left, right in zip(words, words[1:])
    ):
        return "figurative_phrase"
    for left, right in zip(words, words[1:]):
        if (
            _is_plural(left)
            and left not in _PLURAL_MODIFIERS
            and right not in _INTERNAL_OK
            and not _is_plural(right)
        ):
            return "subject_verb_shape"
    if _stem(words[-1]) in _GENERIC_HEADS and all(
        word in _GENERIC_ADJECTIVES or word in _QUANTIFIERS for word in words[:-1]
    ):
        return "generic_head"
    return ""


def is_search_phrase(phrase: str, nouns: Optional[set[str]] = None) -> bool:
    return not search_phrase_check(phrase, nouns)


def _intent(phrase: str, url: str = "") -> str:
    blob = f"{phrase} {url}".lower()
    if _QUESTION.match(phrase or "") or "?" in (phrase or ""):
        return "informational"
    if re.search(r"\b(buy|price|cost|shop|cart|checkout|order)\b", blob) or re.search(
        r"/(collections?|products?|category|dp/)", url or "", re.I
    ):
        return "transactional"
    if re.search(r"\b(best|vs|review|compare|top)\b", blob):
        return "commercial"
    return "informational"


def classify_page_intent(row: dict[str, Any]) -> str:
    url = str(row.get("url") or "")
    title = str(row.get("title") or "")
    snippet = str(row.get("snippet") or row.get("meta_description") or "")
    blob = f"{title} {url} {snippet}".lower()
    trans = bool(_BOILERPLATE.search(blob) or re.search(r"/(collections?|products?|category|dp/)", url, re.I))
    info = bool(re.search(r"\b(how to|guide|ideas|style|outfit|tips|what to wear)\b", blob))
    commercial = bool(re.search(r"\b(best|review|vs|compare)\b", blob))
    if trans and info:
        return "mixed"
    if trans:
        return "transactional"
    if commercial:
        return "commercial"
    if info:
        return "informational"
    if re.search(r"amazon\.|flipkart\.|/shop", url, re.I):
        return "transactional"
    return "informational"


def article_intent(keyword: str, page: Optional[dict[str, Any]]) -> str:
    title = (page or {}).get("title") or ""
    return _intent(f"{keyword} {title}", (page or {}).get("url") or "")


def fold_tokens(text: str) -> list[str]:
    return [_stem(token) for token in re.findall(r"[a-z0-9]+", _clean(text)) if len(token) > 1]


def fold_phrase(text: str) -> str:
    return " ".join(fold_tokens(text))


def match_status(
    phrase: str,
    haystack: str,
    *,
    title: str = "",
    headings: Optional[list[str]] = None,
) -> dict[str, Any]:
    folded = fold_phrase(phrase)
    if not folded:
        return {"status": "missing", "matched_text": "", "match_reason": "empty phrase"}
    fields = [item for item in [title, *(headings or [])] if item]
    for field in fields:
        if fold_phrase(field) == folded:
            return {
                "status": "exact",
                "matched_text": field.strip(),
                "match_reason": "exact phrase match after punctuation and plural normalization",
            }
    for sentence in re.split(r"[.!?|]", haystack or ""):
        if fold_phrase(sentence) == folded:
            return {
                "status": "exact",
                "matched_text": sentence.strip()[:120],
                "match_reason": "exact phrase match after punctuation and plural normalization",
            }
    pset = set(content_tokens(phrase))
    hset = set(content_tokens(" ".join(fields + [haystack or ""])))
    coverage = (len(pset & hset) / len(pset)) if pset else 0.0
    contiguous = f" {folded} " in f" {fold_phrase(haystack)} "
    if coverage >= 0.8 and len(pset & hset) >= min(3, len(pset)):
        matched = title or next((item for item in fields if len(set(content_tokens(item)) & pset) >= min(3, len(pset))), "")
        return {
            "status": "close_variant",
            "matched_text": matched[:120],
            "match_reason": "same entities and intent with natural word-order variation",
        }
    if contiguous or (coverage >= 0.66 and len(pset) <= 4 and len(pset & hset) >= 2):
        return {
            "status": "close_variant",
            "matched_text": (title or phrase)[:120],
            "match_reason": "same entities and intent with natural word-order variation",
        }
    return {"status": "missing", "matched_text": "", "match_reason": "not found in article text"}


def relevance_score(phrase: str, keyword: str) -> float:
    pset, kset = set(content_tokens(phrase)), set(content_tokens(keyword))
    if not pset or not kset:
        return 0.0
    jaccard = len(pset & kset) / len(pset | kset)
    coverage = len(pset & kset) / len(kset)
    return round(min(1.0, (jaccard * 0.55) + (coverage * 0.45)), 3)


def _garment_conflict(phrase: str, keyword: str) -> bool:
    kw_g = _GARMENTS & set(content_tokens(keyword))
    ph_g = _GARMENTS & set(content_tokens(phrase))
    return bool(kw_g and ph_g and not (kw_g & ph_g))


def _looks_like_title(phrase: str) -> bool:
    words = (phrase or "").split()
    if "|" in phrase or " – " in phrase or " — " in phrase:
        return True
    if len(words) > _MAX_KEYWORD_WORDS or len(phrase) > _MAX_KEYWORD_CHARS:
        return True
    if phrase[:1].isupper() and sum(1 for w in words if w[:1].isupper()) >= max(4, len(words) - 1) and len(words) >= 6:
        return True
    return False


def _is_brand_phrase(phrase: str, domains: Optional[list[str]] = None) -> bool:
    if _BRANDISH.search(phrase or ""):
        return True
    lowered = (phrase or "").lower()
    for domain in domains or []:
        host = (domain or "").split(".")[0].lower()
        if host and len(host) >= 4 and host in lowered:
            return True
    return False


def validate_keyword(
    phrase: str,
    keyword: str,
    *,
    source: str = "body",
    page_title: str = "",
    article_intent_label: str = "informational",
    domains: Optional[list[str]] = None,
    page_relevance: float = 0.0,
    debug: bool = False,
) -> dict[str, Any]:
    raw = " ".join((phrase or "").split())
    words = raw.split()
    word_count = len(words)
    phrase_rel = relevance_score(raw, keyword)
    effective_rel = max(phrase_rel, page_relevance if source in {"heading", "meta"} else 0.0)
    flags = {
        "phrase_length": len(raw),
        "word_count": word_count,
        "appears_in_heading": source == "heading",
        "appears_in_body": source in {"body", "opening", "meta", "heading"},
        "appears_in_meta": source == "meta",
        "is_brand_phrase": _is_brand_phrase(raw, domains),
        "is_navigation_phrase": bool(_NAV.search(raw)) or is_closing_section(raw),
        "is_page_title_only": bool(page_title and raw.lower() == page_title.lower()),
        "intent": _intent(raw),
        "relevance_to_target_topic": effective_rel,
        "semantic_similarity": phrase_rel,
        "accepted": False,
        "rejection_reason": "",
    }
    if word_count < 2 or word_count > _MAX_KEYWORD_WORDS:
        flags["rejection_reason"] = "word_count"
        return flags
    if flags["is_page_title_only"] or source == "title":
        flags["rejection_reason"] = "page_title_only"
        return flags
    if _looks_like_title(raw):
        flags["rejection_reason"] = "title_or_sentence"
        return flags
    if flags["is_brand_phrase"]:
        flags["rejection_reason"] = "brand_or_domain"
        return flags
    if flags["is_navigation_phrase"]:
        flags["rejection_reason"] = "navigation"
        return flags
    if _BOILERPLATE.search(raw) and article_intent_label != "transactional":
        flags["rejection_reason"] = "product_boilerplate"
        return flags
    if _garment_conflict(raw, keyword):
        flags["rejection_reason"] = "different_product_entity"
        return flags
    if effective_rel < 0.18 and source != "target":
        flags["rejection_reason"] = "low_topic_relevance"
        return flags
    if flags["intent"] == "transactional" and article_intent_label == "informational":
        flags["rejection_reason"] = "intent_mismatch"
        return flags
    flags["accepted"] = True
    if not debug:
        flags.pop("debug", None)
    return flags


def _classify(phrase: str, keyword: str) -> str:
    if _QUESTION.match(phrase) or phrase.endswith("?"):
        return "question"
    words = phrase.split()
    kw = normalize_phrase(keyword)
    if kw and (normalize_phrase(phrase) == kw or kw in normalize_phrase(phrase)):
        return "primary"
    if _intent(phrase) == "transactional":
        return "commercial_modifier"
    if len(words) >= 4:
        return "long-tail"
    if len(words) == 1:
        return "entity"
    return "secondary"


def extract_terms(
    text: str,
    headings: list[str],
    keyword: str,
    limit: int = 40,
    *,
    meta: str = "",
    page_title: str = "",
    article_intent_label: str = "informational",
    domains: Optional[list[str]] = None,
    page_relevance: float = 0.0,
    debug: bool = False,
) -> list[dict[str, Any]]:
    head_blob = " ".join(headings or []).lower()
    meta_l = (meta or "").lower()
    nouns = domain_nouns(page_title, keyword, *(headings or []))
    grams: Counter[str] = Counter()

    def collect(blob: str, weight: int) -> None:
        allowed = noun_chunk_phrases(blob)
        for words in phrase_segments(blob):
            if len(words) <= 4 and any(_YEAR.match(word) for word in words):
                continue
            for size in (2, 3, 4):
                for index in range(len(words) - size + 1):
                    phrase = " ".join(words[index:index + size])
                    if allowed is not None and phrase not in allowed:
                        continue
                    if is_search_phrase(phrase, nouns):
                        grams[phrase] += weight

    collect(text or "", 1)
    collect(meta or "", 1)
    for heading in headings or []:
        collect(heading, 3)
        words = _phrase_words(heading)
        clean = " ".join(words)
        if 2 < len(words) <= _MAX_KEYWORD_WORDS and _QUESTION.match(clean):
            grams[clean] += 3
    kw = " ".join(_tokens(keyword or ""))
    if kw:
        grams[kw] += 6

    merged: dict[str, tuple[str, int]] = {}
    for phrase, freq in grams.items():
        key = phrase_key(phrase)
        current = merged.get(key)
        if current is None:
            merged[key] = (phrase, freq)
            continue
        best = phrase if freq > current[1] else current[0]
        merged[key] = (best, current[1] + freq)
    ranked = sorted(merged.values(), key=lambda item: -item[1])

    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for phrase, freq in ranked[:160]:
        source = "body"
        if phrase in head_blob:
            source = "heading"
        elif phrase in meta_l:
            source = "meta"
        elif phrase in (text or "")[:400].lower():
            source = "opening"
        flags = validate_keyword(
            phrase,
            keyword,
            source=source,
            page_title=page_title,
            article_intent_label=article_intent_label,
            domains=domains,
            page_relevance=page_relevance,
            debug=debug,
        )
        flags["frequency"] = freq
        if not flags["accepted"]:
            if freq >= 2:
                rejected.append({"keyword": phrase, **flags})
            continue
        if freq < 2 and phrase != kw and source != "heading":
            continue
        rows.append({
            "keyword": phrase,
            "type": _classify(phrase, keyword),
            "frequency": freq,
            "prominence": "high" if source in {"heading", "opening", "target"} else "medium",
            "placement": source,
            "search_intent": flags["intent"],
            "search_volume": UNAVAILABLE,
            "keyword_difficulty": UNAVAILABLE,
            "page_title_signal": False,
            "relevance_score": flags["semantic_similarity"],
        })
        if len(rows) >= limit:
            break
    return rows


def compare_keywords(
    keyword: str,
    yours: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
    *,
    serp_phrases: Optional[list[str]] = None,
    debug: bool = False,
) -> dict[str, Any]:
    article_intent_label = article_intent(keyword, yours)
    your_heads = list((yours or {}).get("h2_headings") or []) + list((yours or {}).get("h1_headings") or [])
    if (yours or {}).get("h2"):
        your_heads.extend(yours.get("h2") or [])
    your_h1 = (yours or {}).get("h1") or ""
    if your_h1:
        your_heads.append(your_h1)
    your_body = (yours or {}).get("full_text") or (yours or {}).get("text") or ""
    your_meta = (yours or {}).get("meta_description") or ""
    your_title = (yours or {}).get("title") or ""
    your_haystack = " ".join([your_title, your_h1, " ".join(your_heads), your_body, your_meta])
    domains = [row.get("domain") or "" for row in competitors]
    your_rel = max(relevance_score(your_title, keyword), relevance_score(your_h1, keyword), 0.35)

    def _heads_without_title(row: dict[str, Any]) -> list[str]:
        title = str(row.get("title") or "").strip().lower()
        values = list(row.get("h2_headings") or []) + list(row.get("h1_headings") or [])
        extra = row.get("h2") or []
        if isinstance(extra, list):
            values.extend(extra)
        h1 = row.get("h1") or ""
        if h1:
            values.append(h1)
        return [item for item in values if item and str(item).strip().lower() != title]

    catalog: dict[str, dict[str, Any]] = {}
    for term in extract_terms(
        your_body,
        _heads_without_title(yours or {}),
        keyword,
        limit=24,
        meta=your_meta,
        page_title=your_title,
        article_intent_label=article_intent_label,
        domains=domains,
        page_relevance=your_rel,
        debug=debug,
    ):
        catalog[phrase_key(term["keyword"])] = term

    editorial = [
        row for row in competitors
        if classify_page_intent(row) not in {"transactional", "navigational"}
    ]
    for row in editorial:
        heads = _heads_without_title(row)
        page_blob = " ".join([
            row.get("title") or "",
            row.get("snippet") or "",
            " ".join(heads[:8]),
            (row.get("full_text") or row.get("text") or "")[:400],
        ])
        page_rel = relevance_score(page_blob, keyword)
        for term in extract_terms(
            row.get("full_text") or row.get("text") or row.get("snippet") or "",
            heads,
            keyword,
            limit=16,
            meta=row.get("meta_description") or "",
            page_title=row.get("title") or "",
            article_intent_label=article_intent_label,
            domains=domains,
            page_relevance=page_rel,
            debug=debug,
        ):
            catalog.setdefault(phrase_key(term["keyword"]), term)

    serp_nouns = domain_nouns(your_title, keyword, *your_heads)
    for phrase in serp_phrases or []:
        phrase = " ".join(_phrase_words(phrase))
        if not is_search_phrase(phrase, serp_nouns):
            continue
        flags = validate_keyword(
            phrase,
            keyword,
            source="serp",
            article_intent_label=article_intent_label,
            domains=domains,
        )
        if not flags["accepted"]:
            continue
        catalog.setdefault(phrase_key(phrase), {
            "keyword": phrase,
            "type": _classify(phrase, keyword),
            "frequency": 1,
            "prominence": "medium",
            "placement": "serp",
            "search_intent": flags["intent"],
            "search_volume": UNAVAILABLE,
            "keyword_difficulty": UNAVAILABLE,
            "page_title_signal": False,
            "relevance_score": flags["semantic_similarity"],
        })

    if keyword:
        catalog[phrase_key(keyword)] = {
            "keyword": keyword.strip(),
            "type": "primary",
            "frequency": 6,
            "prominence": "high",
            "placement": "target",
            "search_intent": _intent(keyword),
            "search_volume": UNAVAILABLE,
            "keyword_difficulty": UNAVAILABLE,
            "page_title_signal": False,
            "relevance_score": 1.0,
        }

    table = []
    gaps = []
    for meta in catalog.values():
        phrase = meta["keyword"]
        match = match_status(
            phrase,
            your_haystack,
            title=your_title,
            headings=your_heads,
        )
        in_comp = False
        competitor_count = 0
        for row in competitors:
            if classify_page_intent(row) in {"transactional", "navigational"}:
                continue
            blob = " ".join([
                " ".join(_heads_without_title(row)),
                row.get("full_text") or row.get("text") or row.get("snippet") or "",
                row.get("meta_description") or "",
            ])
            status = match_status(phrase, blob, headings=_heads_without_title(row))["status"]
            if status in {"exact", "close_variant"}:
                in_comp = True
                competitor_count += 1
        title_only = False
        for row in competitors:
            title = row.get("title") or ""
            if title and normalize_phrase(phrase) == normalize_phrase(title):
                title_only = True
        if title_only and meta.get("placement") != "heading":
            continue
        status = match["status"]
        relevance = meta.get("relevance_score") or 0
        widely_used = competitor_count >= min(2, max(1, len(editorial)))
        if in_comp and status == "missing" and (widely_used or relevance >= GAP_HIGH_RELEVANCE):
            opportunity = "high"
            recommendation = "Cover this subtopic in a natural H2; do not force exact-match stuffing."
            priority = "high-priority"
        elif in_comp and status == "missing" and relevance >= GAP_MIN_RELEVANCE:
            opportunity = "medium"
            recommendation = "Cover briefly if it fits your angle; only some competitors use it."
            priority = "medium-priority"
        elif in_comp and status == "missing":
            opportunity = "low"
            recommendation = "Low overlap with your target keyword; skip unless it fits your angle."
            priority = "low-priority"
        elif in_comp and status == "close_variant":
            opportunity = "low"
            recommendation = "Keep the natural variant already used; no exact-match stuffing."
            priority = "low-priority"
        elif status == "exact" and not in_comp:
            opportunity = "differentiate"
            recommendation = "Keep this unique angle; make the answer more citation-ready."
            priority = "long-term"
        else:
            opportunity = "monitor"
            recommendation = "Maintain natural coverage; avoid extra exact-match repeats."
            priority = "low-priority"
        row = {
            **meta,
            "found_in_my_blog": status != "missing",
            "found_in_competitor": in_comp,
            "my_blog_status": status,
            "matched_text": match.get("matched_text") or "",
            "match_reason": match.get("match_reason") or "",
            "competitor_count": competitor_count,
            "intent": meta.get("search_intent") or _intent(phrase),
            "opportunity": opportunity,
            "reason": match.get("match_reason") or recommendation,
            "recommended_action": recommendation,
            "recommendation": recommendation,
            "priority_group": priority,
            "suggested_heading": "" if status != "missing" else phrase.capitalize(),
            "search_intent": meta.get("search_intent") or _intent(phrase),
        }
        table.append(row)
        if status == "missing" and in_comp:
            gaps.append(row)

    table.sort(key=lambda item: ({"missing": 0, "close_variant": 1, "exact": 2}.get(item["my_blog_status"], 3), -item.get("relevance_score") or 0))
    high = [g for g in gaps if g["priority_group"] == "high-priority"][:8]
    return {
        "table": table[:40],
        "gaps": {
            "high-priority": high,
            "medium-priority": [g for g in gaps if g["priority_group"] == "medium-priority"][:8],
            "low-priority": [g for g in gaps if g["priority_group"] == "low-priority"][:6],
            "quick-win": high[:4],
            "long-term": [g for g in table if g["priority_group"] == "long-term"][:6],
        },
        "article_intent": article_intent_label,
        "disclaimer": "Search volume and keyword difficulty are Data unavailable unless a third-party API is configured. Close variants count as present; do not stuff exact match.",
        "debug_rejections": [] if not debug else [],
    }


def keyword_focus(
    keyword: str,
    table: list[dict[str, Any]],
    gsc: Optional[dict[str, Any]] = None,
    *,
    competitor_total: int = 0,
    country: str = "us",
    per_group: int = 3,
    per_close: Optional[int] = None,
    per_new: Optional[int] = None,
    metrics: MetricProvider = DEFAULT_METRICS,
) -> dict[str, Any]:
    """Pick at most `per_group` keywords for our blog, competitors, close-to-ranking, and new topics.

    Performance for our blog comes from Search Console when connected; otherwise
    from on-page usage. Volume is only shown when a metric provider returns it.
    Close-to-ranking and new topics are capped separately so GSC striking-distance
    queries cannot crowd out content-gap phrases.
    """
    target_key = phrase_key(keyword) if keyword else ""
    used: set[str] = set()
    gsc = gsc or {}
    queries = [
        row for row in (gsc.get("queries") or [])
        if gsc.get("status") == "ok" and row.get("query") and not row.get("branded")
    ]
    has_gsc = bool(queries)
    close_limit = per_group if per_close is None else per_close
    new_limit = per_group if per_new is None else per_new

    def volume_of(phrase: str) -> Any:
        try:
            value = metrics.keyword_volume(phrase, country)
        except Exception:
            value = None
        return UNAVAILABLE if value is None else value

    def take(candidates: list[dict[str, Any]], limit: Optional[int] = None) -> list[dict[str, Any]]:
        cap = per_group if limit is None else limit
        picked = []
        for item in candidates:
            key = phrase_key(item["keyword"])
            if not key or key in used:
                continue
            used.add(key)
            picked.append({**item, "search_volume": volume_of(item["keyword"])})
            if len(picked) >= cap:
                break
        return picked

    def is_primary_variant(phrase: str) -> bool:
        if not phrase:
            return True
        if target_key and phrase_key(phrase) == target_key:
            return True
        return bool(keyword) and relevance_score(phrase, keyword) >= 0.85

    def sort_by_volume(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        known = {item["keyword"]: volume_of(item["keyword"]) for item in items}
        items.sort(key=lambda item: (
            not isinstance(known[item["keyword"]], int),
            -(known[item["keyword"]] if isinstance(known[item["keyword"]], int) else 0),
            item.get("_rank", (99,)),
        ))
        return items

    def without_rank(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key != "_rank"}

    def gsc_evidence(row: dict[str, Any]) -> str:
        return (
            f"{int(row.get('clicks') or 0)} clicks · {int(row.get('impressions') or 0)} impressions"
            f" · avg position {float(row.get('position') or 0):.1f}"
        )

    if has_gsc:
        page_one = [r for r in queries if 0 < (r.get("position") or 0) <= 10]
        ranked = sorted(page_one, key=lambda r: (-(r.get("clicks") or 0), -(r.get("impressions") or 0)))
        ours = take([
            {"keyword": r["query"], "evidence": gsc_evidence(r), "source": "search_console"}
            for r in ranked
        ])
    else:
        on_page = [
            row for row in table
            if row.get("my_blog_status") == "exact"
        ]
        on_page.sort(key=lambda r: (
            r.get("type") != "primary",
            r.get("prominence") != "high",
            -(r.get("frequency") or 0),
            -(r.get("relevance_score") or 0),
        ))
        ours = take([
            {
                "keyword": r["keyword"],
                "evidence": f"Used {int(r.get('frequency') or 0)}× on your page"
                + (f" · in {r['placement']}" if r.get("placement") in {"heading", "opening", "meta"} else ""),
                "source": "on_page",
            }
            for r in on_page
        ])

    comp_rows = [
        row for row in table
        if row.get("found_in_competitor") and phrase_key(row.get("keyword") or "") != target_key
    ]
    comp_rows.sort(key=lambda r: (
        -(r.get("competitor_count") or 0),
        -(r.get("frequency") or 0),
        -(r.get("relevance_score") or 0),
    ))
    total = max(competitor_total, max((r.get("competitor_count") or 0 for r in comp_rows), default=0))
    competitors = take([
        {
            "keyword": r["keyword"],
            "evidence": f"Used by {int(r.get('competitor_count') or 0)} of {total} competitors"
            + ("" if r.get("found_in_my_blog") else " · missing from your page"),
            "source": "competitors",
        }
        for r in comp_rows
    ])

    close_candidates: list[dict[str, Any]] = []
    if has_gsc:
        striking = [
            row for row in queries
            if (row.get("position") or 0) > 10
            and (row.get("impressions") or 0) > 0
            and not is_primary_variant(str(row.get("query") or ""))
        ]
        striking.sort(key=lambda row: -(row.get("impressions") or 0))
        close_candidates.extend(
            {
                "keyword": row["query"],
                "evidence": f"{int(row.get('impressions') or 0)} impressions but avg position "
                f"{float(row.get('position') or 0):.1f}; you already get search demand for it",
                "source": "search_console",
                "_rank": (0, -(row.get("impressions") or 0)),
            }
            for row in striking
        )
    close_to_ranking = take(
        [without_rank(item) for item in sort_by_volume(close_candidates)],
        close_limit,
    )

    gap_rows = [
        row for row in table
        if row.get("my_blog_status") == "missing"
        and phrase_key(row.get("keyword") or "") != target_key
        and (row.get("relevance_score") or 0) >= 0.35
    ]
    gap_candidates = [
        {
            "keyword": row["keyword"],
            "evidence": "Relevant to your target keyword and missing from your page"
            + (f" · used by {int(row.get('competitor_count') or 0)} competitors" if row.get("competitor_count") else ""),
            "source": "gap",
            "_rank": (1, -(row.get("competitor_count") or 0), -(row.get("relevance_score") or 0)),
        }
        for row in gap_rows
    ]
    new_topics = take(
        [without_rank(item) for item in sort_by_volume(gap_candidates)],
        new_limit,
    )

    opportunities = close_to_ranking + new_topics
    close_volume = any(isinstance(item["search_volume"], int) for item in close_to_ranking)
    new_volume = any(isinstance(item["search_volume"], int) for item in new_topics)
    volume_known = close_volume or new_volume
    close_note = (
        "Queries you already get impressions for but rank below position 10 — not new topics."
        + ("" if close_volume else " Search volume: Data unavailable (no volume API configured).")
        if has_gsc else
        "Connect Search Console to see queries you already rank for weakly."
    )
    new_note = (
        "Topics competitors cover that your page does not use."
        + (
            "" if new_volume else
            " Search volume: Data unavailable (no volume API configured). Ranked by relevance "
            "to your target keyword and competitor use."
        )
    )
    return {
        "our_blog": ours,
        "our_blog_basis": "search_console" if has_gsc else "on_page",
        "competitors": competitors,
        "close_to_ranking": close_to_ranking,
        "close_to_ranking_basis": "volume" if close_volume else ("search_console" if has_gsc else "none"),
        "close_to_ranking_note": close_note,
        "new_topics": new_topics,
        "new_topics_basis": "volume" if new_volume else "relevance",
        "new_topics_note": new_note,
        "opportunities": opportunities,
        "opportunities_basis": "volume" if volume_known else ("search_console" if has_gsc else "relevance"),
        "note": (
            "" if volume_known else
            "Search volume: Data unavailable (no volume API configured). Close-to-ranking uses Search Console "
            "impressions when connected; new topics use relevance and competitor use."
        ),
    }
