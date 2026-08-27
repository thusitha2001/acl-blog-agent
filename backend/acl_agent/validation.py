"""
ACL Blog Agent - deterministic, code-based validation.

No model calls here - word counts, heading structure, keyword
presence, internal-link verification, originality check, and
humanization quality heuristics.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

from acl_agent.config import (
    HUMANIZATION_MAX_CONTRACTION_DENSITY,
    HUMANIZATION_MAX_FILLER_COUNT,
    HUMANIZATION_MAX_REPEAT_STARTER_PCT,
    HUMANIZATION_MIN_CONTRACTION_DENSITY,
    HUMANIZATION_MIN_SENTENCE_VARIANCE,
    PLAGIARISM_OVERLAP_THRESHOLD,
    WORD_COUNT_TOLERANCE,
)
from acl_agent.models import ContentBrief, InternalLink


def word_count_band(target_word_count: int) -> tuple[int, int]:
    """
    The acceptable [min, max] word range for a given target, based on
    WORD_COUNT_TOLERANCE. Both bounds are hard requirements - an
    article outside this band fails validation, whether it's short
    or long.
    """
    spread = int(round(target_word_count * WORD_COUNT_TOLERANCE))
    return target_word_count - spread, target_word_count + spread

def count_h1(text: str) -> int:
    return len(
        re.findall(
            r"^#\s+.+$",
            text,
            flags=re.MULTILINE,
        )
    )


def word_count(text: str) -> int:
    return len(
        re.findall(
            r"\S+",
            text,
        )
    )


def keyword_count(
    text: str,
    keyword: str,
) -> int:
    return len(
        re.findall(
            re.escape(keyword),
            text,
            flags=re.IGNORECASE,
        )
    )


def validate_internal_links(
    links: list[InternalLink],
    website: str,
) -> list[str]:
    errors = []

    for link in links:
        if not link.url.startswith(website):
            errors.append(
                f"Unverified external internal link: {link.url}"
            )

    return errors


def _normalize_for_shingles(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return words


def check_originality(
    article: str,
    reference_text: str,
    ngram_size: int = 8,
    threshold: float = PLAGIARISM_OVERLAP_THRESHOLD,
) -> Optional[str]:
    """
    Heuristic plagiarism/originality check: builds overlapping word
    n-grams ("shingles") from both the article and the reference
    material (the style/fact chunks retrieved from the knowledge
    base), then measures what fraction of the article's shingles
    also appear in the reference text verbatim.

    This is a lightweight local check, not a substitute for a real
    plagiarism-detection service - it only catches close copying
    from your OWN indexed source blogs, not the wider web. Returns
    a warning string if the overlap ratio exceeds the threshold,
    otherwise None.
    """
    if not reference_text or not reference_text.strip():
        return None

    article_words = _normalize_for_shingles(article)
    reference_words = _normalize_for_shingles(reference_text)

    if len(article_words) < ngram_size or len(reference_words) < ngram_size:
        return None

    reference_shingles = {
        tuple(reference_words[i:i + ngram_size])
        for i in range(len(reference_words) - ngram_size + 1)
    }

    article_shingles = [
        tuple(article_words[i:i + ngram_size])
        for i in range(len(article_words) - ngram_size + 1)
    ]

    if not article_shingles:
        return None

    overlap_count = sum(
        1 for shingle in article_shingles if shingle in reference_shingles
    )

    overlap_ratio = overlap_count / len(article_shingles)

    if overlap_ratio > threshold:
        return (
            f"Possible close paraphrasing detected: {overlap_ratio:.0%} "
            f"of {ngram_size}-word phrases match reference source "
            "material verbatim (threshold is "
            f"{threshold:.0%})."
        )

    return None


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if len(s.strip()) > 3]


AI_FILLER_PHRASES = [
    "in today's world",
    "when it comes to",
    "it's important to note",
    "it's worth mentioning",
    "in this article",
    "let's dive in",
    "let's explore",
    "without further ado",
    "sit back and relax",
    "what are you waiting for",
    "look no further",
    "delve into",
    "it goes without saying",
    "moreover",
    "furthermore",
    "in conclusion",
    "overall",
    "it is important to note",
    "whether you're",
    "in this guide",
    "we'll cover",
    "we'll explore",
    "we'll discuss",
    "shed light",
    "at the end of the day",
    "in a nutshell",
    "rest assured",
    "dive deep",
    "tap into",
    "game-changer",
    "this comprehensive guide",
    "the world of",
    "the realm of",
]

AI_FILLER_PATTERNS = [
    r"not only.{0,20}but also",
]


def humanization_checks(text: str) -> dict[str, Any]:
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    sentences = _split_sentences(text)
    word_lists = [s.split() for s in sentences]
    sentence_lengths = [len(wl) for wl in word_lists]

    if sentence_lengths:
        avg_sl = sum(sentence_lengths) / len(sentence_lengths)
        variance = sum(
            (sl - avg_sl) ** 2 for sl in sentence_lengths
        ) / len(sentence_lengths)
        std_dev = variance ** 0.5
        metrics["avg_sentence_length"] = round(avg_sl, 1)
        metrics["sentence_length_stddev"] = round(std_dev, 1)
        if avg_sl > 0 and std_dev / avg_sl < HUMANIZATION_MIN_SENTENCE_VARIANCE:
            warnings.append(
                f"Sentence length variance is low ({std_dev:.1f} "
                f"std dev / {avg_sl:.1f} avg = {std_dev/avg_sl:.2f} "
                f"CV, threshold {HUMANIZATION_MIN_SENTENCE_VARIANCE}). "
                "Sentences may feel monotone."
            )

    all_words = re.findall(r"[a-zA-Z']+", text.lower())
    total_words = len(all_words) or 1

    contractions = sum(
        1 for w in all_words
        if "'" in w and len(w) > 1
        and w not in ("'s", "'t", "'re", "'ve", "'ll", "'d")
    )
    contraction_density = contractions / total_words
    metrics["contraction_density"] = round(contraction_density, 4)
    if contraction_density < HUMANIZATION_MIN_CONTRACTION_DENSITY:
        warnings.append(
            f"Contractions are sparse ({contraction_density:.1%}). "
            "The text may read too formal or robotic."
        )
    elif contraction_density > HUMANIZATION_MAX_CONTRACTION_DENSITY:
        warnings.append(
            f"Contractions are excessive ({contraction_density:.1%}). "
            "May feel forced or unnatural."
        )

    filler_count = sum(
        1 for phrase in AI_FILLER_PHRASES
        if phrase in text.lower()
    )
    filler_count += sum(
        1 for pat in AI_FILLER_PATTERNS
        if re.search(pat, text.lower())
    )
    metrics["filler_phrase_count"] = filler_count
    if filler_count > HUMANIZATION_MAX_FILLER_COUNT:
        warnings.append(
            f"AI-ism filler phrases detected ({filler_count}): "
            "may hurt perceived humanization."
        )

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    para_lengths = [len(p.split()) for p in paragraphs]
    if len(para_lengths) >= 3:
        avg_pl = sum(para_lengths) / len(para_lengths)
        pl_var = sum(
            (pl - avg_pl) ** 2 for pl in para_lengths
        ) / len(para_lengths)
        metrics["avg_paragraph_length"] = round(avg_pl, 1)
        if avg_pl > 0 and (pl_var ** 0.5) / avg_pl < 0.20:
            warnings.append(
                "Paragraph lengths are very uniform. Mix short and "
                "longer paragraphs for a more natural feel."
            )

    if sentences and len(sentences) >= 5:
        starters = []
        for s in sentences:
            first_word = re.match(r"[A-Za-z]+", s.strip())
            if first_word:
                starters.append(first_word.group().lower())
        starter_counts = Counter(starters)
        most_common = starter_counts.most_common(1)[0] if starter_counts else ("", 0)
        repeat_pct = most_common[1] / len(sentences) if most_common[1] else 0
        metrics["top_sentence_starter"] = most_common[0]
        metrics["top_starter_pct"] = round(repeat_pct, 3)
        if repeat_pct > HUMANIZATION_MAX_REPEAT_STARTER_PCT:
            warnings.append(
                f"Sentence starter '{most_common[0]}' used in "
                f"{repeat_pct:.0%} of sentences (threshold "
                f"{HUMANIZATION_MAX_REPEAT_STARTER_PCT:.0%}). "
                "Vary openings for natural rhythm."
            )

    personal_observation_patterns = [
        r"most people don't realize",
        r"here'?s? the thing",
        r"the honest answer",
        r"here'?s? what most",
        r"the catch is",
        r"it depends",
        r"no single right answer",
    ]
    has_depth_signal = any(
        re.search(p, text.lower()) for p in personal_observation_patterns
    )
    metrics["has_depth_signal"] = has_depth_signal
    if not has_depth_signal:
        warnings.append(
            "No depth signals found (uncertainty acknowledgment, "
            "trade-off mention, or personal observation). Add at "
            "least one to feel more human."
        )

    dash_count = text.count(" - ") + text.count("\u2014")
    metrics["em_dash_count"] = dash_count
    if dash_count == 0:
        warnings.append(
            "No em dashes or parenthetical asides found. Humans "
            "use these to break flow naturally."
        )

    return {"warnings": warnings, "metrics": metrics}


def validate_article(
    article: str,
    brief: ContentBrief,
    meta_title: str,
    meta_description: str,
    internal_links: list[InternalLink],
    reference_text: str = "",
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if count_h1(article) != 1:
        errors.append(
            "Article must contain exactly one H1."
        )

    if count_h1(article) == 1 and not re.search(
        r"^##\s+.+$",
        article,
        flags=re.MULTILINE,
    ):
        warnings.append(
            "Article has no H2 sections - structure may be too flat."
        )

    if len(meta_title) > 60:
        warnings.append(
            "Meta title exceeds 60 characters."
        )

    if len(meta_description) > 155:
        warnings.append(
            "Meta description exceeds 155 characters."
        )

    if (
        brief.primary_keyword.lower()
        not in article[:1200].lower()
    ):
        warnings.append(
            "Primary keyword is not present near the opening."
        )

    current_words = word_count(article)

    minimum_words, maximum_words = word_count_band(
        brief.target_word_count
    )

    if current_words < minimum_words:
        errors.append(
            f"Article contains {current_words} words; target is "
            f"{brief.target_word_count}, minimum allowed is "
            f"{minimum_words}."
        )
    elif current_words > maximum_words:
        errors.append(
            f"Article contains {current_words} words; target is "
            f"{brief.target_word_count}, maximum allowed is "
            f"{maximum_words}."
        )

    generic_phrases = [
        "in today's world",
        "when it comes to",
        "in conclusion",
        "overall",
        "it is important to note",
    ]

    article_lower = article.lower()

    for phrase in generic_phrases:
        if phrase in article_lower:
            warnings.append(
                f"Generic phrase detected: {phrase}"
            )

    originality_issue = check_originality(
        article,
        reference_text,
    )

    if originality_issue:
        warnings.append(originality_issue)

    errors.extend(
        validate_internal_links(
            internal_links,
            brief.website,
        )
    )

    humanization = humanization_checks(article)
    warnings.extend(humanization["warnings"])

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "word_count": current_words,
        "target_word_count": brief.target_word_count,
        "minimum_words": minimum_words,
        "maximum_words": maximum_words,
        "h1_count": count_h1(article),
        "keyword_count": keyword_count(
            article,
            brief.primary_keyword,
        ),
        "humanization_metrics": humanization["metrics"],
    }
