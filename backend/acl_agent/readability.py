"""Readability metrics. English formulas only unless language is English."""
from __future__ import annotations

import re
from typing import Any


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if len(p.split()) >= 2]


def _syllables(word: str) -> int:
    cleaned = re.sub(r"[^a-z]", "", word.lower())
    if not cleaned:
        return 1
    groups = re.findall(r"[aeiouy]+", cleaned)
    count = len(groups) or 1
    if cleaned.endswith("e") and count > 1:
        count -= 1
    return count


def analyze_readability(text: str, language: str = "en") -> dict[str, Any]:
    if len((text or "").split()) < 8:
        lang = (language or "en").lower()
        return {
            "score": None,
            "score_label": "Data unavailable",
            "status": "unavailable",
            "reason": "Article text could not be extracted.",
            "interpretation": "Not enough extracted article text to score readability.",
            "language": lang,
            "english_formulas_applied": False,
            "flesch_reading_ease": None,
            "flesch_kincaid_grade": None,
            "avg_sentence_length": None,
            "avg_paragraph_length": None,
            "avg_word_length": None,
            "passive_voice_pct": None,
            "long_sentence_pct": None,
            "transition_count": 0,
            "problematic_sentences": [],
            "rewrite_tips": [],
            "confidence": "low",
        }
    lang = (language or "en").lower()
    english = lang.startswith("en")
    sentences = _sentences(text)
    words = re.findall(r"[A-Za-z']+", text or "")
    word_n = max(len(words), 1)
    sent_n = max(len(sentences), 1)
    avg_sentence = round(word_n / sent_n, 1)
    paragraphs = [p for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    avg_paragraph = round(word_n / max(len(paragraphs), 1), 1)
    avg_word = round(sum(len(w) for w in words) / word_n, 2)
    long_sentences = sum(1 for s in sentences if len(s.split()) >= 28)
    long_pct = round(100 * long_sentences / sent_n, 1)
    passive = len(re.findall(r"\b(?:was|were|been|being|is|are|be)\s+\w+ed\b", text or "", re.I))
    passive_pct = round(100 * passive / sent_n, 1)
    transitions = len(re.findall(
        r"\b(however|therefore|meanwhile|for example|in addition|as a result)\b",
        text or "",
        re.I,
    ))
    syllables = sum(_syllables(w) for w in words)
    flesch = round(206.835 - 1.015 * (word_n / sent_n) - 84.6 * (syllables / word_n), 1)
    grade = round(0.39 * (word_n / sent_n) + 11.8 * (syllables / word_n) - 15.59, 1)
    score = max(0, min(100, int(flesch))) if english else None
    if flesch >= 70:
        meaning = "Easy to read"
    elif flesch >= 50:
        meaning = "Fairly readable"
    else:
        meaning = "Dense — shorten sentences"
    problematic = [s for s in sentences if len(s.split()) >= 32][:5]
    return {
        "score": score if english else None,
        "score_label": score if english else "Data unavailable",
        "interpretation": meaning if english else "English-only Flesch formulas were not applied.",
        "language": lang,
        "english_formulas_applied": english,
        "flesch_reading_ease": flesch if english else None,
        "flesch_kincaid_grade": grade if english else None,
        "avg_sentence_length": avg_sentence,
        "avg_paragraph_length": avg_paragraph,
        "avg_word_length": avg_word,
        "passive_voice_pct": passive_pct,
        "long_sentence_pct": long_pct,
        "transition_count": transitions,
        "heading_hint": "Use H2s every 200–300 words for scanability.",
        "problematic_sentences": problematic,
        "rewrite_tips": [
            "Split sentences over 25 words.",
            "Lead sections with a one-sentence answer.",
            "Prefer lists for steps and comparisons.",
        ] if (not english or score is None or score < 70) else [],
        "confidence": "medium" if english else "low",
    }
