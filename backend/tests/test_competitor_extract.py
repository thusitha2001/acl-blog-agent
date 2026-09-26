"""Regression tests for competitor page extraction fallbacks."""
from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from acl_agent.auto_brief import SERPResult, _serp_results_match_query, search_serp
from acl_agent.competitors import (
    _competitor_does_well,
    _extract_modified_datetime,
    _extract_title,
    _fallback_page,
    _order_serp_results,
    _page_flags,
    _page_stats,
    _parse_datetime,
    _relative_updated,
    _score_page,
    _select_competitor_rows,
)
from bs4 import BeautifulSoup

FIXTURES = Path(__file__).resolve().parent / "fixtures"

TRAVELMERMAID = "https://travelmermaid.com/travel/the-charm-of-george-town-penang/"
WANDERLULUU = "https://www.wanderluluu.com/7-things-to-love-george-town-penang/"
MISSFILATELISTA = (
    "https://www.missfilatelista.com/penang-travel-guide-where-to-explore-eat-and-stay/"
)

ELEMENTOR_HTML = """
<html>
<head>
  <meta property="og:title" content="Elementor Penang Guide">
  <meta property="article:modified_time" content="2019-11-03T13:56:35+00:00">
  <title>Wrong leftover</title>
</head>
<body>
  <header class="elementor-location-header"><p>Nav chrome</p></header>
  <div class="elementor-location-single">
    <div class="elementor-widget-container"><h2>How to Get to Penang</h2></div>
    <div class="elementor-widget-container"><div>Ferries leave Butterworth every hour and the ride takes about twenty minutes across the channel.</div></div>
    <div class="elementor-widget-container"><h2>Where to Stay</h2></div>
    <div class="elementor-widget-container"><div>George Town guesthouses around Love Lane are walkable to street art and cafes for a weekend stay without needing a car.</div></div>
    <div class="elementor-widget-container"><h2>What to Do in Penang</h2></div>
    <div class="elementor-widget-container"><div>Walk the clan jetties, eat at a hawker centre, and leave time for a street-art loop through Armenian Street before sunset.</div></div>
    <div class="elementor-widget-container"><div>Travelers also visit Kek Lok Si, sample nutmeg juice, and use Grab for the hills when the heat picks up in the afternoon.</div></div>
  </div>
</body>
</html>
"""


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ExtractorFixtureTests(unittest.TestCase):
    def test_travelmermaid_baseline(self):
        page = _page_stats(TRAVELMERMAID, _load("travelmermaid.html"), {})
        self.assertTrue(page["extract_ok"])
        self.assertIn("Charm of George Town", page["title"])
        self.assertGreaterEqual(page["word_count"] or 0, 1800)
        self.assertTrue((page["updated_at"] or "").startswith("2026-09-05"))
        self.assertNotEqual(page["updated"], "Unknown")
        self.assertNotEqual(page["updated"], "Updated recently")
        scores = _score_page("george town penang", page)
        self.assertIsNotNone(scores["seo"])
        self.assertEqual(scores["confidence"], "high")

    def test_wanderluluu_baseline(self):
        page = _page_stats(WANDERLULUU, _load("wanderluluu.html"), {})
        self.assertTrue(page["extract_ok"])
        self.assertIn("7 Things to Love", page["title"])
        self.assertGreaterEqual(page["word_count"] or 0, 1800)
        self.assertTrue((page["updated_at"] or "").startswith("2017-12-06"))
        scores = _score_page("george town penang", page)
        self.assertIsNotNone(scores["seo"])

    def test_missfilatelista_no_placeholder_fallbacks(self):
        page = _page_stats(MISSFILATELISTA, _load("missfilatelista.html"), {})
        self.assertTrue(page["extract_ok"], page.get("extract_error"))
        self.assertEqual(
            page["title"],
            "George Town, Penang Travel Guide: Where to Explore and Stay - Miss Filatelista",
        )
        self.assertFalse(str(page["title"]).startswith("http"))
        self.assertGreaterEqual(page["word_count"] or 0, 700)
        self.assertTrue((page["updated_at"] or "").startswith("2019-11-03"))
        self.assertNotEqual(page["updated"], "Updated recently")
        self.assertNotEqual(page["updated"], "Unknown")
        does_well = _competitor_does_well(page, _page_flags(page))
        self.assertNotIn("missfilatelista.com", does_well)
        self.assertFalse(does_well.startswith("http"))
        scores = _score_page("george town penang", page)
        self.assertIsNotNone(scores["seo"])
        self.assertNotEqual(scores["confidence"], "unavailable")


