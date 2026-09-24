"""Regression tests for keyword validation, intent, AIO/SXO, and content gaps."""
from __future__ import annotations

import unittest

from acl_agent.analysis_input import average_competitor_scores
from acl_agent.analysis_report import action_plan, content_gaps, originality_report
from acl_agent.competitors import _score_page
from acl_agent.keywords import (
    classify_page_intent,
    compare_keywords,
    match_status,
    validate_keyword,
)


HOODIE_ARTICLE = (
    "How to Style Men’s Oversized Hoodies: Best Outfit Ideas. "
    "An oversized hoodie looks better when the shoulders sit slightly past your own "
    "and the hem hits mid-hip. Pair it with tapered jeans, clean sneakers, and a "
    "simple watch. Layer a chore coat over the hoodie in cold weather. "
    "Casual streetwear looks work when you keep one item fitted. "
    "Avoid stacking baggy pants with a huge hoodie. "
    "Choose a color that contrasts with your denim. "
) * 4

HOODIE_PAGE = {
    "title": "How to Style Men’s Oversized Hoodies: Best Outfit Ideas",
    "h1": "How to Style Men’s Oversized Hoodies: Best Outfit Ideas",
    "h1_headings": ["How to Style Men’s Oversized Hoodies: Best Outfit Ideas"],
    "h2_headings": ["Casual streetwear looks", "Layering in cold weather"],
    "text": HOODIE_ARTICLE,
    "full_text": HOODIE_ARTICLE,
    "meta_description": "Outfit ideas for styling oversized hoodies.",
    "extract_ok": True,
    "word_count": len(HOODIE_ARTICLE.split()),
    "source_markdown": "# How to Style Men’s Oversized Hoodies\n\n" + HOODIE_ARTICLE,
    "schema_types": ["Article"],
    "author": "Editor",
    "faq": {"answered": 0},
    "domain": "example.com",
    "url": "https://example.com/style-mens-oversized-hoodies",
    "content_type": "Blog",
}

SHOP_COMPETITORS = [
    {
        "title": "Buy Oversized Shirts for Men Online in India",
        "url": "https://www.bewakoof.com/collections/oversized-t-shirts",
        "domain": "bewakoof.com",
        "h1_headings": ["Buy Oversized Shirts for Men Online in India"],
        "h2_headings": ["Size chart", "Add to cart"],
        "text": "Buy oversized shirts for men online. Best prices on oversized t shirt men.",
        "snippet": "Shop oversized t-shirts",
        "meta_description": "Buy oversized t-shirts for men and women online.",
    },
    {
        "title": "Buy Oversized T-shirts For Men & Women Online | Bewakoof",
        "url": "https://www.bewakoof.com/oversized-t-shirts",
        "domain": "bewakoof.com",
        "h2_headings": [],
        "text": "Bewakoof oversized t shirt collection.",
    },
    {
        "title": "Buy Oversized & Baggy T-Shirts for Men Online in India | Trendy Streetwear – CrazyMonk",
        "url": "https://crazymonk.in/collections/oversized",
        "domain": "crazymonk.in",
        "h2_headings": [],
        "text": "CrazyMonk baggy t-shirts.",
    },
    {
        "title": "Amazon.in : oversized",
        "url": "https://www.amazon.in/s?k=oversized",
        "domain": "amazon.in",
        "h2_headings": [],
        "text": "Amazon oversized products.",
    },
    {
        "title": "Oversized T Shirt Men",
        "url": "https://shop.example/oversized-t-shirt-men",
        "domain": "shop.example",
        "h2_headings": ["Buy now"],
        "text": "Buy oversized t shirt men online.",
    },
]

GUIDE_COMPETITOR = {
    "title": "Oversized hoodie outfit guide",
    "url": "https://style.example/oversized-hoodie-outfits",
    "domain": "style.example",
    "h1_headings": ["Oversized hoodie outfit guide"],
    "h2_headings": [
        "How should an oversized hoodie fit?",
        "What pants pair well with an oversized hoodie?",
        "Best shoes for an oversized hoodie outfit",
    ],
    "text": (
        "How should an oversized hoodie fit? The shoulder seam should sit just past yours. "
        "What pants pair well with an oversized hoodie? Tapered jeans keep the look balanced. "
        "Best shoes for an oversized hoodie outfit are chunky sneakers. "
        "Layering oversized hoodies with jackets works in winter."
    ),
    "snippet": "A styling guide for oversized hoodie outfits.",
}


