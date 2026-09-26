"""Grounded LLM recommendations for Competitor Analysis."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from acl_agent.analysis_llm import (
    AnalysisLlmAdvice,
    LlmCopyDraft,
    build_analysis_llm_facts,
    enrich_analysis_with_llm,
)


class AnalysisLlmTests(unittest.TestCase):
    def test_facts_keep_measured_gsc_and_omit_volume(self):
        facts = build_analysis_llm_facts(
            target_keyword="christmas dinner ideas",
            page={"title": "Best Christmas Dinner Ideas", "h1": "15 Dishes", "meta_description": "A short note."},
            gsc={
                "status": "ok",
                "clicks": 80,
                "impressions": 900,
                "position": 8.8,
                "keyword_targeting": {"primary_ranking_query": "how to make christmas dinner for a crowd"},
                "queries": [{"query": "how to make christmas dinner for a crowd", "impressions": 400, "clicks": 20, "position": 8.8}],
            },
            index_status={"label": "Indexed", "source": "url_inspection", "indexed": True, "coverage_state": "Submitted and indexed"},
            verdict={"observed": ["Impressions changed -82.3% versus the previous period."]},
            action_plan=[{"category": "Title", "issue": "Missing ranking query", "recommended_action": "Put the ranking query in the title."}],
            what_to_add={"table": [{"topic": "Make-ahead sides"}]},
        )
        self.assertEqual(facts["gsc"]["impressions"], 900)
        self.assertEqual(facts["ranking_query"], "how to make christmas dinner for a crowd")
        self.assertNotIn("search volume", str(facts["gsc"]))
        self.assertIn("search volume", facts["unavailable_metrics"])

    def test_success_attaches_recommendation_drafts(self):
        advice = AnalysisLlmAdvice(
            editor_summary="Rewrite the title around the ranking query Search Console already shows.",
            title=LlmCopyDraft(
                current="Best Christmas Dinner Ideas",
                recommended="How to Make Christmas Dinner for a Crowd",
                why="Title does not mention the ranking query.",
            ),
            h1=LlmCopyDraft(current="15 Dishes", recommended="How to Make Christmas Dinner for a Crowd", why="H1 is generic."),
            meta_description=LlmCopyDraft(current="A short note.", recommended="A make-ahead plan for Christmas dinner for a crowd.", why="Meta is thin."),
            next_steps=["Put the ranking query in the title.", "Add a make-ahead sides section."],
        )
        with patch("acl_agent.analysis_llm.call_model_for_json", return_value=advice):
            report = enrich_analysis_with_llm({"target_keyword": "christmas dinner ideas"})
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["label"], "Recommendation")
        self.assertIn("ranking query", report["editor_summary"])
        self.assertEqual(report["title"]["recommended"], "How to Make Christmas Dinner for a Crowd")

    def test_model_failure_does_not_break_analysis(self):
        with patch("acl_agent.analysis_llm.call_model_for_json", side_effect=RuntimeError("quota")):
            report = enrich_analysis_with_llm({"target_keyword": "x"})
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("quota", report["reason"])
        self.assertEqual(report["next_steps"], [])
