"""One grounded LLM pass for Competitor Analysis recommendations.

Uses measured extract + Search Console facts only. Never invents
volume, DA, backlinks, CWV, or click forecasts.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from acl_agent.config import logger
from acl_agent.llm import call_model_for_json

_BANNED_METRIC_PHRASES = (
    "domain authority",
    "search volume",
    "keyword difficulty",
    "core web vitals",
    "referring domains",
    "click forecast",
    "estimated clicks",
)

SYSTEM_PROMPT = """You write editor recommendations for a Competitor Analysis report.
Use only the facts JSON. Do not invent clicks, impressions, position, CTR,
search volume, keyword difficulty, domain authority, backlinks, Core Web Vitals,
or click forecasts. Do not invent competitor URLs or internal-link destinations.
If a number is missing, write Data unavailable — do not guess.
Every rewrite is a Recommendation, not a measured result.
When a ranking_query is present, the recommended title and H1 must include it.
If index_status.source is not url_inspection, do not say the URL is indexed.
Return JSON only."""


class LlmCopyDraft(BaseModel):
    current: str = ""
    recommended: str = Field(default="", max_length=220)
    why: str = Field(default="", max_length=400)


class AnalysisLlmAdvice(BaseModel):
    editor_summary: str = Field(min_length=20, max_length=700)
    title: LlmCopyDraft = Field(default_factory=LlmCopyDraft)
    h1: LlmCopyDraft = Field(default_factory=LlmCopyDraft)
    meta_description: LlmCopyDraft = Field(default_factory=LlmCopyDraft)
    next_steps: list[str] = Field(default_factory=list, max_length=5)


def unavailable_llm_advice(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "label": "Recommendation",
        "source": "llm",
        "editor_summary": "",
        "title": {},
        "h1": {},
        "meta_description": {},
        "next_steps": [],
    }


def build_analysis_llm_facts(
    *,
    target_keyword: str = "",
    page: Optional[dict[str, Any]] = None,
    gsc: Optional[dict[str, Any]] = None,
    index_status: Optional[dict[str, Any]] = None,
    verdict: Optional[dict[str, Any]] = None,
    action_plan: Optional[list[dict[str, Any]]] = None,
    what_to_add: Optional[dict[str, Any]] = None,
    keyword_mismatch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Subset of measured fields the model is allowed to see."""
    page = page or {}
    gsc = gsc or {}
    targeting = gsc.get("keyword_targeting") or {}
    queries = []
    for row in (gsc.get("queries") or [])[:8]:
        queries.append({
            "query": row.get("query"),
            "impressions": row.get("impressions"),
            "clicks": row.get("clicks"),
            "position": row.get("position"),
        })
    actions = []
    for item in (action_plan or [])[:6]:
        actions.append({
            "category": item.get("category"),
            "issue": item.get("issue"),
            "recommended_action": item.get("recommended_action"),
        })
    topics = [row.get("topic") for row in ((what_to_add or {}).get("table") or [])[:8] if row.get("topic")]
    return {
        "target_keyword": target_keyword,
        "ranking_query": targeting.get("primary_ranking_query") or "",
        "keyword_mismatch": bool(keyword_mismatch),
        "title": page.get("title") or "",
        "h1": page.get("h1") or "",
        "meta_description": page.get("meta_description") or "",
        "h2": list(page.get("h2_headings") or page.get("h2") or [])[:12],
        "gsc": {
            "status": gsc.get("status"),
            "clicks": gsc.get("clicks"),
            "impressions": gsc.get("impressions"),
            "ctr": gsc.get("ctr"),
            "position": gsc.get("position"),
            "impressions_delta_pct": (gsc.get("trend") or {}).get("impressions_delta_pct"),
        },
        "index_status": {
            "label": (index_status or {}).get("label"),
            "source": (index_status or {}).get("source"),
            "coverage_state": (index_status or {}).get("coverage_state"),
            "indexed": (index_status or {}).get("indexed"),
        },
        "observed": list((verdict or {}).get("observed") or [])[:6],
        "actions": actions,
        "topics_to_add": topics,
        "queries": queries,
        "unavailable_metrics": [
            "search volume",
            "keyword difficulty",
            "domain authority",
            "backlinks",
            "Core Web Vitals",
        ],
    }


def _reject_invented_metrics(advice: AnalysisLlmAdvice) -> Optional[str]:
    blob = " ".join([
        advice.editor_summary,
        advice.title.recommended,
        advice.title.why,
        advice.h1.recommended,
        advice.h1.why,
        advice.meta_description.recommended,
        advice.meta_description.why,
        *advice.next_steps,
    ]).lower()
    for phrase in _BANNED_METRIC_PHRASES:
        if phrase in blob:
            return f"Do not mention {phrase}; it is not in the facts."
    return None


def enrich_analysis_with_llm(facts: dict[str, Any]) -> dict[str, Any]:
    """Return Recommendation drafts, or status unavailable if the model fails."""
    if not facts:
        return unavailable_llm_advice("No analysis facts were available for recommendations.")
    try:
        advice = call_model_for_json(
            SYSTEM_PROMPT,
            (
                "Write recommendation drafts from these measured facts. "
                "Do not add metrics that are not in the JSON.\n\n"
                f"{facts}"
            ),
            AnalysisLlmAdvice,
            temperature=0.3,
            max_tokens=1400,
            schema_retries=1,
            extra_validate=_reject_invented_metrics,
        )
    except Exception as error:
        logger.warning("Analysis LLM skipped: %s", error)
        return unavailable_llm_advice(str(error) or "Recommendation model failed.")
    payload = advice.model_dump()
    payload["status"] = "ok"
    payload["reason"] = None
    payload["label"] = "Recommendation"
    payload["source"] = "llm"
    return payload