class FallbackSafetyTests(unittest.TestCase):
    def test_fallback_page_does_not_invent_metrics(self):
        page = _fallback_page(
            MISSFILATELISTA,
            MISSFILATELISTA,
            "",
        )
        self.assertFalse(page["extract_ok"])
        self.assertEqual(page["title"], "")
        self.assertIsNone(page["word_count"])
        self.assertEqual(page["updated"], "Unknown")
        self.assertIsNone(page["updated_at"])
        does_well = _competitor_does_well(page, _page_flags(page))
        self.assertEqual(does_well, "")
        scores = _score_page("george town penang", page)
        self.assertIsNone(scores["seo"])
        self.assertEqual(scores["confidence"], "unavailable")

    def test_relative_updated_unknown_when_missing(self):
        self.assertEqual(_relative_updated(None), "Unknown")
        parsed = _parse_datetime("2019-11-03T13:56:35+00:00")
        self.assertIsInstance(parsed, datetime)
        self.assertEqual(parsed.date().isoformat(), "2019-11-03")

    def test_elementor_leaf_divs_and_og_title(self):
        soup = BeautifulSoup(ELEMENTOR_HTML, "html.parser")
        self.assertEqual(_extract_title(soup), "Elementor Penang Guide")
        modified = _extract_modified_datetime(soup)
        self.assertEqual(modified.date().isoformat(), "2019-11-03")
        page = _page_stats("https://example.com/penang", ELEMENTOR_HTML, {})
        self.assertGreaterEqual(page["word_count"] or 0, 40)
        self.assertEqual(page["title"], "Elementor Penang Guide")
        self.assertTrue((page["updated_at"] or "").startswith("2019-11-03"))


class AutoCompetitorFillTests(unittest.TestCase):
    def test_order_serp_fills_five_including_weaker_matches(self):
        results = [
            SERPResult("George Town Penang travel guide", "https://a.com/penang-guide", "Stay and eat in George Town"),
            SERPResult("Penang itinerary", "https://b.com/penang", "What to do in Penang"),
            SERPResult("Travel tips for Penang", "https://c.com/stay", "Travel days in Penang"),
            SERPResult("Penang food travel", "https://d.com/food", "Penang travel eats"),
            SERPResult("George Town street art", "https://e.com/art", "George Town Penang murals"),
            SERPResult("Hotel deals this week", "https://f.com/deals", "Book a room tonight"),
            SERPResult("George at ASDA", "https://direct.asda.com/george", "Kids clothes from George"),
            SERPResult("Penang Wikipedia", "https://en.wikipedia.org/wiki/Penang", "Penang is a Malaysian state"),
        ]
        ordered = _order_serp_results("penang travel guide", results)
        urls = [item.url for item in ordered]
        self.assertGreaterEqual(len(ordered), 5)
        self.assertTrue(urls[0].startswith("https://a.com"))
        self.assertNotIn("wikipedia.org", " ".join(urls))
        self.assertNotIn("asda.com", " ".join(urls))
        self.assertNotIn("https://f.com/deals", urls)

    def test_skips_leading_token_only_matches(self):
        results = [
            SERPResult("George Login", "https://bank.example/george", "Online banking with George"),
            SERPResult("Curious George", "https://youtube.com/george", "Official Curious George"),
            SERPResult("Penang travel days", "https://ok.com/penang", "A Penang travel guide"),
        ]
        ordered = _order_serp_results("george town penang travel guide", results)
        urls = [item.url for item in ordered]
        self.assertEqual(urls, ["https://ok.com/penang"])

    def test_select_fills_to_five_when_few_are_on_topic(self):
        pending = []
        for index in range(6):
            pending.append({
                "is_manual": False,
                "topic": 4 if index < 2 else 1,
                "extract_ok": index < 2,
                "row": {"url": f"https://site{index}.com/post"},
            })
        selected = _select_competitor_rows(pending, target=5, needed=3)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected[0]["url"], "https://site0.com/post")
        self.assertEqual(selected[1]["url"], "https://site1.com/post")

    def test_manual_urls_kept_then_auto_fill(self):
        pending = [
            {"is_manual": True, "topic": 5, "topic_mismatch": False, "extract_ok": True, "row": {"url": "https://manual.com/a"}},
            {"is_manual": False, "topic": 5, "extract_ok": True, "row": {"url": "https://auto.com/1"}},
            {"is_manual": False, "topic": 4, "extract_ok": True, "row": {"url": "https://auto.com/2"}},
            {"is_manual": False, "topic": 1, "extract_ok": False, "row": {"url": "https://auto.com/3"}},
            {"is_manual": False, "topic": 1, "extract_ok": False, "row": {"url": "https://auto.com/4"}},
            {"is_manual": False, "topic": 0, "extract_ok": False, "row": {"url": "https://auto.com/5"}},
        ]
        selected = _select_competitor_rows(pending, target=5, needed=3)
        self.assertEqual(len(selected), 5)
        self.assertEqual(selected[0]["url"], "https://manual.com/a")

    def test_off_topic_manuals_are_not_kept_as_normal_competitors(self):
        pending = [
            {"is_manual": True, "topic": 0, "topic_mismatch": True, "extract_ok": True, "row": {"url": "https://blackberrys.com/hoodie"}},
            {"is_manual": False, "topic": 5, "topic_mismatch": False, "extract_ok": True, "row": {"url": "https://bali.example/lempuyang"}},
            {"is_manual": False, "topic": 4, "topic_mismatch": False, "extract_ok": True, "row": {"url": "https://bali.example/gate"}},
            {"is_manual": False, "topic": 4, "topic_mismatch": False, "extract_ok": True, "row": {"url": "https://travel.example/temple"}},
            {"is_manual": False, "topic": 1, "topic_mismatch": False, "extract_ok": False, "row": {"url": "https://weak.example/a"}},
            {"is_manual": False, "topic": 1, "topic_mismatch": False, "extract_ok": False, "row": {"url": "https://weak.example/b"}},
        ]
        selected = _select_competitor_rows(pending, target=5, needed=3)
        urls = [row["url"] for row in selected]
        self.assertNotIn("https://blackberrys.com/hoodie", urls)
        self.assertEqual(urls[0], "https://bali.example/lempuyang")


