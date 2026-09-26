"""GSC diagnosis summary, action merge, and competitor-pipeline isolation."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from acl_agent.analysis_report import action_plan
from datetime import date

from acl_agent.gsc_diagnosis import (
    _on_page_audit,
    adapt_gsc_test_diagnosis,
    build_diagnosis_summary,
    build_index_status,
    diagnose_page_visibility,
    diagnosis_window,
    merge_gsc_actions,
    query_loss_table,
    unavailable_diagnosis,
    year_ago_bounds,
)


YOGURT_TITLE = "Eco-Friendly Yogurt Making"
YOGURT_QUERY = "how to make skyr"
YOGURT_PAGE = {
    "url": "https://example.com/blogs/news/eco-friendly-yogurt-making",
    "title": YOGURT_TITLE,
    "h1": YOGURT_TITLE,
    "h2_headings": ["Ingredients", "Method"],
    "h2_count": 2,
    "word_count": 900,
    "content_type": "Editorial guide",
    "meta_description": "A short yogurt note.",
    "robots": "index,follow",
    "canonical": "https://example.com/blogs/news/eco-friendly-yogurt-making",
    "internal_links": 4,
}


def _yogurt_gsc(**overrides):
    payload = {
        "status": "ok",
        "url": YOGURT_PAGE["url"],
        "impressions": 447,
        "clicks": 9,
        "ctr": 0.0201,
        "position": 18.4,
        "content_type": "Editorial guide",
        "h2_count": 2,
        "word_count": 900,
        "trend": {
            "impressions_delta": -3915,
            "impressions_delta_pct": -89.8,
            "clicks_delta": -40,
        },
        "intent_split": {"informational": 447},
        "keyword_targeting": {
            "target_keyword": "eco-friendly yogurt making",
            "primary_ranking_query": YOGURT_QUERY,
            "mismatch": True,
            "in_title": False,
            "in_h1": False,
            "in_url": False,
        },
        "title": {"value": YOGURT_TITLE, "issues": ["Title does not contain the target keyword or a close variant"], "recommended_action": "Rewrite the title around the query the page actually ranks for."},
        "h1": {"value": YOGURT_TITLE, "issues": ["H1 does not contain the target keyword or a close variant"], "recommended_action": "Align the H1 with the primary ranking query."},
        "queries": [{"query": YOGURT_QUERY, "impressions": 300, "clicks": 6, "intent": "informational"}],
        "recommended_actions": [],
    }
    payload.update(overrides)
    return payload


class DiagnosisSummaryTests(unittest.TestCase):
    def test_yogurt_visibility_drop_outranks_mismatch(self):
        summary = build_diagnosis_summary(
            _yogurt_gsc(),
            target_keyword="eco-friendly yogurt making",
            page=YOGURT_PAGE,
        )
        self.assertEqual(summary["kind"], "visibility_drop")
        self.assertIn("Visibility drop", summary["text"])
        self.assertIn("3915", summary["text"])
        self.assertEqual(summary["confidence"], "high")

    def test_keyword_title_mismatch_when_no_drop(self):
        gsc = _yogurt_gsc(trend={"impressions_delta": -20, "impressions_delta_pct": -4.3})
        summary = build_diagnosis_summary(
            gsc,
            target_keyword="eco-friendly yogurt making",
            page=YOGURT_PAGE,
        )
        self.assertEqual(summary["kind"], "keyword_mismatch")
        self.assertIn(YOGURT_QUERY, summary["text"])
        self.assertIn("eco-friendly yogurt making", summary["text"])

    def test_ctr_gap_uses_intent_baseline(self):
        gsc = _yogurt_gsc(
            trend={},
            keyword_targeting={
                "target_keyword": YOGURT_QUERY,
                "primary_ranking_query": YOGURT_QUERY,
                "mismatch": False,
                "in_title": True,
                "in_h1": True,
                "in_url": True,
            },
            impressions=800,
            ctr=0.02,
            position=2.1,
            intent_split={"informational": 800},
        )
        page = {**YOGURT_PAGE, "title": "How to make skyr", "h1": "How to make skyr"}
        summary = build_diagnosis_summary(gsc, target_keyword=YOGURT_QUERY, page=page)
        self.assertEqual(summary["kind"], "ctr_gap")
        self.assertIn("not compelling", summary["text"])
        self.assertEqual(summary["intent"], "informational")

    def test_thin_visibility_vs_competitor_depth(self):
        gsc = _yogurt_gsc(
            trend={},
            keyword_targeting={
                "target_keyword": YOGURT_QUERY,
                "primary_ranking_query": YOGURT_QUERY,
                "mismatch": False,
                "in_title": True,
                "in_h1": True,
                "in_url": True,
            },
            impressions=150,
            ctr=0.09,
            position=8,
        )
        page = {**YOGURT_PAGE, "word_count": 400, "title": "How to make skyr", "h1": "How to make skyr"}
        summary = build_diagnosis_summary(
            gsc,
            target_keyword=YOGURT_QUERY,
            page=page,
            competitor_avg_words=2200,
        )
        self.assertEqual(summary["kind"], "thin_visibility")
        self.assertIn("content depth", summary["text"])

    def test_content_gap_fallback(self):
        gsc = unavailable_diagnosis("Search Console is not connected.")
        summary = build_diagnosis_summary(
            gsc,
            target_keyword="eco-friendly yogurt making",
            page=YOGURT_PAGE,
            content_gaps={"table": [{"missing_topic": "How to make skyr at home"}]},
        )
        self.assertEqual(summary["kind"], "content_gaps")
        self.assertIn("How to make skyr at home", summary["text"])

    def test_low_sample_softens_wording(self):
        gsc = _yogurt_gsc(impressions=40, trend={"impressions_delta": -80, "impressions_delta_pct": -66.7})
        summary = build_diagnosis_summary(gsc, target_keyword="eco-friendly yogurt making", page=YOGURT_PAGE)
        self.assertEqual(summary["confidence"], "low")
        self.assertTrue(summary["text"].lower().startswith("possible"))

    def test_seasonal_caveat_only_for_travel(self):
        travel_page = {**YOGURT_PAGE, "url": "https://example.com/tourism/lempuyang-temple-bali"}
        travel = build_diagnosis_summary(
            _yogurt_gsc(url=travel_page["url"]),
            target_keyword="lempuyang temple bali",
            page=travel_page,
        )
        yogurt = build_diagnosis_summary(
            _yogurt_gsc(),
            target_keyword="eco-friendly yogurt making",
            page=YOGURT_PAGE,
        )
        self.assertTrue(travel["seasonal_caveat"])
        self.assertIn("Seasonal/travel", travel["text"])
        self.assertFalse(yogurt["seasonal_caveat"])
        self.assertNotIn("Seasonal/travel", yogurt["text"])
        self.assertEqual(travel["confidence"], "medium")
        self.assertEqual(yogurt["confidence"], "high")

    def test_seasonal_drop_without_year_ago_is_medium_confidence(self):
        travel_page = {**YOGURT_PAGE, "url": "https://example.com/tourism/lempuyang-temple-bali"}
        gsc = _yogurt_gsc(url=travel_page["url"], comparisons={"year_ago": {"status": "unavailable"}})
        summary = build_diagnosis_summary(
            gsc,
            target_keyword="lempuyang temple bali",
            page=travel_page,
        )
        self.assertEqual(summary["kind"], "visibility_drop")
        self.assertIsNone((gsc.get("comparisons") or {}).get("year_ago", {}).get("impressions_delta_pct"))
        self.assertEqual(summary["confidence"], "medium")
        self.assertNotEqual(summary["confidence"], "high")
        self.assertIn("Seasonal/travel", summary["text"])


class ActionMergeTests(unittest.TestCase):
    def test_duplicate_title_and_h1_actions_merge(self):
        on_page = action_plan(
            {**YOGURT_PAGE, "extract_ok": True, "schema_types": []},
            {"seo": 40},
            {"gaps": {"high-priority": []}},
            {"table": []},
            {"score": 70},
        )
        on_page.insert(0, {
            "priority": "High Priority",
            "category": "Title",
            "issue": "Title does not mention the keyword",
            "recommended_action": "Heuristic: add the keyword to the title.",
            "estimated_impact": "On-page",
            "estimated_effort": "Low",
            "related_gap": "title",
        })
        on_page.insert(1, {
            "priority": "High Priority",
            "category": "H1",
            "issue": "H1 missing keyword",
            "recommended_action": "Heuristic: add the keyword to the H1.",
            "estimated_impact": "On-page",
            "estimated_effort": "Low",
            "related_gap": "h1",
        })
        gsc = _yogurt_gsc(recommended_actions=[
            {
                "priority": "Critical",
                "category": "Title",
                "issue": "Primary ranking query differs from the target keyword used in the title/H1",
                "recommended_action": "Rewrite the title around “how to make skyr”.",
                "estimated_impact": "GSC",
                "estimated_effort": "Low",
                "related_gap": "how to make skyr",
                "source": "gsc",
            },
            {
                "priority": "High Priority",
                "category": "H1",
                "issue": "H1 does not contain the target keyword or a close variant",
                "recommended_action": "Align the H1 with how to make skyr.",
                "estimated_impact": "GSC",
                "estimated_effort": "Low",
                "related_gap": "h1",
                "source": "gsc",
            },
        ])
        merged = merge_gsc_actions(on_page, gsc)
        title_items = [item for item in merged if "title" in f"{item.get('category', '')} {item.get('issue', '')}".lower()]
        h1_items = [item for item in merged if item.get("category") == "H1"]
        self.assertEqual(len(title_items), 1)
        self.assertEqual(len(h1_items), 1)
        self.assertIn("how to make skyr", title_items[0]["recommended_action"])
        self.assertEqual(title_items[0].get("source"), "gsc")


class DiagnoseFunctionTests(unittest.TestCase):
    def test_unavailable_when_gsc_test_raises(self):
        with patch(
            "acl_agent.gsc_diagnosis.run_gsc_test_diagnosis",
            side_effect=RuntimeError("token expired"),
        ):
            report = diagnose_page_visibility(
                YOGURT_PAGE["url"],
                days=180,
                page=YOGURT_PAGE,
                target_keyword="eco-friendly yogurt making",
            )
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("token expired", report["reason"])
        self.assertEqual(report["title"]["value"], YOGURT_TITLE)

    def test_adapts_gsc_test_yogurt_shape(self):
        raw = {
            "verdict": "Visibility problem",
            "why": ["The page only earned 447 impressions."],
            "totals": {"clicks": 0, "impressions": 447, "ctr": 0.0, "position": 2.56},
            "targeting": {
                "primary_query": "how to make skyr yogurt",
                "target_query": "how to make skyr yogurt",
                "primary_in_title": False,
                "primary_in_h1": False,
                "primary_in_url": False,
            },
            "query_analysis": {
                "top": [
                    {
                        "query": "how to make skyr yogurt",
                        "clicks": 0,
                        "impressions": 24,
                        "ctr": 0.0,
                        "position": 14,
                    }
                ],
                "intent_impressions": {"informational": 447},
                "branded_impressions": 0,
            },
            "trend": {
                "status": "declining",
                "note": "Period comparisons can reflect seasonality (especially travel content).",
                "deltas": {
                    "clicks": -4,
                    "impressions": -3915,
                    "impressions_ratio": -3915 / 4362,
                    "position": 0.2,
                },
                "previous": {"impressions": 4362},
            },
            "recommendations": [
                {
                    "id": "rewrite_title_primary",
                    "title": "Rewrite the title around the primary query",
                    "reason": 'Include "how to make skyr yogurt" near the start of the title.',
                    "action": "Rewrite the title around the primary query",
                    "detail": 'Include "how to make skyr yogurt" near the start of the title.',
                    "priority": "High",
                    "effort": "low",
                    "queries": ["how to make skyr yogurt"],
                }
            ],
            "content": {"issues": [], "off_topic_headings": ["Shop cotton sheets"]},
            "links": {"internal_count": 4, "issues": []},
            "indexing_issues": [],
            "page": {"title": YOGURT_TITLE, "h1": [YOGURT_TITLE], "word_count": 900},
            "gsc": {
                "days": 180,
                "start_date": "2026-03-26",
                "end_date": "2026-09-21",
                "previous_start_date": "2025-09-26",
                "previous_end_date": "2026-03-25",
            },
            "previous_queries": [
                {"query": "how to make skyr yogurt", "clicks": 8, "impressions": 400, "ctr": 0.02, "position": 8.0},
                {"query": "skyr recipe", "clicks": 3, "impressions": 120, "ctr": 0.025, "position": 12.0},
            ],
            "year_ago_totals": {"clicks": 12, "impressions": 500, "ctr": 0.024, "position": 9.0},
            "year_ago_start_date": "2025-03-26",
            "year_ago_end_date": "2025-09-21",
            "confidence": {"level": "low"},
        }
        report = adapt_gsc_test_diagnosis(
            raw,
            blog_url=YOGURT_PAGE["url"],
            days=180,
            page=YOGURT_PAGE,
            target_keyword="eco-friendly yogurt making",
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["source"], "gsc-test")
        self.assertEqual(report["impressions"], 447)
        self.assertEqual(report["trend"]["impressions_delta"], -3915)
        self.assertLess(report["trend"]["impressions_delta_pct"], -80)
        self.assertEqual(report["keyword_targeting"]["primary_ranking_query"], "how to make skyr yogurt")
        self.assertTrue(report["keyword_targeting"]["mismatch"])
        self.assertEqual(report["recommended_actions"][0]["category"], "Title")
        self.assertEqual(report["recommended_actions"][0]["source"], "gsc")
        self.assertEqual(report["comparisons"]["previous"]["impressions"], 4362)
        self.assertEqual(report["comparisons"]["year_ago"]["impressions"], 500)
        self.assertEqual(report["query_losses"]["items"][0]["query"], "how to make skyr yogurt")
        self.assertEqual(report["query_losses"]["items"][0]["kind"], "position_fell")
        self.assertEqual(report["index_status"]["source"], "robots_only")
        self.assertIsNone(report["index_status"]["indexed"])
        self.assertEqual(report["index_status"]["label"], "Inspection unavailable")
        self.assertIn("impressions", report["index_status"]["impressions_hint"].lower())

    def test_url_inspection_submitted_and_indexed(self):
        raw = {
            "verdict": "Visibility problem",
            "why": [],
            "totals": {"clicks": 0, "impressions": 447, "ctr": 0.0, "position": 2.56},
            "targeting": {"primary_query": "how to make skyr yogurt"},
            "query_analysis": {"top": [], "intent_impressions": {}, "branded_impressions": 0},
            "trend": {"status": "stable", "deltas": {}, "previous": {}},
            "recommendations": [],
            "content": {"issues": [], "off_topic_headings": []},
            "links": {"internal_count": 4, "issues": []},
            "indexing_issues": [],
            "page": {"title": YOGURT_TITLE, "h1": [YOGURT_TITLE], "word_count": 900, "robots": "index,follow"},
            "gsc": {
                "days": 180,
                "inspection": {
                    "available": True,
                    "coverage_state": "Submitted and indexed",
                    "indexing_state": "INDEXING_ALLOWED",
                    "last_crawl": "2026-09-20T08:00:00Z",
                    "verdict": "PASS",
                },
            },
        }
        report = adapt_gsc_test_diagnosis(
            raw,
            blog_url=YOGURT_PAGE["url"],
            days=180,
            page=YOGURT_PAGE,
            target_keyword="eco-friendly yogurt making",
        )
        self.assertTrue(report["index_status"]["indexed"])
        self.assertEqual(report["index_status"]["label"], "Indexed")
        self.assertEqual(report["index_status"]["source"], "url_inspection")
        self.assertEqual(report["index_status"]["coverage_state"], "Submitted and indexed")
        self.assertEqual(report["indexing"]["coverage_state"], "Submitted and indexed")
        self.assertEqual(report["indexing"]["source"], "url_inspection")

    def test_url_inspection_not_indexed(self):
        status = build_index_status({
            "impressions": 0,
            "indexing": {
                "robots": "index,follow",
                "status": "indexable",
                "inspection": {
                    "available": True,
                    "coverage_state": "Crawled - currently not indexed",
                    "last_crawl": "2026-09-18T12:00:00Z",
                },
            },
        })
        self.assertFalse(status["indexed"])
        self.assertEqual(status["label"], "Not indexed")
        self.assertEqual(status["source"], "url_inspection")

    def test_robots_only_does_not_claim_indexed(self):
        status = build_index_status({
            "impressions": 120,
            "indexing": {"robots": "index,follow", "status": "indexable"},
        })
        self.assertIsNone(status["indexed"])
        self.assertEqual(status["source"], "robots_only")
        self.assertEqual(status["label"], "Inspection unavailable")
        self.assertIn("not a coverage-state check", status["impressions_hint"])

    def test_ok_when_metrics_supplied(self):
        metrics = {
            "clicks": 9,
            "impressions": 447,
            "ctr": 0.02,
            "position": 18.4,
            "trend": {"impressions_delta": -3915, "impressions_delta_pct": -89.8},
            "queries": [{"query": YOGURT_QUERY, "clicks": 6, "impressions": 300, "ctr": 0.02, "position": 12.0}],
            "site_queries": [],
        }
        report = diagnose_page_visibility(
            YOGURT_PAGE["url"],
            days=180,
            page=YOGURT_PAGE,
            target_keyword="eco-friendly yogurt making",
            gsc_metrics=metrics,
        )
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["impressions"], 447)
        self.assertTrue(report["keyword_targeting"]["mismatch"])
        self.assertEqual(report["keyword_targeting"]["primary_ranking_query"], YOGURT_QUERY)


class DiagnosisWindowTests(unittest.TestCase):
    def test_allowed_months_map_to_days(self):
        self.assertEqual(diagnosis_window(1), {"months": 1, "days": 30, "label": "Last 1 month"})
        self.assertEqual(diagnosis_window(3)["days"], 90)
        self.assertEqual(diagnosis_window(6)["days"], 180)
        self.assertEqual(diagnosis_window(12)["days"], 365)

    def test_invalid_months_snap_to_nearest_allowed(self):
        self.assertEqual(diagnosis_window(2)["months"], 1)
        self.assertEqual(diagnosis_window(4)["months"], 3)
        self.assertEqual(diagnosis_window(None)["months"], 6)
        self.assertEqual(diagnosis_window("nope")["months"], 6)

    def test_visibility_drop_names_the_selected_window(self):
        gsc = _yogurt_gsc(period={"months": 3, "days": 90, "label": "Last 3 months"})
        summary = build_diagnosis_summary(gsc, target_keyword=YOGURT_QUERY, page=YOGURT_PAGE)
        self.assertEqual(summary["kind"], "visibility_drop")
        self.assertIn("last 3 months", summary["text"].lower())

    def test_year_ago_flat_is_called_seasonal_not_a_collapse(self):
        gsc = _yogurt_gsc(
            period={"months": 3, "days": 90, "label": "Last 3 months"},
            comparisons={"year_ago": {"status": "ok", "impressions_delta_pct": 4.0}},
        )
        summary = build_diagnosis_summary(gsc, target_keyword=YOGURT_QUERY, page=YOGURT_PAGE)
        self.assertEqual(summary["kind"], "seasonal_swing")
        self.assertIn("year-ago", summary["text"].lower())

    def test_year_ago_bounds_reject_16_month_limit(self):
        bounds = year_ago_bounds("2025-03-26", "2025-09-21", as_of=date(2026, 9, 25))
        self.assertEqual(bounds["status"], "unavailable")
        self.assertIn("16 months", bounds["reason"])
        short = year_ago_bounds("2026-06-26", "2026-09-21", as_of=date(2026, 9, 25))
        self.assertEqual(short["status"], "ok")

    def test_off_topic_heading_needs_zero_overlap_and_low_relevance(self):
        audit = _on_page_audit(
            "https://example.com/dishes",
            {
                "title": "15 dishes for a crowd",
                "h1": "15 dishes for a crowd",
                "h2_headings": [
                    "How to plate the dishes",
                    "Filipino Lechon for a party",
                    "Tips",
                ],
            },
            "15 dishes for a crowd",
        )
        self.assertNotIn("How to plate the dishes", audit["off_topic_headings"])
        self.assertNotIn("Tips", audit["off_topic_headings"])
        self.assertIn("Filipino Lechon for a party", audit["off_topic_headings"])

    def test_query_loss_table_ranks_and_labels(self):
        report = query_loss_table(
            [
                {"query": "reusable bags", "impressions": 40, "clicks": 1, "ctr": 0.02, "position": 18},
                {"query": "new query", "impressions": 5, "clicks": 0, "ctr": 0, "position": 20},
            ],
            [
                {"query": "reusable bags", "impressions": 200, "clicks": 8, "ctr": 0.04, "position": 8},
                {"query": "produce bags", "impressions": 80, "clicks": 2, "ctr": 0.03, "position": 10},
            ],
        )
        self.assertEqual(report["status"], "ok")
        kinds = {item["query"]: item["kind"] for item in report["items"]}
        self.assertEqual(kinds["reusable bags"], "position_fell")
        self.assertEqual(kinds["produce bags"], "vanished")
        self.assertNotIn("new query", kinds)
        self.assertLess(report["items"][0]["impressions_delta"], 0)


if __name__ == "__main__":
    unittest.main()
