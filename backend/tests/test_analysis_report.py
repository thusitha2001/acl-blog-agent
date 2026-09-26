"""Keyword gap and readability helpers."""
from __future__ import annotations

import unittest

from acl_agent.analysis_report import (
    action_plan,
    annotate_actions,
    build_verdict_summary,
    competitor_difference,
    ctr_checklist,
    gsc_query_opportunities,
    image_alt_report,
    merged_content_opportunities,
    quick_wins,
)
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


ARTICLE_HTML = """
<article>
  <h2>Why mesh bags</h2>
  <img src="/uploads/IMG_4821.jpg">
  <img src="https://cdn.example/cotton-mesh-produce-bags-600x400.webp" alt="IMG_4821">
  <h2>How to wash them</h2>
  <figure><img src="/a.png" alt=""><figcaption>Washing mesh bags in a sink</figcaption></figure>
  <img src="/icon.png" width="24" height="24" alt="">
  <img src="/divider.png" alt="" role="presentation">
  <img src="/good.jpg" alt="Three cotton mesh bags filled with apples">
</article>
"""


class ImageAltTests(unittest.TestCase):
    def _images(self):
        from bs4 import BeautifulSoup

        from acl_agent.competitors import _image_inventory

        return _image_inventory(BeautifulSoup(ARTICLE_HTML, "html.parser"), "https://blog.example/post")

    def test_inventory_tracks_section_caption_and_skips_icons(self):
        images = self._images()
        self.assertEqual(len(images), 5)
        self.assertEqual(images[0]["src"], "https://blog.example/uploads/IMG_4821.jpg")
        self.assertFalse(images[0]["has_alt_attr"])
        self.assertEqual(images[1]["filename_words"], ["cotton", "mesh", "produce", "bags"])
        self.assertEqual(images[2]["caption"], "Washing mesh bags in a sink")
        self.assertEqual(images[2]["section"], "How to wash them")
        self.assertTrue(images[3]["decorative"])

    def test_report_flags_issues_and_drafts_from_caption_or_filename(self):
        page = {"images": self._images(), "h2_headings": ["Why mesh bags", "How to wash them"]}
        report = image_alt_report(page, [], "reusable produce bags")
        summary = report["summary"]
        self.assertEqual((summary["missing"], summary["generic"], summary["empty"]), (1, 1, 1))
        self.assertEqual((summary["ok"], summary["decorative"]), (1, 1))
        by_issue = {item["issue"]: item for item in report["items"]}
        self.assertEqual(by_issue["Generic or file-name alt text"]["suggested_alt"], "Cotton mesh produce bags")
        self.assertEqual(
            by_issue["Empty alt (only right for purely decorative images)"]["suggested_alt"],
            "Washing mesh bags in a sink",
        )
        self.assertEqual(by_issue["No alt attribute"]["suggested_alt"], "")
        self.assertIn("Write descriptive alt text for 3 images", report["recommendations"][0])
        plan = action_plan(page, {}, {"gaps": {}}, {"table": []}, {"score": 80}, report)
        self.assertTrue(any(item["category"] == "Images" for item in plan))

    def test_competitor_image_gap_names_bare_sections(self):
        page = {"images": [], "h2_headings": ["Why mesh bags", "How to wash them"]}
        comp = {"images": [{"alt": "Mesh bag", "decorative": False}] * 5}
        report = image_alt_report(page, [comp], "reusable produce bags")
        self.assertEqual(report["competitors"]["avg_images"], 5)
        self.assertTrue(any("“Why mesh bags”" in rec for rec in report["recommendations"]))

    def test_keyword_stuffing_is_flagged(self):
        alts = ["Reusable produce bags", "Reusable produce bags in a kitchen", "Reusable produce bags at a market"]
        page = {"images": [{"alt": a, "has_alt_attr": True} for a in alts]}
        report = image_alt_report(page, [], "reusable produce bags")
        self.assertEqual(report["summary"]["stuffed"], 2)


