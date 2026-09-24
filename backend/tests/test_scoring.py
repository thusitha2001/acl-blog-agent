"""Regression tests for on-page SEO/GEO/AEO scoring heuristics."""
from __future__ import annotations

import unittest

from acl_agent.models import ContentBrief, SEOAnalysis
from acl_agent.scoring import (
    _covers_reader_question,
    _definition_pattern,
    _named_entities,
    _pack,
    _score_aeo,
    _score_geo,
    score_article,
)


def _brief(**overrides) -> ContentBrief:
    payload = {
        "primary_keyword": "penang travel guide",
        "title": "Penang travel guide for first visits",
        "article_angle": "A practical first-timer guide to George Town.",
        "website": "https://example.com",
        "brand_name": "Example Travel",
    }
    payload.update(overrides)
    return ContentBrief(**payload)


def _seo(**overrides) -> SEOAnalysis:
    payload = {
        "primary_keyword": "penang travel guide",
        "meta_title": "Penang travel guide",
        "meta_description": "A practical first-timer guide to George Town, Penang.",
    }
    payload.update(overrides)
    return SEOAnalysis(**payload)


class PackNormalizationTests(unittest.TestCase):
    def test_missing_factor_cannot_still_score_100(self):
        packed = _pack(
            "SEO",
            "",
            [
                {"name": "a", "score": 100, "max": 100, "tip": ""},
                {"name": "b", "score": 0, "max": 10, "tip": "fix b"},
            ],
        )
        self.assertEqual(packed["score"], 91)
        self.assertLess(packed["score"], 100)
        self.assertEqual(packed["max_points"], 110)
        self.assertEqual(packed["earned_points"], 100)

    def test_full_points_still_100_when_max_is_not_100(self):
        packed = _pack(
            "GEO",
            "",
            [
                {"name": "a", "score": 55, "max": 55, "tip": ""},
                {"name": "b", "score": 55, "max": 55, "tip": ""},
            ],
        )
        self.assertEqual(packed["score"], 100)


class DefinitionPatternTests(unittest.TestCase):
    def test_generic_is_a_is_not_a_freebie(self):
        text = "It is a common approach. This is the reason people fly via Kuala Lumpur."
        self.assertFalse(_definition_pattern(text, "penang travel guide"))

    def test_keyword_anchored_definition_matches(self):
        text = "A penang travel guide is a practical itinerary for first-time visitors."
        self.assertTrue(_definition_pattern(text, "penang travel guide"))

    def test_score_ignores_unrelated_copula(self):
        article = (
            "# Other title\n\n"
            "It is a common approach to pack light. This is the reason most people overpack.\n\n"
            "## Getting around\n\n"
            "Grab is the easiest way across the island after you land."
        )
        report = _score_aeo(article, _brief(), _seo())
        definition = next(f for f in report["factors"] if f["name"] == "Definition snippet")
        self.assertLess(definition["score"], definition["max"])


class NamedEntityProxyTests(unittest.TestCase):
    def test_skips_title_case_headings_and_counts_mid_sentence_names(self):
        text = (
            "How To Get To Penang\n"
            "Ferries leave Butterworth every hour toward George Town and Armenian Street.\n"
        )
        count = _named_entities(text)
        self.assertGreaterEqual(count, 2)
        self.assertEqual(_named_entities("How To Get To Penang\n"), 0)


class ReaderQuestionTests(unittest.TestCase):
    def test_scattered_tokens_do_not_count_as_an_answer(self):
        question = "How much do boutique hotels cost in George Town?"
        scattered = [
            "Hotels line the harbor.",
            "Boutiques sell nutmeg soap.",
            "George Town has murals.",
            "The ferry cost is low.",
        ]
        self.assertFalse(_covers_reader_question(question, scattered))

    def test_same_block_overlap_counts(self):
        question = "How much do boutique hotels cost in George Town?"
        blocks = [
            "Boutique hotels in George Town cost about 80 dollars a night near Love Lane."
        ]
        self.assertTrue(_covers_reader_question(question, blocks))


class EditorialProxyTests(unittest.TestCase):
    def test_short_honest_does_not_unlock_full_points(self):
        article = "# Title\n\nThis is an honest overview.\n\nMost people visit in December."
        report = _score_geo(article, _brief(), _seo())
        depth = next(f for f in report["factors"] if f["name"] == "Editorial judgment language")
        self.assertEqual(depth["score"], 3)


class ExtendedScoreTests(unittest.TestCase):
    def test_score_article_includes_aio_and_sxo(self):
        article = """# Penang travel guide

Penang travel guide is a first-timer plan for George Town.

## How do I get to Penang?

Ferries leave Butterworth every twenty minutes.

## What should I eat?

Try char kway teow at a hawker centre.

- Walk the clan jetties
- See street art

It depends on how many days you have rather than copying a generic loop.
"""
        report = score_article(article, _brief(), _seo())
        self.assertIn("aio", report)
        self.assertIn("sxo", report)
        self.assertTrue(0 <= report["aio"]["score"] <= 100)
        self.assertTrue(0 <= report["overall"] <= 100)
        self.assertEqual(report["aio"]["max_points"], sum(f["max"] for f in report["aio"]["factors"]))


if __name__ == "__main__":
    unittest.main()