class SerpQualityTests(unittest.TestCase):
    def test_dictionary_bing_hits_are_off_topic(self):
        rows = [
            SERPResult("STYLE Definition & Meaning", "https://www.merriam-webster.com/dictionary/style", "style"),
            SERPResult("InStyle homepage", "https://www.instyle.com/", "celebrity style"),
            SERPResult("HTML style tag", "https://www.w3schools.com/TAGs/tag_style.asp", "style attribute"),
        ]
        self.assertFalse(_serp_results_match_query("style mens oversized hoodies", rows))

    def test_hoodie_guides_are_on_topic(self):
        rows = [
            SERPResult(
                "15 Ways to Style an Oversized Hoodie for Men",
                "https://urbanmenstyle.com/ways-to-style-an-oversized-hoodie-for-men/",
                "outfit ideas for oversized hoodies",
            ),
        ]
        self.assertTrue(_serp_results_match_query("style mens oversized hoodies", rows))

    def test_order_keeps_hoodie_guides(self):
        results = [
            SERPResult("STYLE Definition", "https://www.merriam-webster.com/dictionary/style", "style"),
            SERPResult(
                "15 Ways to Style an Oversized Hoodie for Men",
                "https://urbanmenstyle.com/hoodie",
                "oversized hoodie outfits",
            ),
            SERPResult(
                "How to Style Men's Oversized Hoodies",
                "https://www.example.com/style-mens-oversized-hoodies",
                "outfit ideas",
            ),
        ]
        ordered = _order_serp_results("style mens oversized hoodies", results)
        urls = " ".join(item.url for item in ordered)
        self.assertIn("urbanmenstyle.com", urls)
        self.assertIn("example.com", urls)
        self.assertNotIn("merriam-webster", urls)

    def test_search_serp_falls_through_to_duckduckgo(self):
        bing = [
            SERPResult("STYLE Definition", "https://www.merriam-webster.com/dictionary/style", "style"),
        ]
        ddg_rows = [
            {
                "title": "How to Style Men's Oversized Hoodies",
                "href": "https://urbanmenstyle.com/hoodie",
                "body": "oversized hoodie outfit ideas for men",
            }
        ]

        class FakeDDGS:
            def __init__(self, timeout=12):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def text(self, query, max_results=10, region="us-en", backend="duckduckgo"):
                return ddg_rows

        from unittest.mock import patch
        with patch("acl_agent.auto_brief._search_bing", return_value=bing), patch(
            "ddgs.DDGS", FakeDDGS
        ):
            rows = search_serp("style mens oversized hoodies", max_results=8)
        self.assertEqual(rows[0].url, "https://urbanmenstyle.com/hoodie")


if __name__ == "__main__":
    unittest.main()