class ReportAssemblyTests(unittest.TestCase):
    def test_verdict_uses_diagnosis_and_best_gsc_query(self):
        verdict = build_verdict_summary(
            {
                "text": "Visibility drop over last 6 months (-82% impressions).",
                "confidence": "medium",
                "seasonal_caveat": True,
                "delta_pct": -82.3,
            },
            {
                "our_blog_basis": "search_console",
                "our_blog": [{
                    "keyword": "how to make christmas dinner for a crowd",
                    "evidence": "80 clicks · 900 impressions · avg position 8.8",
                    "source": "search_console",
                }],
            },
            {"target_keyword": "christmas dinner ideas", "search_console_query": "how to make christmas dinner for a crowd"},
            {
                "keyword_targeting": {"mismatch": True, "in_title": False, "in_h1": False},
                "title": {"issues": ["Title does not contain the target keyword"]},
                "h1": {"issues": ["H1 does not contain the target keyword"]},
            },
            {"title": "Best Christmas Dinner Ideas for a Large Group", "h1": "15 Dishes to Delight"},
        )
        self.assertTrue(any("-82.3%" in line or "-82.3" in line for line in verdict["observed"]))
        self.assertTrue(any("how to make christmas dinner for a crowd" in line for line in verdict["observed"]))
        self.assertTrue(any("8.8" in line for line in verdict["observed"]))
        self.assertTrue(any("Title and H1" in line for line in verdict["observed"]))
        self.assertIn("Seasonality", verdict["areas_to_check"])
        self.assertTrue(any("year-over-year" in line for line in verdict["verification"]))
        self.assertIn("medium", verdict["text"])

    def test_verdict_reports_url_inspection_indexed(self):
        verdict = build_verdict_summary(
            {"text": "Visibility drop.", "confidence": "high", "delta_pct": -10},
            {},
            None,
            {
                "index_status": {
                    "indexed": True,
                    "label": "Indexed",
                    "coverage_state": "Submitted and indexed",
                    "last_crawl": "2026-09-20T08:00:00Z",
                    "source": "url_inspection",
                },
            },
        )
        self.assertTrue(any("Indexed" in line for line in verdict["observed"]))
        self.assertTrue(any("Submitted and indexed" in line for line in verdict["observed"]))
        self.assertTrue(any("URL Inspection already returned" in line for line in verdict["verification"]))
        self.assertFalse(any("Check URL indexing" in line for line in verdict["verification"]))

    def test_verdict_does_not_claim_indexed_from_robots(self):
        verdict = build_verdict_summary(
            {"text": "Visibility drop.", "confidence": "medium"},
            {},
            None,
            {
                "index_status": {
                    "indexed": None,
                    "label": "Inspection unavailable",
                    "source": "robots_only",
                    "robots_status": "indexable",
                    "impressions_hint": "Search Console recorded 447 impressions. That means Google has shown this URL; it is not a coverage-state check.",
                },
                "indexing": {"status": "indexable"},
            },
        )
        self.assertTrue(any("Inspection unavailable" in line for line in verdict["observed"]))
        self.assertTrue(any("not a Google index check" in line for line in verdict["observed"]))
        self.assertFalse(any(line.startswith("Google index: Indexed") for line in verdict["observed"]))
        self.assertTrue(any("Check URL indexing" in line for line in verdict["verification"]))

    def test_merged_table_dedupes_near_duplicate_gap_and_heading(self):
        merged = merged_content_opportunities(
            [{"keyword": "christmas dinner cost", "evidence": "Used by 2 competitors"}],
            {"table": [
                {"missing_topic": "Christmas dinner cost table", "covered_by": "a.example", "importance": "high", "recommended_heading": "What does Christmas dinner cost?"},
                {"missing_topic": "Make-ahead sides", "covered_by": "b.example", "importance": "medium", "recommended_heading": "Make-ahead sides"},
            ]},
        )
        topics = [row["topic"] for row in merged["table"]]
        self.assertTrue(any("cost" in topic.lower() for topic in topics))
        self.assertIn("Make-ahead sides", topics)
        dual = [row for row in merged["table"] if "keyword_gap" in row["sources"] and "heading_gap" in row["sources"]]
        self.assertTrue(dual)

    def test_competitor_difference_omits_weak_gaps(self):
        self.assertIsNone(competitor_difference(
            {"word_count": 1400, "table_count": 1},
            {"onpage_technical_score": 70},
            {"word_count": 1500, "table_count": 1, "scores": {"onpage_technical_score": 72}, "signals": []},
            [],
        ))
        sentence = competitor_difference(
            {"word_count": 800, "table_count": 0},
            {"onpage_technical_score": 40},
            {
                "word_count": 2400,
                "table_count": 1,
                "scores": {"onpage_technical_score": 70},
                "signals": [{"kind": "positive", "label": "Clear buying criteria"}],
            },
            [],
        )
        self.assertIn("2,400 words", sentence)
        self.assertIn("3.0x", sentence)

    def test_actions_get_why_confidence_and_no_click_forecast(self):
        plan = annotate_actions(
            [{
                "priority": "High Priority",
                "category": "Title",
                "issue": "Title mismatch",
                "recommended_action": "Rewrite the title",
                "estimated_impact": "~990 clicks per period",
                "estimated_effort": "Low",
            }],
            {"keyword_targeting": {"mismatch": True, "primary_ranking_query": "how to make christmas dinner for a crowd"}},
        )
        self.assertEqual(plan[0]["coverage_class"], "must")
        self.assertEqual(plan[0]["recommendation_confidence"], "high")
        self.assertTrue(plan[0]["why"])
        self.assertEqual(plan[0]["estimated_impact"], "High")
        self.assertIn("Not a traffic forecast", plan[0]["impact_note"])
        self.assertEqual(len(quick_wins(plan)), 1)

    def test_gsc_buckets_and_ctr_checklist_use_existing_queries(self):
        gsc = {
            "impressions": 2000,
            "ctr": 0.001,
            "position": 9.4,
            "intent_split": {"informational": 2000},
            "keyword_targeting": {"mismatch": True, "in_title": False},
            "meta": {"issues": ["Meta description is thin"]},
            "queries": [
                {"query": "christmas dinner for a crowd", "position": 8.8, "impressions": 900, "clicks": 80},
                {"query": "easy christmas dinner", "position": 14.0, "impressions": 200, "clicks": 2},
                {"query": "christmas soup recipes", "position": 28.0, "impressions": 40, "clicks": 0},
                {"query": "brand shop", "position": 5.0, "impressions": 10, "clicks": 8, "branded": True},
            ],
        }
        buckets = gsc_query_opportunities(gsc)
        self.assertEqual([row["query"] for row in buckets["quick_wins"]], ["christmas dinner for a crowd"])
        self.assertEqual([row["query"] for row in buckets["page_two"]], ["easy christmas dinner"])
        self.assertEqual([row["query"] for row in buckets["content"]], ["christmas soup recipes"])
        self.assertNotIn("brand shop", [row["query"] for group in buckets.values() if isinstance(group, list) for row in group])
        ctr = ctr_checklist(gsc)
        self.assertEqual(ctr["status"], "gap")
        self.assertTrue(any("Title" in item for item in ctr["possible_checks"]))
        self.assertIn("not a click forecast", ctr["note"].lower())


if __name__ == "__main__":
    unittest.main()
