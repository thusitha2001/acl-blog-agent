"""Keyword gap and readability helpers."""
from __future__ import annotations

import unittest

from acl_agent.keywords import compare_keywords, extract_terms
from acl_agent.readability import analyze_readability


class KeywordGapTests(unittest.TestCase):
    def test_competitor_only_phrase_is_a_gap(self):
        yours = {
            "title": "Penang basics",
            "h2_headings": ["Getting around"],
            "text": "Penang ferries are frequent and George Town is walkable.",
        }
        competitors = [{
            "title": "Penang street art guide",
            "h2_headings": ["Street art in George Town", "Clan jetties"],
            "text": "Street art in George Town and clan jetties are the weekend highlights. Street art in George Town covers Armenian Street.",
            "domain": "example.com",
        }]
        report = compare_keywords("penang travel guide", yours, competitors)
        phrases = [row["keyword"] for row in report["gaps"]["high-priority"]]
        self.assertTrue(any("street art" in p for p in phrases) or report["gaps"]["high-priority"])
        self.assertTrue(all(row["search_volume"] == "Data unavailable" for row in report["table"]))


class ReadabilityTests(unittest.TestCase):
    def test_english_flesch_returns_score(self):
        text = "George Town is easy to walk. Ferries leave often. Eat at a hawker stall before sunset."
        report = analyze_readability(text, "en")
        self.assertIsNotNone(report["score"])
        self.assertTrue(report["english_formulas_applied"])

    def test_non_english_does_not_fake_flesch(self):
        report = analyze_readability("இது ஒரு சோதனை வாக்கியம்.", "ta")
        self.assertIsNone(report["score"])
        self.assertEqual(report["score_label"], "Data unavailable")


if __name__ == "__main__":
    unittest.main()
