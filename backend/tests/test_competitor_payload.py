"""Regression tests for competitor analysis request, SERP query, and reports."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from urllib.parse import urlparse

from pydantic import ValidationError

from acl_agent.analysis_input import (
    average_competitor_scores,
    detect_keyword_from_article,
    validate_blog_url,
)
from acl_agent.analysis_report import humanization_report, originality_report
from acl_agent.api import CompetitorAnalyzeRequest
from acl_agent.competitors import analyze_competitors, _score_page
from acl_agent.keywords import compare_keywords
from acl_agent.gsc_diagnosis import unavailable_diagnosis
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


COMPETITOR_URL = "https://competitor.example/fall-table-decor"
DECOR_TEXT = (
    "Fall table decor ideas for autumn dinners. "
    "Use pumpkin centerpieces, a rust tablecloth, and linen napkins for fall table decor. "
    "Layer candles and dried leaves along the table runner. "
) * 6
DECOR_PAGE = {
    **BEDDING_PAGE,
    "url": COMPETITOR_URL,
    "domain": "competitor.example",
    "title": "Fall Table Decor Ideas",
    "h1": "Fall Table Decor Ideas",
    "h1_headings": ["Fall Table Decor Ideas"],
    "h2_headings": ["Pumpkin centerpieces", "Fall tablecloth colors"],
    "text": DECOR_TEXT,
    "full_text": DECOR_TEXT,
    "source_markdown": "# Fall Table Decor Ideas\n\n" + DECOR_TEXT,
    "article_html": DECOR_TEXT,
}


def _scrape_blog_or_decor(url: str) -> dict:
    return dict(DECOR_PAGE) if "competitor.example" in url else dict(BEDDING_PAGE)


class _SkipAnalysisLlmMixin:
    def setUp(self):
        self._llm_patch = patch(
            "acl_agent.competitors.enrich_analysis_with_llm",
            return_value={"status": "skipped", "reason": "unit test"},
        )
        self._llm_patch.start()

    def tearDown(self):
        self._llm_patch.stop()


class AnalysisFlowTests(_SkipAnalysisLlmMixin, unittest.TestCase):
    def test_user_keyword_is_used_and_live_search_never_runs(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=_scrape_blog_or_decor), patch(
            "acl_agent.competitors.search_serp"
        ) as search, patch("acl_agent.auto_brief.search_serp") as brief_search:
            result = analyze_competitors(
                blog_url="https://www.example.com/blogs/news/perfect-bedding-style",
                keyword="fall table decor",
                competitor_urls=[COMPETITOR_URL],
            )
        search.assert_not_called()
        brief_search.assert_not_called()
        self.assertEqual(result["serp_query"], "fall table decor")
        self.assertEqual(result["serp_query_source"], "user")
        self.assertEqual(result["target_keyword_source"], "user")
        self.assertEqual([row["url"] for row in result["competitors"]], [COMPETITOR_URL])
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

    def test_missing_keyword_is_rejected_not_detected(self):
        with patch("acl_agent.competitors._scrape_url", return_value=dict(BEDDING_PAGE)) as scrape:
            with self.assertRaises(ValueError) as ctx:
                analyze_competitors(
                    blog_url=BEDDING_PAGE["url"],
                    keyword=None,
                    competitor_urls=[COMPETITOR_URL],
                )
        self.assertEqual(str(ctx.exception), "Enter a target keyword.")
        scrape.assert_not_called()

    def test_no_competitor_urls_audits_page_only(self):
        with patch("acl_agent.competitors._scrape_url", return_value=dict(BEDDING_PAGE)), patch(
            "acl_agent.competitors.search_serp"
        ) as search:
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                competitor_urls=[],
            )
        search.assert_not_called()
        self.assertEqual(result["competitors"], [])
        self.assertIn("audit of your page only", result["serp_warning"])
        self.assertIsInstance(result["your_scores"]["seo"], int)

    def test_keyword_alone_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            analyze_competitors(keyword="fall table decor", competitor_urls=[])
        self.assertEqual(str(ctx.exception), "Enter a blog URL or at least one competitor URL.")

    def test_fetch_failure_is_reported(self):
        with patch("acl_agent.competitors._scrape_url", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                analyze_competitors(
                    blog_url="https://www.example.com/missing",
                    keyword="fall table decor",
                )
        self.assertEqual(str(ctx.exception), "The page could not be fetched.")

    def test_stale_client_id_is_echoed(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=_scrape_blog_or_decor):
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                competitor_urls=[COMPETITOR_URL],
                client_analysis_id="run-9",
            )
        self.assertEqual(result["client_analysis_id"], "run-9")
        self.assertTrue(result["analysis_id"])


class CompetitorUrlIsolationTests(_SkipAnalysisLlmMixin, unittest.TestCase):
    HOODIE_URLS = [
        "https://blackberrys.com/oversized-hoodie",
        "https://nobero.com/hoodie-blog",
        "https://veirdo.in/hoodie",
    ]
    TEMPLE_BLOG = "https://www.example.com/blogs/news/lempuyang-temple-bali"
    TEMPLE_COMPS = [
        "https://bali.example/lempuyang-temple-gate",
        "https://travel.example/pura-lempuyang",
        "https://guide.example/bali-temples",
    ]

    def _page(self, url: str, title: str, text: str) -> dict:
        return {
            **BEDDING_PAGE,
            "url": url,
            "domain": urlparse(url).netloc,
            "title": title,
            "h1": title,
            "h1_headings": [title],
            "text": text,
            "full_text": text,
            "source_markdown": f"# {title}\n\n{text}",
            "article_html": text,
        }

    def _scrape(self, url: str):
        temple_text = (
            "Lempuyang Temple Bali Gate of Heaven travel guide. "
            "Climb the stairs to Pura Lempuyang and photograph the split gate. "
        ) * 8
        hoodie_text = (
            "Men oversized hoodie streetwear outfits and cotton fabric. "
            "Blackberrys and Nobero sell oversized hoodies online. "
        ) * 8
        if any(host in url for host in ("blackberrys", "nobero", "veirdo", "hoodie")):
            return self._page(url, "Oversized hoodie outfits", hoodie_text)
        return self._page(url, "Lempuyang Temple Bali Gate of Heaven", temple_text)

    def test_second_call_does_not_keep_first_call_competitor_urls(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=self._scrape):
            first = analyze_competitors(
                blog_url="https://www.example.com/blogs/news/hoodie-outfits",
                keyword="style mens oversized hoodies",
                competitor_urls=list(self.HOODIE_URLS),
            )
            second = analyze_competitors(
                blog_url=self.TEMPLE_BLOG,
                keyword="lempuyang temple bali gate heaven travel",
                competitor_urls=list(self.TEMPLE_COMPS),
            )
        self.assertTrue(any("blackberrys" in url or "nobero" in url for url in first["competitor_urls"]))
        second_urls = second["competitor_urls"] + [row["url"] for row in second["competitors"]]
        for banned in self.HOODIE_URLS:
            self.assertNotIn(banned, second_urls)
        self.assertEqual(sorted(second["competitor_urls"]), sorted(self.TEMPLE_COMPS))

    def test_off_topic_manual_urls_are_excluded(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=self._scrape):
            result = analyze_competitors(
                blog_url=self.TEMPLE_BLOG,
                keyword="lempuyang temple bali gate heaven travel",
                competitor_urls=list(self.HOODIE_URLS) + self.TEMPLE_COMPS[:1],
            )
        result_urls = result["competitor_urls"] + [row["url"] for row in result["competitors"]]
        for banned in self.HOODIE_URLS:
            self.assertNotIn(banned, result_urls)
        self.assertTrue(result["excluded_competitor_urls"])
        self.assertIn("don't appear to match the target keyword", result["serp_warning"])
        self.assertTrue(any("lempuyang" in (row.get("url") or "") or "bali" in (row.get("url") or "") for row in result["competitors"]))


class CompetitorStreamIsolationTests(unittest.TestCase):
    def test_sequential_http_requests_do_not_share_competitor_urls(self):
        from fastapi.testclient import TestClient

        from acl_agent.api import app, require_auth

        captured: list[list[str]] = []

        def fake_analyze(**kwargs):
            captured.append(list(kwargs.get("competitor_urls") or []))
            return {
                "analysis_id": "iso",
                "client_analysis_id": kwargs.get("client_analysis_id"),
                "competitor_urls": list(kwargs.get("competitor_urls") or []),
                "excluded_competitor_urls": [],
                "competitors": [{"url": url, "domain": url} for url in (kwargs.get("competitor_urls") or [])],
                "serp": {"keyword": kwargs.get("keyword"), "related_queries": [], "common_headings": []},
                "your_page": {"url": kwargs.get("blog_url"), "title": "page"},
            }

        app.dependency_overrides[require_auth] = lambda: {"id": "1", "name": "tester"}
        try:
            with patch("acl_agent.api.analyze_competitors", side_effect=fake_analyze):
                with TestClient(app) as client:
                    headers = {"Authorization": "Bearer test-token"}
                    first = client.post(
                        "/analyze-competitors-stream",
                        json={
                            "blog_url": "https://www.example.com/blogs/news/hoodie-outfits",
                            "keyword": "style mens oversized hoodies",
                            "competitor_urls": [
                                "https://blackberrys.com/hoodie",
                                "https://nobero.com/hoodie",
                            ],
                            "client_analysis_id": "1",
                        },
                        headers=headers,
                    )
                    second = client.post(
                        "/analyze-competitors-stream",
                        json={
                            "blog_url": "https://www.example.com/blogs/news/lempuyang-temple-bali",
                            "keyword": "lempuyang temple bali gate heaven travel",
                            "competitor_urls": [],
                            "client_analysis_id": "2",
                        },
                        headers=headers,
                    )
        finally:
            app.dependency_overrides.pop(require_auth, None)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0], ["https://blackberrys.com/hoodie", "https://nobero.com/hoodie"])
        self.assertEqual(captured[1], [])
        self.assertNotIn("blackberrys.com", " ".join(captured[1]))

    def test_request_without_keyword_is_rejected(self):
        from fastapi.testclient import TestClient

        from acl_agent.api import app, require_auth

        app.dependency_overrides[require_auth] = lambda: {"id": "1", "name": "tester"}
        try:
            with patch("acl_agent.api.analyze_competitors") as analyze, TestClient(app) as client:
                response = client.post(
                    "/analyze-competitors-stream",
                    json={"blog_url": "https://www.example.com/blogs/news/hoodie-outfits"},
                    headers={"Authorization": "Bearer test-token"},
                )
        finally:
            app.dependency_overrides.pop(require_auth, None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["message"], "Enter a target keyword.")
        analyze.assert_not_called()


class GscPipelineIsolationTests(_SkipAnalysisLlmMixin, unittest.TestCase):
    def test_analyze_competitors_survives_gsc_raise(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=_scrape_blog_or_decor), patch(
            "acl_agent.competitors.diagnose_page_visibility",
            side_effect=RuntimeError("GSC down"),
        ):
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                competitor_urls=[COMPETITOR_URL],
            )
        self.assertEqual(result["gsc_diagnosis"]["status"], "unavailable")
        self.assertTrue(result["gsc_diagnosis"]["reason"])
        self.assertTrue(result["diagnosis_summary"]["text"])
        self.assertTrue(result["keywords"]["table"] or result["content_gaps"])
        self.assertIn("verified traffic", result["unavailable_metrics"])
        self.assertIsInstance(result["your_scores"]["seo"], int)

    def test_analyze_competitors_survives_gsc_unavailable(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=_scrape_blog_or_decor), patch(
            "acl_agent.competitors.diagnose_page_visibility",
            return_value=unavailable_diagnosis("Search Console is not connected.", BEDDING_PAGE["url"]),
        ):
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                competitor_urls=[COMPETITOR_URL],
            )
        self.assertEqual(result["gsc_diagnosis"]["status"], "unavailable")
        self.assertEqual(result["diagnosis_summary"]["kind"], "content_gaps")
        self.assertIn("verified traffic", result["unavailable_metrics"])
        self.assertIsNone(result["keyword_mismatch"])

    def test_months_are_passed_to_search_console(self):
        with patch("acl_agent.competitors._scrape_url", side_effect=_scrape_blog_or_decor), patch(
            "acl_agent.competitors.diagnose_page_visibility",
            return_value=unavailable_diagnosis("Search Console is not connected.", BEDDING_PAGE["url"], days=90),
        ) as diagnose:
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                competitor_urls=[COMPETITOR_URL],
                months=3,
            )
        diagnose.assert_called_once()
        self.assertEqual(diagnose.call_args.kwargs["days"], 90)
        self.assertEqual(result["diagnosis_window"], {"months": 3, "days": 90, "label": "Last 3 months"})
        self.assertEqual(result["gsc_diagnosis"]["period"]["months"], 3)

    def test_keyword_mismatch_flags_keyword_dependent_actions(self):
        diagnosis = unavailable_diagnosis("", BEDDING_PAGE["url"])
        diagnosis.update({
            "status": "ok",
            "keyword_targeting": {
                "target_keyword": "fall table decor",
                "primary_ranking_query": "linen duvet cover",
                "mismatch": True,
            },
        })
        with patch("acl_agent.competitors._scrape_url", side_effect=_scrape_blog_or_decor), patch(
            "acl_agent.competitors.diagnose_page_visibility",
            return_value=diagnosis,
        ):
            result = analyze_competitors(
                blog_url=BEDDING_PAGE["url"],
                keyword="fall table decor",
                competitor_urls=[COMPETITOR_URL],
            )
        self.assertEqual(result["keyword_mismatch"], {
            "target_keyword": "fall table decor",
            "search_console_query": "linen duvet cover",
        })
        self.assertTrue(result["keywords"]["depends_on_keyword"])
        self.assertTrue(result["content_gaps"]["depends_on_keyword"])
        for item in result["action_plan"]:
            if item.get("category") in {"Keyword", "Content"}:
                self.assertTrue(item.get("depends_on_keyword"))
            else:
                self.assertFalse(item.get("depends_on_keyword"))


if __name__ == "__main__":
    unittest.main()