class TitleNotKeywordTests(unittest.TestCase):
    def test_page_titles_are_not_returned_as_keywords(self):
        report = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, SHOP_COMPETITORS)
        phrases = [row["keyword"].lower() for row in report["table"]]
        banned = [
            "buy oversized shirts for men online in india",
            "oversized t shirt men",
            "buy oversized t-shirts for men & women online | bewakoof",
            "amazon.in : oversized",
            "buy oversized & baggy t-shirts",
        ]
        for phrase in banned:
            self.assertFalse(any(phrase in item for item in phrases), phrase)
        self.assertTrue(all(row.get("page_title_signal") is not True or row["type"] == "primary" for row in report["table"]))

    def test_brand_names_are_filtered(self):
        flags = validate_keyword(
            "Bewakoof oversized",
            "style mens oversized hoodies",
            source="heading",
            domains=["bewakoof.com"],
        )
        self.assertFalse(flags["accepted"])
        self.assertEqual(flags["rejection_reason"], "brand_or_domain")

    def test_product_titles_are_not_recommended_headings(self):
        gaps = content_gaps(HOODIE_PAGE, SHOP_COMPETITORS + [GUIDE_COMPETITOR], "style mens oversized hoodies")
        blob = " ".join(
            [row["missing_topic"] for row in gaps["table"]]
            + gaps["recommended_outline"]
            + [row["recommended_heading"] for row in gaps["table"]]
        ).lower()
        self.assertNotIn("bewakoof", blob)
        self.assertNotIn("crazymonk", blob)
        self.assertNotIn("amazon.in", blob)
        self.assertNotIn("buy oversized shirts", blob)
        self.assertTrue(any("pants" in row["missing_topic"].lower() or "fit" in row["missing_topic"].lower() for row in gaps["table"]))


class MatchStatusTests(unittest.TestCase):
    def test_close_variant_for_natural_title(self):
        match = match_status(
            "style mens oversized hoodies",
            HOODIE_ARTICLE,
            title=HOODIE_PAGE["title"],
            headings=HOODIE_PAGE["h2_headings"],
        )
        self.assertEqual(match["status"], "close_variant")
        self.assertIn("Oversized", match["matched_text"])
        self.assertIn("natural word-order", match["match_reason"])

    def test_exact_close_variant_and_missing(self):
        exact = match_status(
            "casual streetwear looks",
            HOODIE_ARTICLE,
            title=HOODIE_PAGE["title"],
            headings=HOODIE_PAGE["h2_headings"],
        )
        missing = match_status(
            "waterproof hiking boots",
            HOODIE_ARTICLE,
            title=HOODIE_PAGE["title"],
            headings=HOODIE_PAGE["h2_headings"],
        )
        report = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, [GUIDE_COMPETITOR])
        primary = next(row for row in report["table"] if row["type"] == "primary")
        self.assertEqual(exact["status"], "exact")
        self.assertEqual(primary["my_blog_status"], "close_variant")
        self.assertEqual(missing["status"], "missing")
        self.assertIn(primary["my_blog_status"], {"exact", "close_variant", "missing"})


class IntentTests(unittest.TestCase):
    def test_shopping_pages_are_intent_mismatch(self):
        self.assertEqual(classify_page_intent(SHOP_COMPETITORS[0]), "transactional")
        self.assertEqual(classify_page_intent(GUIDE_COMPETITOR), "informational")
        report = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, SHOP_COMPETITORS + [GUIDE_COMPETITOR])
        phrases = [row["keyword"].lower() for row in report["table"]]
        self.assertFalse(any("buy oversized" in item for item in phrases))


class ScoreAndPlanTests(unittest.TestCase):
    def test_aio_and_sxo_when_article_text_exists(self):
        scores = _score_page("style mens oversized hoodies", HOODIE_PAGE)
        self.assertIsInstance(scores["aio"], int)
        self.assertIsInstance(scores["sxo"], int)
        self.assertEqual(scores["reports"]["aio"]["status"], "available")
        self.assertEqual(scores["reports"]["sxo"]["status"], "available")
        self.assertTrue(scores["reports"]["aio"]["factors"])
        self.assertTrue(scores["reports"]["sxo"]["factors"])
        names = {f["name"] for f in scores["reports"]["aio"]["factors"]}
        self.assertIn("Entity clarity", names)
        sxo_names = {f["name"] for f in scores["reports"]["sxo"]["factors"]}
        self.assertIn("Search intent match", sxo_names)

    def test_null_aio_sxo_do_not_break_averages(self):
        rows = [
            {"scores": {"seo": 20, "geo": 50, "aeo": 40, "aio": None, "sxo": None}},
            {"scores": {"seo": 30, "geo": 60, "aeo": 50, "aio": None, "sxo": None}},
        ]
        avg = average_competitor_scores(rows)
        self.assertEqual(avg["seo"], 25.0)
        self.assertIsNone(avg["aio"])
        self.assertIsNone(avg["sxo"])

    def test_action_plan_from_real_findings(self):
        keywords = compare_keywords("style mens oversized hoodies", HOODIE_PAGE, [GUIDE_COMPETITOR])
        gaps = content_gaps(HOODIE_PAGE, [GUIDE_COMPETITOR], "style mens oversized hoodies")
        scores = _score_page("style mens oversized hoodies", HOODIE_PAGE)
        plan = action_plan(HOODIE_PAGE, scores, keywords, gaps, {"score": 70})
        self.assertTrue(plan)
        self.assertTrue(any(item["category"] in {"Keyword", "Content", "AEO"} for item in plan))

    def test_independent_reports_exist(self):
        original = originality_report(HOODIE_PAGE, [GUIDE_COMPETITOR])
        self.assertIn("Internal similarity check only", original["disclaimer"])
        self.assertIn("Not a definitive legal plagiarism determination", original["disclaimer"])
        gaps = content_gaps(HOODIE_PAGE, [GUIDE_COMPETITOR], "style mens oversized hoodies")
        self.assertTrue(gaps["recommended_outline"])
        self.assertTrue(any("fit" in h.lower() or "pants" in h.lower() or "faq" in h.lower() for h in gaps["recommended_outline"]))


if __name__ == "__main__":
    unittest.main()
