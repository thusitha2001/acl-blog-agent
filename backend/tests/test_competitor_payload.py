"""Regression tests for competitor analysis request, SERP query, and reports."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from acl_agent.analysis_input import (
    average_competitor_scores,
    detect_keyword_from_article,
    validate_blog_url,
)
from acl_agent.analysis_report import humanization_report, originality_report
from acl_agent.api import CompetitorAnalyzeRequest
from acl_agent.auto_brief import SERPAnalysis, SERPResult
from acl_agent.competitors import analyze_competitors, _score_page
from acl_agent.keywords import compare_keywords
from acl_agent.readability import analyze_readability


BEDDING_TEXT = (
    "Find the Perfect Bedding Style for Your Bedroom. "
    "A duvet, sheets, and a quilt layer keep a bed comfortable through the seasons. "
    "Choose a breathable cotton percale for summer and a heavier weave for winter nights. "
    "Layer two pillow types so guests can pick the loft they prefer. "
    "Wash linens weekly and rotate blankets so the fabric lasts. "
    "This article explains bedding style choices with specific examples from a small bedroom."
) * 3

BEDDING_PAGE = {
    "url": "https://www.example.com/blogs/news/perfect-bedding-style",
    "title": "Find the Perfect Bedding Style for Your Bedroom",
    "h1": "Find the Perfect Bedding Style for Your Bedroom",
    "h1_count": 1,
    "h2_count": 3,
    "h1_headings": ["Find the Perfect Bedding Style for Your Bedroom"],
    "h2_headings": ["Cotton vs linen", "Layering a small bed", "Care and washing"],
    "word_count": len(BEDDING_TEXT.split()),
    "text": BEDDING_TEXT,
    "full_text": BEDDING_TEXT,
    "source_markdown": "# Find the Perfect Bedding Style for Your Bedroom\n\n" + BEDDING_TEXT,
    "article_html": BEDDING_TEXT,
    "extract_ok": True,
    "meta_description": "Bedding style ideas for a comfortable bedroom.",
    "author": "Editor",
    "domain": "example.com",
    "favicon": "https://example.com/favicon.ico",
    "content_type": "Blog",
    "authority": "Medium authority",
    "schema_types": ["Article"],
    "faq": {"answered": 1},
    "updated_at": "2026-01-01T00:00:00+00:00",
}

COMP_PAGE = {
    **BEDDING_PAGE,
    "url": "https://competitor.example/fall-table-decor",
    "domain": "competitor.example",
    "title": "Fall table decor ideas",
    "h1": "Fall table decor ideas",
    "h2_headings": ["Pumpkin centerpieces", "Tablecloth colors", "Outdoor table settings"],
    "text": "Fall table decor with pumpkin centerpieces and tablecloth colors. Outdoor table settings for dinner.",
    "full_text": "Fall table decor with pumpkin centerpieces and tablecloth colors. Outdoor table settings for dinner. "
    + BEDDING_TEXT,
    "extract_ok": True,
}


class BlogUrlValidationTests(unittest.TestCase):
    def test_blog_url_is_kept_exactly(self):
        url = "https://www.allcottonandlinen.com/blogs/news/fall-table-decor-ideas"
        check = validate_blog_url(url)
        self.assertTrue(check["ok"])
        self.assertEqual(check["url"], url)
        req = CompetitorAnalyzeRequest(blog_url=url, keyword="fall table decor")
        self.assertEqual(req.blog_url, url)

    def test_local_competitors_hash_is_rejected(self):
        for raw in (
            "http://127.0.0.1:8001/competitors#",
            "http://127.0.0.1:8001/competitors",
            "/competitors#",
            "#",
        ):
            check = validate_blog_url(raw)
            self.assertFalse(check["ok"], raw)
            self.assertEqual(check["status"], "invalid")
            self.assertIn("local Competitor Analysis page", check["error"])
        with self.assertRaises(ValidationError):
            CompetitorAnalyzeRequest(blog_url="http://127.0.0.1:8001/competitors#", keyword="fall table decor")


class KeywordDetectionTests(unittest.TestCase):
    def test_old_slug_is_not_used_when_title_is_bedding(self):
        page = {
            **BEDDING_PAGE,
            "url": "https://www.example.com/blogs/news/redesigning-home-better-sleep-winnipeg",
        }
        detected = detect_keyword_from_article(page)
        self.assertNotIn("winnipeg", detected["keyword"])
        self.assertNotIn("redesigning", detected["keyword"])
        self.assertIn("bedding", detected["keyword"])


class AverageTests(unittest.TestCase):
    def test_averages_ignore_null_aio_sxo(self):
        rows = [
            {"scores": {"seo": 20, "geo": 50, "aeo": 40, "aio": None, "sxo": None}},
            {"scores": {"seo": 24, "geo": 55, "aeo": 44, "aio": None, "sxo": None}},
            {"scores": {"seo": 26, "geo": 55, "aeo": 46, "aio": None, "sxo": None}},
            {"scores": {"seo": 28, "geo": 60, "aeo": 48, "aio": None, "sxo": None}},
            {"scores": {"seo": 28, "geo": 55, "aeo": 49, "aio": None, "sxo": None}},
        ]
        avg = average_competitor_scores(rows)
        self.assertEqual(avg["seo"], 25.2)
        self.assertEqual(avg["geo"], 55.0)
        self.assertEqual(avg["aeo"], 45.4)
        self.assertIsNone(avg["aio"])
        self.assertIsNone(avg["sxo"])
        self.assertIn("no AIO", avg["reasons"]["aio"])
        self.assertEqual(avg["sample_note"], "Based on 5 of 5 competitors")


class AnalyzerReachTests(unittest.TestCase):
    def test_full_text_reaches_keyword_and_reports(self):
        yours = {**BEDDING_PAGE, "text": BEDDING_TEXT, "h2_headings": ["Cotton vs linen"]}
        competitors = [{
            "title": "Fall table decor",
            "h2_headings": ["Pumpkin centerpieces", "Tablecloth colors"],
            "text": "Pumpkin centerpieces and tablecloth colors for fall table decor. Pumpkin centerpieces on a farm table.",
            "domain": "competitor.example",
            "url": "https://competitor.example/fall",
        }]
        keywords = compare_keywords("fall table decor", yours, competitors)
        self.assertTrue(keywords["table"])
        self.assertTrue(keywords["gaps"]["high-priority"] or keywords["table"])
        read = analyze_readability(BEDDING_TEXT, "en")
        self.assertIsNotNone(read["score"])
        human = humanization_report(BEDDING_TEXT)
        self.assertIsNotNone(human["score"])
        original = originality_report(yours, competitors)
        self.assertIsNotNone(original["score"])
        scores = _score_page("fall table decor", yours)
        self.assertIsInstance(scores["seo"], int)
        self.assertIsInstance(scores["aio"], int)
        self.assertIsInstance(scores["sxo"], int)
        self.assertTrue(scores["reports"]["aio"]["factors"])


class AnalysisFlowTests(unittest.TestCase):
    def _serp(self, query: str) -> SERPAnalysis:
        return SERPAnalysis(
            keyword=query,
            results=[
                SERPResult(
                    title="Fall table decor ideas",
                    url="https://competitor.example/fall-table-decor",
                    snippet="Pumpkin centerpieces and tablecloth colors.",
                )
            ],
        )

    def test_user_keyword_is_exact_serp_query(self):
        with patch("acl_agent.competitors._scrape_url", return_value=dict(BEDDING_PAGE)), patch(
            "acl_agent.competitors.analyze_serp",
            return_value=self._serp("fall table decor"),
        ) as serp, patch("acl_agent.competitors.search_serp", return_value=[]):
            result = analyze_competitors(
                blog_url="https://www.example.com/blogs/news/perfect-bedding-style",
                keyword="fall table decor",
                competitor_urls=[],
                competitor_count=3,
            )
        self.assertEqual(result["serp_query"], "fall table decor")
        self.assertEqual(result["serp_query_source"], "user")
        self.assertEqual(serp.call_args.args[0], "fall table decor")
        self.assertNotIn("winnipeg", result["serp_query"])
        self.assertEqual(result["your_page"]["url"], BEDDING_PAGE["url"])
        self.assertIn("Bedding", result["your_page"]["title"])
        self.assertTrue(result["your_page"]["full_text"])
        self.assertTrue(result["keywords"]["table"])
        self.assertTrue(result["content_gaps"]["table"] or result["content_gaps"].get("status") == "ok")
        self.assertIsNotNone(result["readability"]["score"])
        self.assertIsNotNone(result["humanization"]["score"])
        self.assertIsNotNone(result["originality"]["score"])
        self.assertTrue(result["action_plan"])
        self.assertIsInstance(result["your_scores"]["aio"], int)
        self.assertEqual(result["analysis_mode"], "blog_and_keyword")

    def test_old_keyword_is_not_invented_from_slug(self):
        page = {
            **BEDDING_PAGE,
            "url": "https://www.example.com/blogs/news/redesigning-home-better-sleep-winnipeg",
        }
        with patch("acl_agent.competitors._scrape_url", return_value=page), patch(
            "acl_agent.competitors.analyze_serp",
            side_effect=lambda query, **kwargs: self._serp(query),
        ) as serp, patch("acl_agent.competitors.search_serp", return_value=[]):
            result = analyze_competitors(
                blog_url=page["url"],
                keyword=None,
                competitor_urls=[],
                competitor_count=3,
            )
        self.assertNotIn("winnipeg", result["serp_query"])
        self.assertNotEqual(serp.call_args.args[0], "redesigning home better sleep winnipeg")
        self.assertEqual(result["target_keyword_source"], "auto_detected")

    def test_fetch_failure_is_reported(self):
        with patch("acl_agent.competitors._scrape_url", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                analyze_competitors(
                    blog_url="https://www.example.com/missing",
                    keyword="fall table decor",
                )
        self.assertEqual(str(ctx.exception), "The page could not be fetched.")

    def test_stale_client_id_is_echoed(self):
        with patch("acl_agent.competitors._scrape_url", return_value=dict(BEDDING_PAGE)), patch(
            "acl_agent.competitors.analyze_serp",
            return_value=self._serp("fall table decor"),
        ), patch("acl_agent.competitors.search_serp", return_value=[]):
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                client_analysis_id="run-9",
                competitor_count=3,
            )
        self.assertEqual(result["client_analysis_id"], "run-9")
        self.assertTrue(result["analysis_id"])


if __name__ == "__main__":
    unittest.main()
