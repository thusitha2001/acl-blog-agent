"""Keyword gap and readability helpers."""
from __future__ import annotations

import unittest

from acl_agent.analysis_report import action_plan, image_alt_report
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


if __name__ == "__main__":
    unittest.main()
