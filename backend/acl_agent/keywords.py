"""Keyword extraction and gap analysis from live page text."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from acl_agent.metrics import UNAVAILABLE

_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "your", "our",
    "are", "was", "were", "have", "has", "had", "not", "but", "you",
    "all", "can", "will", "just", "about", "into", "more", "than",
    "also", "when", "what", "which", "their", "them", "they", "then",
    "some", "been", "each", "very", "here", "there", "over", "after",
    "before", "other", "only", "most", "such", "like", "best", "how",
    "to", "a", "an", "of", "in", "on", "at", "or", "by", "it", "is",
}

_LIGHT_STOP = {"the", "and", "for", "with", "from", "how", "to", "a", "an", "of", "in", "on", "best"}

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
    r"related searches|skip to|add to cart|shop now)\b",
    re.I,
)
_BRANDISH = re.compile(
    r"\b(amazon|bewakoof|crazymonk|flipkart|myntra|ajio|nike|adidas|"
    r"zara|h&m|uniqlo|walmart|ebay|etsy|shopify)\b",
    re.I,
)
_GARMENTS = {
    "hoodie", "hoodies", "shirt", "shirts", "tshirt", "tshirts", "tee", "tees",
    "jacket", "jackets", "jean", "jeans", "pant", "pants", "dress", "dresses",
    "sweater", "sweatshirt", "coat", "coats",
}
_MAX_KEYWORD_WORDS = 7
_MAX_KEYWORD_CHARS = 60


def _tokens(text: str) -> list[str]:
    cleaned = (text or "").lower().replace("'", "").replace("’", "")
    return re.findall(r"[a-z0-9]{3,}", cleaned)


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
    cleaned = (text or "").lower().replace("'", "").replace("’", "")
    return [_stem(token) for token in re.findall(r"[a-z0-9]+", cleaned) if len(token) > 1]


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
        "is_navigation_phrase": bool(_NAV.search(raw)),
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
    body = (text or "").lower()
    meta_l = (meta or "").lower()
    words = [w for w in _tokens(body + " " + head_blob + " " + meta_l) if w not in _STOP]
    grams: Counter[str] = Counter()
    for size in (2, 3, 4):
        for index in range(len(words) - size + 1):
            phrase = " ".join(words[index:index + size])
            if any(part in _LIGHT_STOP for part in phrase.split()[:1]):
                continue
            grams[phrase] += 1
    for heading in headings or []:
        clean = " ".join(_tokens(heading))
        if 1 < len(clean.split()) <= _MAX_KEYWORD_WORDS:
            grams[clean] += 3
    kw = " ".join(_tokens(keyword or ""))
    if kw:
        grams[kw] += 6

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    rejected: list[dict[str, Any]] = []
    for phrase, freq in grams.most_common(160):
        if phrase in seen:
            continue
        seen.add(phrase)
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
        catalog[term["keyword"]] = term

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
            catalog.setdefault(term["keyword"], term)

    if keyword:
        catalog[keyword.lower().strip()] = {
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
    for phrase, meta in catalog.items():
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
        if in_comp and status == "missing":
            opportunity = "high" if meta.get("relevance_score", 0) >= 0.35 else "medium"
            recommendation = "Cover this subtopic in a natural H2; do not force exact-match stuffing."
            priority = "high-priority"
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
