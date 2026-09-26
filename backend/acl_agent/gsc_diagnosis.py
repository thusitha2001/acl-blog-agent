"""Page-level Search Console diagnosis for Competitor Analysis.

Live GSC numbers come from the standalone tool at GSC_TEST_ROOT
(C:\\Users\\thusitha\\gsc-test by default), which owns OAuth tokens and
the Search Console client. Metrics are never invented.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from acl_agent.config import logger
from acl_agent.keywords import content_tokens, fold_phrase, _intent
from acl_agent.metrics import UNAVAILABLE

GSC_TEST_ROOT = Path(os.environ.get("GSC_TEST_ROOT", r"C:\Users\thusitha\gsc-test"))
IMPRESSION_FLOOR = 100
ALLOWED_MONTHS = (1, 3, 6, 12)
_DAYS_FOR_MONTHS = {1: 30, 3: 90, 6: 180, 12: 365}
DEFAULT_MONTHS = 6
GSC_RETENTION_DAYS = 16 * 30
QUERY_LOSS_LIMIT = 10
SEASONAL_TERMS = {
    "travel", "temple", "bali", "holiday", "christmas", "summer", "winter",
    "monsoon", "festival", "ski", "beach", "halloween", "easter", "diwali",
    "thanksgiving", "newyear", "valentine", "wedding-season", "peak season",
}

EXPECTED_CTR = {
    "navigational": ((3, 0.20), (10, 0.08)),
    "transactional": ((3, 0.15), (10, 0.04)),
    "commercial": ((3, 0.12), (10, 0.035)),
    "informational": ((3, 0.08), (10, 0.025)),
}


def diagnosis_window(months: Any = None) -> dict[str, Any]:
    """Clamp the Search Console lookback to 1, 3, 6, or 12 months."""
    try:
        value = int(months)
    except (TypeError, ValueError):
        value = DEFAULT_MONTHS
    if value not in ALLOWED_MONTHS:
        value = min(ALLOWED_MONTHS, key=lambda option: abs(option - value))
    days = _DAYS_FOR_MONTHS[value]
    label = "Last 1 month" if value == 1 else f"Last {value} months"
    return {"months": value, "days": days, "label": label}


def _shift_years(iso: str, years: int) -> str:
    day = date.fromisoformat(iso)
    try:
        return day.replace(year=day.year + years).isoformat()
    except ValueError:
        return (day + timedelta(days=365 * years)).isoformat()


def _clean_totals(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not row:
        return None
    impressions = row.get("impressions")
    if impressions is None:
        return None
    position = row.get("position")
    if int(impressions or 0) == 0 and not position:
        position = None
    return {
        "clicks": int(row.get("clicks") or 0),
        "impressions": int(impressions or 0),
        "ctr": float(row.get("ctr") or 0),
        "position": None if position is None else float(position),
    }


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous is None or previous == 0:
        return None
    return round((float(current) - float(previous)) / float(previous) * 100, 1)


def _compare_totals(
    label: str,
    start: Optional[str],
    end: Optional[str],
    current: Optional[dict[str, Any]],
    baseline: Optional[dict[str, Any]],
    *,
    status: str = "ok",
    reason: Optional[str] = None,
) -> dict[str, Any]:
    if status != "ok":
        return {
            "label": label,
            "start": start,
            "end": end,
            "status": status,
            "reason": reason or UNAVAILABLE,
            "clicks": None,
            "impressions": None,
            "ctr": None,
            "position": None,
            "clicks_delta": None,
            "impressions_delta": None,
            "impressions_delta_pct": None,
        }
    base = _clean_totals(baseline) or {}
    cur = _clean_totals(current) or {}
    return {
        "label": label,
        "start": start,
        "end": end,
        "status": "ok",
        "reason": None,
        "clicks": base.get("clicks"),
        "impressions": base.get("impressions"),
        "ctr": base.get("ctr"),
        "position": base.get("position"),
        "clicks_delta": None if cur.get("clicks") is None or base.get("clicks") is None else cur["clicks"] - base["clicks"],
        "impressions_delta": None if cur.get("impressions") is None or base.get("impressions") is None else cur["impressions"] - base["impressions"],
        "impressions_delta_pct": _pct_change(cur.get("impressions"), base.get("impressions")),
    }


def year_ago_bounds(start: Optional[str], end: Optional[str], *, as_of: Optional[date] = None) -> dict[str, Any]:
    if not start or not end:
        return {"status": "unavailable", "reason": "Current date range missing."}
    year_start = _shift_years(start, -1)
    year_end = _shift_years(end, -1)
    today = as_of or date.today()
    if (today - date.fromisoformat(year_start)).days > GSC_RETENTION_DAYS:
        return {
            "status": "unavailable",
            "reason": "Search Console only keeps about 16 months of data, so a year-ago window is not available for this range.",
            "start": year_start,
            "end": year_end,
        }
    return {"status": "ok", "reason": None, "start": year_start, "end": year_end}


def query_loss_table(
    current_queries: Optional[list[dict[str, Any]]],
    previous_queries: Optional[list[dict[str, Any]]],
    *,
    limit: int = QUERY_LOSS_LIMIT,
) -> dict[str, Any]:
    if previous_queries is None:
        return {
            "status": "unavailable",
            "reason": "Previous-period query rows were not returned by Search Console.",
            "items": [],
        }
    current_map = {
        str(row.get("query") or "").strip().lower(): row
        for row in (current_queries or [])
        if row.get("query")
    }
    items: list[dict[str, Any]] = []
    for row in previous_queries:
        query = str(row.get("query") or "").strip()
        if not query:
            continue
        prev_impr = int(row.get("impressions") or 0)
        now = current_map.get(query.lower())
        now_impr = int((now or {}).get("impressions") or 0)
        lost = prev_impr - now_impr
        if lost <= 0:
            continue
        now_pos = (now or {}).get("position")
        prev_pos = row.get("position")
        now_ctr = (now or {}).get("ctr")
        prev_ctr = row.get("ctr")
        if now is None:
            kind = "vanished"
        elif now_pos is not None and prev_pos and float(now_pos) - float(prev_pos) >= 3:
            kind = "position_fell"
        elif prev_ctr and now_ctr is not None and float(now_ctr) < float(prev_ctr) * 0.7:
            kind = "ctr_fell"
        else:
            kind = "demand_down"
        items.append({
            "query": query,
            "impressions": now_impr,
            "previous_impressions": prev_impr,
            "impressions_delta": -lost,
            "clicks": int((now or {}).get("clicks") or 0),
            "previous_clicks": int(row.get("clicks") or 0),
            "position": None if now_pos is None else float(now_pos),
            "previous_position": None if prev_pos is None else float(prev_pos),
            "kind": kind,
        })
    items.sort(key=lambda item: (item["impressions_delta"], -item["previous_impressions"]))
    return {"status": "ok", "reason": None, "items": items[:limit]}


def build_comparisons(
    *,
    current: Optional[dict[str, Any]],
    previous: Optional[dict[str, Any]],
    year_ago: Optional[dict[str, Any]],
    current_range: Optional[dict[str, Any]] = None,
    previous_range: Optional[dict[str, Any]] = None,
    year_ago_range: Optional[dict[str, Any]] = None,
    year_ago_reason: Optional[str] = None,
) -> dict[str, Any]:
    current_range = current_range or {}
    previous_range = previous_range or {}
    year_ago_range = year_ago_range or {}
    this_period = {
        "label": "This period",
        "start": current_range.get("start"),
        "end": current_range.get("end"),
        "status": "ok" if current else "unavailable",
        "reason": None if current else UNAVAILABLE,
        **(_clean_totals(current) or {"clicks": None, "impressions": None, "ctr": None, "position": None}),
    }
    prev_status = "ok" if previous is not None else "unavailable"
    yoy_status = "ok" if year_ago is not None else "unavailable"
    return {
        "current": this_period,
        "previous": _compare_totals(
            "Previous period",
            previous_range.get("start"),
            previous_range.get("end"),
            current,
            previous,
            status=prev_status,
            reason=None if prev_status == "ok" else "Previous-period totals were not returned.",
        ),
        "year_ago": _compare_totals(
            "Year ago",
            year_ago_range.get("start"),
            year_ago_range.get("end"),
            current,
            year_ago,
            status=yoy_status,
            reason=year_ago_reason or (None if yoy_status == "ok" else "Year-ago totals were not returned."),
        ),
    }


def _load_gsc_test():
    root_s = str(GSC_TEST_ROOT)
    if root_s not in sys.path:
        sys.path.append(root_s)
    from gsc_diagnosis.auth import get_gsc_service  # type: ignore
    from gsc_diagnosis.gsc import fetch_page_queries, fetch_page_totals  # type: ignore

    return get_gsc_service(), fetch_page_totals, fetch_page_queries


def enrich_gsc_periods(raw: dict[str, Any]) -> dict[str, Any]:
    """Add year-ago totals and previous-period queries. Never invents numbers."""
    gsc = raw.get("gsc") or {}
    start, end = gsc.get("start_date"), gsc.get("end_date")
    yoy = year_ago_bounds(start, end)
    raw["year_ago_start_date"] = yoy.get("start")
    raw["year_ago_end_date"] = yoy.get("end")
    if yoy["status"] != "ok":
        raw["year_ago_totals"] = None
        raw["year_ago_reason"] = yoy["reason"]
    site_url = gsc.get("site_url")
    page_url = gsc.get("gsc_page_url") or raw.get("url")
    prev_start, prev_end = gsc.get("previous_start_date"), gsc.get("previous_end_date")
    if yoy["status"] == "ok" or (prev_start and prev_end):
        service, fetch_totals, fetch_queries = _load_gsc_test()
        if yoy["status"] == "ok" and site_url and page_url:
            try:
                raw["year_ago_totals"] = fetch_totals(service, site_url, page_url, yoy["start"], yoy["end"])
                raw["year_ago_reason"] = None
            except Exception as error:
                logger.warning("Year-ago GSC totals skipped: %s", error)
                raw["year_ago_totals"] = None
                raw["year_ago_reason"] = str(error) or "Year-ago lookup failed."
        if prev_start and prev_end and site_url and page_url and raw.get("previous_queries") is None:
            try:
                raw["previous_queries"] = fetch_queries(service, site_url, page_url, prev_start, prev_end)
            except Exception as error:
                logger.warning("Previous-period GSC queries skipped: %s", error)
                raw["previous_queries"] = None
                raw["previous_queries_reason"] = str(error) or "Previous-period query lookup failed."
    return raw


def unavailable_diagnosis(reason: str, url: str = "", days: int = 180) -> dict[str, Any]:
    window = diagnosis_window(round(days / 30) if days else DEFAULT_MONTHS)
    return {
        "status": "unavailable",
        "reason": reason,
        "url": url,
        "days": window["days"],
        "period": window,
        "clicks": None,
        "impressions": None,
        "ctr": None,
        "position": None,
        "trend": {},
        "queries": [],
        "keyword_targeting": {},
        "indexing": {},
        "title": {},
        "h1": {},
        "meta": {},
        "internal_linking": {},
        "off_topic_headings": [],
        "recommended_actions": [],
        "site_queries": [],
        "comparisons": build_comparisons(current=None, previous=None, year_ago=None),
        "query_losses": {
            "status": "unavailable",
            "reason": "Search Console is not connected.",
            "items": [],
        },
    }


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _contains_phrase(haystack: str, phrase: str) -> bool:
    if not phrase or not haystack:
        return False
    return fold_phrase(phrase) in fold_phrase(haystack) or set(content_tokens(phrase)).issubset(set(content_tokens(haystack)))


def _query_intent(query: str) -> str:
    return _intent(query or "")


def expected_ctr(position: Optional[float], intent: str = "informational") -> Optional[float]:
    if position is None:
        return None
    bands = EXPECTED_CTR.get(intent) or EXPECTED_CTR["informational"]
    if position <= bands[0][0]:
        return bands[0][1]
    if position <= bands[1][0]:
        return bands[1][1]
    return bands[1][1] * 0.5


def _is_seasonal(url: str, keyword: str, category: str = "") -> bool:
    blob = f"{url} {keyword} {category}".lower()
    return any(term in blob for term in SEASONAL_TERMS)


def _on_page_audit(blog_url: str, page: Optional[dict[str, Any]], target_keyword: str) -> dict[str, Any]:
    page = page or {}
    title = str(page.get("title") or "")
    h1 = str(page.get("h1") or (page.get("h1_headings") or [""])[0] or "")
    meta = str(page.get("meta_description") or "")
    robots = str(page.get("robots") or "")
    canonical = str(page.get("canonical") or "")
    url = str(page.get("url") or blog_url or "")
    heads = list(page.get("h2_headings") or [])
    kw_tokens = set(content_tokens(target_keyword))
    off_topic = []
    for heading in heads:
        tokens = set(content_tokens(heading))
        if tokens and kw_tokens and not (tokens & kw_tokens) and len(heading.split()) >= 4:
            off_topic.append(heading)
    title_issues = []
    if not title:
        title_issues.append("Missing title")
    elif target_keyword and not _contains_phrase(title, target_keyword):
        title_issues.append("Title does not contain the target keyword or a close variant")
    if len(title) > 65:
        title_issues.append("Title is longer than ~65 characters")
    h1_issues = []
    if not h1:
        h1_issues.append("Missing H1")
    elif target_keyword and not _contains_phrase(h1, target_keyword):
        h1_issues.append("H1 does not contain the target keyword or a close variant")
    meta_issues = []
    if not meta or meta == UNAVAILABLE:
        meta_issues.append("Meta description missing from extract")
    elif len(meta) < 50:
        meta_issues.append("Meta description is thin")
    indexed = "noindex" not in robots.lower()
    internal = page.get("internal_links") or page.get("internal_link_count") or 0
    if isinstance(internal, list):
        internal = len(internal)
    return {
        "title": {
            "value": title,
            "issues": title_issues,
            "recommended_action": "Rewrite the title around the query the page actually ranks for." if title_issues else "",
        },
        "h1": {
            "value": h1,
            "issues": h1_issues,
            "recommended_action": "Align the H1 with the primary ranking query." if h1_issues else "",
        },
        "meta": {
            "value": meta if meta != UNAVAILABLE else "",
            "issues": meta_issues,
            "recommended_action": "Write a 140–160 character snippet that promises the ranking-query answer." if meta_issues else "",
        },
        "indexing": {
            "robots": robots or UNAVAILABLE,
            "canonical": canonical or UNAVAILABLE,
            "status": "indexable" if indexed else "noindex",
        },
        "internal_linking": {
            "count": int(internal or 0),
            "note": "Internal link count from the extracted page only.",
        },
        "off_topic_headings": off_topic[:8],
        "content_type": page.get("content_type") or "",
        "h2_count": int(page.get("h2_count") or len(heads) or 0),
        "word_count": int(page.get("word_count") or 0),
        "url": url,
    }


def _brand_host_tokens(url: str) -> set[str]:
    host = _host(url).split(".")
    return {part for part in host if len(part) >= 4 and part not in {"www", "blog", "blogs", "news"}}


def _first_h1(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0] if value else "")
    return str(value or "")


REC_CATEGORY = {
    "rewrite_title_primary": "Title",
    "tighten_title": "Title",
    "align_h1": "H1",
    "rewrite_meta": "Meta",
    "fix_indexability": "Indexing",
}


def run_gsc_test_diagnosis(blog_url: str, days: int = 180) -> dict[str, Any]:
    """Call the standalone gsc-test diagnose_page() using that folder's tokens."""
    root = GSC_TEST_ROOT
    if not root.is_dir():
        raise FileNotFoundError(f"GSC tool not found at {root}")
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.append(root_s)
    from gsc_diagnosis.pipeline import diagnose_page  # type: ignore

    raw = diagnose_page(blog_url, days=days)
    try:
        return enrich_gsc_periods(raw)
    except Exception as error:
        logger.warning("GSC period enrichment skipped: %s", error)
        raw.setdefault("year_ago_totals", None)
        raw.setdefault("previous_queries", None)
        raw.setdefault("year_ago_reason", str(error) or "Period enrichment failed.")
        return raw


def _map_recommendation(item: dict[str, Any]) -> dict[str, Any]:
    rec_id = str(item.get("id") or "")
    queries = item.get("queries") or []
    related = queries[0] if queries else rec_id
    action = item.get("action") or item.get("title") or item.get("recommended_action") or ""
    detail = item.get("detail") or item.get("reason") or action
    return {
        "priority": item.get("priority") or "High Priority",
        "category": REC_CATEGORY.get(rec_id, item.get("category") or "GSC"),
        "issue": action,
        "recommended_action": detail,
        "estimated_impact": item.get("estimated_impact_label") or item.get("estimated_impact") or "",
        "estimated_effort": str(item.get("effort") or "medium").title(),
        "related_gap": related,
        "source": "gsc",
        "id": rec_id,
    }


def _keyword_mismatch(primary: str, target_keyword: str) -> bool:
    if not primary or not target_keyword:
        return False
    return (
        fold_phrase(primary) != fold_phrase(target_keyword)
        and not _contains_phrase(target_keyword, primary)
        and not _contains_phrase(primary, target_keyword)
    )


def _payload_from_metrics(
    url: str,
    days: int,
    audit: dict[str, Any],
    metrics: dict[str, Any],
    target_keyword: str,
) -> dict[str, Any]:
    queries = list(metrics.get("queries") or [])
    brand = _brand_host_tokens(url)
    for row in queries:
        tokens = set(content_tokens(row.get("query") or ""))
        row["branded"] = bool(tokens & brand)
        row["intent"] = row.get("intent") or _query_intent(row.get("query") or "")
    branded_impr = sum(int(row.get("impressions") or 0) for row in queries if row.get("branded"))
    nonbrand_impr = sum(int(row.get("impressions") or 0) for row in queries if not row.get("branded"))
    intent_split: dict[str, int] = {}
    for row in queries:
        intent = row.get("intent") or "informational"
        intent_split[intent] = intent_split.get(intent, 0) + int(row.get("impressions") or 0)
    primary = (queries[0].get("query") if queries else "") or ""
    hay_title = str(audit.get("title", {}).get("value") or "")
    hay_h1 = str(audit.get("h1", {}).get("value") or "")
    hay_url = str(audit.get("url") or url)
    payload = {
        "status": "ok",
        "reason": None,
        "url": url,
        "days": days,
        "clicks": metrics.get("clicks"),
        "impressions": metrics.get("impressions"),
        "ctr": metrics.get("ctr"),
        "position": metrics.get("position"),
        "trend": metrics.get("trend") or {},
        "queries": queries,
        "branded_split": {
            "branded_impressions": branded_impr,
            "nonbranded_impressions": nonbrand_impr,
        },
        "intent_split": intent_split,
        "keyword_targeting": {
            "target_keyword": target_keyword,
            "primary_ranking_query": primary,
            "mismatch": _keyword_mismatch(primary, target_keyword),
            "in_title": _contains_phrase(hay_title, primary) if primary else False,
            "in_h1": _contains_phrase(hay_h1, primary) if primary else False,
            "in_url": _contains_phrase(hay_url.replace("-", " "), primary) if primary else False,
        },
        "site_queries": metrics.get("site_queries") or [],
        "range": metrics.get("range") or {},
        "source": "metrics",
        "comparisons": metrics.get("comparisons") or build_comparisons(
            current=metrics,
            previous=(metrics.get("trend") or {}).get("previous") or metrics.get("previous_totals"),
            year_ago=metrics.get("year_ago_totals"),
            current_range=metrics.get("range") or {},
            previous_range=metrics.get("previous_range") or {},
            year_ago_range=metrics.get("year_ago_range") or {},
            year_ago_reason=metrics.get("year_ago_reason"),
        ),
        "query_losses": metrics.get("query_losses") or query_loss_table(
            queries,
            metrics.get("previous_queries"),
        ),
    }
    payload.update(audit)
    payload["recommended_actions"] = _gsc_actions(payload, target_keyword)
    return payload


def adapt_gsc_test_diagnosis(
    raw: dict[str, Any],
    *,
    blog_url: str,
    days: int,
    page: Optional[dict[str, Any]] = None,
    target_keyword: str = "",
    audit: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Map gsc-test diagnose_page() output onto the Competitor Analysis contract."""
    url = blog_url
    audit = dict(audit or _on_page_audit(url, page, target_keyword))
    totals = raw.get("totals") or {}
    targeting = raw.get("targeting") or {}
    query_analysis = raw.get("query_analysis") or {}
    content = raw.get("content") or {}
    links = raw.get("links") or {}
    gsc_meta = raw.get("gsc") or {}
    page_meta = raw.get("page") or {}
    trend_src = raw.get("trend") or {}
    deltas = trend_src.get("deltas") or {}
    impr_ratio = deltas.get("impressions_ratio")
    impressions_delta = deltas.get("impressions")
    impressions_delta_pct = None
    if isinstance(impr_ratio, (int, float)):
        impressions_delta_pct = round(impr_ratio * 100, 1)
    elif isinstance(impressions_delta, (int, float)):
        previous = (trend_src.get("previous") or {}).get("impressions")
        if previous:
            impressions_delta_pct = round((impressions_delta / previous) * 100, 1)

    primary = targeting.get("primary_query") or ""
    if not primary:
        top = (query_analysis.get("top") or [{}])
        primary = (top[0].get("query") if top else "") or ""

    hay_title = str(audit.get("title", {}).get("value") or page_meta.get("title") or "")
    hay_h1 = str(audit.get("h1", {}).get("value") or _first_h1(page_meta.get("h1")))
    hay_url = str(audit.get("url") or page_meta.get("final_url") or url)
    in_title = targeting.get("primary_in_title")
    in_h1 = targeting.get("primary_in_h1")
    in_url = targeting.get("primary_in_url")
    if in_title is None:
        in_title = _contains_phrase(hay_title, primary) if primary else False
    if in_h1 is None:
        in_h1 = _contains_phrase(hay_h1, primary) if primary else False
    if in_url is None:
        in_url = _contains_phrase(hay_url.replace("-", " "), primary) if primary else False

    queries = []
    for row in query_analysis.get("top") or []:
        query = row.get("query") or ""
        queries.append({
            "query": query,
            "clicks": int(row.get("clicks") or 0),
            "impressions": int(row.get("impressions") or 0),
            "ctr": float(row.get("ctr") or 0),
            "position": float(row.get("position") or 0),
            "intent": row.get("intent") or _query_intent(query),
        })

    intent_split = {
        str(key): int(value)
        for key, value in (query_analysis.get("intent_impressions") or {}).items()
    }
    if not intent_split:
        for row in queries:
            intent = row.get("intent") or "informational"
            intent_split[intent] = intent_split.get(intent, 0) + int(row.get("impressions") or 0)

    title_issues = [
        issue for issue in (content.get("issues") or [])
        if "title" in str(issue).lower()
    ]
    h1_issues = [
        issue for issue in (content.get("issues") or [])
        if "h1" in str(issue).lower()
    ]
    meta_issues = [
        issue for issue in (content.get("issues") or [])
        if "meta" in str(issue).lower()
    ]
    if targeting.get("primary_query") and not targeting.get("primary_in_title"):
        title_issues = title_issues or [
            f'Primary query "{primary}" is missing from the title'
        ]
    if targeting.get("primary_query") and not targeting.get("primary_in_h1"):
        h1_issues = h1_issues or [
            f'Primary query "{primary}" is missing from the H1'
        ]

    indexing_issues = list(raw.get("indexing_issues") or [])
    inspection = gsc_meta.get("inspection") or {}
    robots = str(page_meta.get("robots") or audit.get("indexing", {}).get("robots") or "")
    index_status = "indexable"
    if any("noindex" in str(issue).lower() for issue in indexing_issues) or "noindex" in robots.lower():
        index_status = "noindex"
    elif inspection.get("coverage_state"):
        index_status = str(inspection.get("coverage_state"))

    actions = [_map_recommendation(item) for item in raw.get("recommendations") or [] if isinstance(item, dict)]
    payload = {
        "status": "ok",
        "reason": None,
        "url": url,
        "days": int(gsc_meta.get("days") or days),
        "clicks": totals.get("clicks"),
        "impressions": totals.get("impressions"),
        "ctr": totals.get("ctr"),
        "position": totals.get("position"),
        "trend": {
            "status": trend_src.get("status"),
            "clicks_delta": deltas.get("clicks"),
            "impressions_delta": impressions_delta,
            "impressions_delta_pct": impressions_delta_pct,
            "position_delta": deltas.get("position"),
            "note": trend_src.get("note") or "",
        },
        "queries": queries,
        "branded_split": {
            "branded_impressions": int(query_analysis.get("branded_impressions") or 0),
            "nonbranded_impressions": int(
                (totals.get("impressions") or 0) - (query_analysis.get("branded_impressions") or 0)
            ),
        },
        "intent_split": intent_split,
        "keyword_targeting": {
            "target_keyword": target_keyword or targeting.get("target_query") or "",
            "primary_ranking_query": primary,
            "gsc_target_query": targeting.get("target_query") or "",
            "mismatch": _keyword_mismatch(primary, target_keyword or targeting.get("target_query") or ""),
            "in_title": bool(in_title),
            "in_h1": bool(in_h1),
            "in_url": bool(in_url),
        },
        "site_queries": (raw.get("sitewide") or {}).get("other_pages") or [],
        "range": {
            "start": gsc_meta.get("start_date"),
            "end": gsc_meta.get("end_date"),
            "days": gsc_meta.get("days") or days,
            "label": gsc_meta.get("date_range_label") or diagnosis_window(round((gsc_meta.get("days") or days) / 30))["label"],
        },
        "period": {
            **diagnosis_window(round((gsc_meta.get("days") or days) / 30)),
            "start": gsc_meta.get("start_date"),
            "end": gsc_meta.get("end_date"),
            "label": gsc_meta.get("date_range_label") or diagnosis_window(round((gsc_meta.get("days") or days) / 30))["label"],
        },
        "verdict": raw.get("verdict"),
        "why": raw.get("why") or [],
        "diagnoses": raw.get("diagnoses") or [],
        "gsc_confidence": raw.get("confidence") or {},
        "source": "gsc-test",
        "comparisons": build_comparisons(
            current=totals,
            previous=(trend_src.get("previous") or raw.get("previous_totals")),
            year_ago=raw.get("year_ago_totals"),
            current_range={"start": gsc_meta.get("start_date"), "end": gsc_meta.get("end_date")},
            previous_range={
                "start": gsc_meta.get("previous_start_date"),
                "end": gsc_meta.get("previous_end_date"),
            },
            year_ago_range={
                "start": raw.get("year_ago_start_date"),
                "end": raw.get("year_ago_end_date"),
            },
            year_ago_reason=raw.get("year_ago_reason"),
        ),
        "query_losses": query_loss_table(queries, raw.get("previous_queries")),
        "title": {
            "value": hay_title,
            "issues": title_issues or (audit.get("title") or {}).get("issues") or [],
            "recommended_action": "Rewrite the title around the query the page actually ranks for." if title_issues else "",
        },
        "h1": {
            "value": hay_h1,
            "issues": h1_issues or (audit.get("h1") or {}).get("issues") or [],
            "recommended_action": "Align the H1 with the primary ranking query." if h1_issues else "",
        },
        "meta": {
            "value": page_meta.get("meta_description") or (audit.get("meta") or {}).get("value") or "",
            "issues": meta_issues or (audit.get("meta") or {}).get("issues") or [],
            "recommended_action": "Write a 140–160 character snippet that promises the ranking-query answer." if meta_issues else "",
        },
        "indexing": {
            "robots": robots or UNAVAILABLE,
            "canonical": page_meta.get("canonical") or (audit.get("indexing") or {}).get("canonical") or UNAVAILABLE,
            "status": index_status,
            "issues": indexing_issues,
        },
        "internal_linking": {
            "count": int(links.get("internal_count") or audit.get("internal_linking", {}).get("count") or 0),
            "note": "; ".join(links.get("issues") or []) or "Internal link count from the GSC page diagnosis.",
        },
        "off_topic_headings": content.get("off_topic_headings") or audit.get("off_topic_headings") or [],
        "content_type": (page or {}).get("content_type") or audit.get("content_type") or "",
        "h2_count": int((page or {}).get("h2_count") or audit.get("h2_count") or len(page_meta.get("h2") or []) or 0),
        "word_count": int(page_meta.get("word_count") or audit.get("word_count") or 0),
    }
    payload["recommended_actions"] = actions or _gsc_actions(payload, target_keyword)
    return payload


def diagnose_page_visibility(
    blog_url: str,
    days: int = 180,
    *,
    page: Optional[dict[str, Any]] = None,
    target_keyword: str = "",
    gsc_metrics: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return the full GSC diagnosis dict, or status:'unavailable' if GSC fails."""
    window = diagnosis_window(round(days / 30) if days else DEFAULT_MONTHS)
    days = window["days"]
    url = (blog_url or "").strip()
    if not url:
        return unavailable_diagnosis("No blog URL submitted.", days=days)
    audit = _on_page_audit(url, page, target_keyword)
    if gsc_metrics is not None:
        if not gsc_metrics:
            payload = unavailable_diagnosis(
                "Search Console is not connected, or this host is not an available property.",
                url,
            )
            payload.update(audit)
            payload["days"] = days
            payload["recommended_actions"] = _gsc_actions(payload, target_keyword)
            return payload
        return _payload_from_metrics(url, days, audit, gsc_metrics, target_keyword)

    try:
        raw = run_gsc_test_diagnosis(url, days=days)
    except Exception as error:
        logger.warning("GSC diagnosis failed for %s: %s", url, error)
        payload = unavailable_diagnosis(
            str(error) or "Search Console is not connected, or this host is not an available property.",
            url,
        )
        payload.update(audit)
        payload["days"] = days
        payload["recommended_actions"] = _gsc_actions(payload, target_keyword)
        return payload
    return adapt_gsc_test_diagnosis(
        raw,
        blog_url=url,
        days=days,
        page=page,
        target_keyword=target_keyword,
        audit=audit,
    )


def _gsc_actions(diagnosis: dict[str, Any], target_keyword: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    targeting = diagnosis.get("keyword_targeting") or {}
    if targeting.get("mismatch") and not (targeting.get("in_title") and targeting.get("in_h1")):
        items.append({
            "priority": "Critical",
            "category": "Title",
            "issue": "Primary ranking query differs from the target keyword used in the title/H1",
            "recommended_action": (
                f"Rewrite the title and H1 around “{targeting.get('primary_ranking_query')}” "
                f"instead of forcing “{targeting.get('target_keyword') or target_keyword}”. "
                "Do not exact-match stuff."
            ),
            "estimated_impact": "Aligns the snippet with the query Google already shows",
            "estimated_effort": "Low",
            "related_gap": targeting.get("primary_ranking_query") or "",
            "source": "gsc",
        })
    title = diagnosis.get("title") or {}
    if title.get("issues") and not any(item["category"] == "Title" for item in items):
        items.append({
            "priority": "High Priority",
            "category": "Title",
            "issue": "; ".join(title.get("issues") or []),
            "recommended_action": title.get("recommended_action") or "Fix the title tag.",
            "estimated_impact": "Snippet CTR",
            "estimated_effort": "Low",
            "related_gap": "title",
            "source": "gsc",
        })
    h1 = diagnosis.get("h1") or {}
    if h1.get("issues"):
        items.append({
            "priority": "High Priority",
            "category": "H1",
            "issue": "; ".join(h1.get("issues") or []),
            "recommended_action": h1.get("recommended_action") or "Fix the H1.",
            "estimated_impact": "On-page query alignment",
            "estimated_effort": "Low",
            "related_gap": "h1",
            "source": "gsc",
        })
    meta = diagnosis.get("meta") or {}
    if meta.get("issues"):
        items.append({
            "priority": "Medium Priority",
            "category": "Meta",
            "issue": "; ".join(meta.get("issues") or []),
            "recommended_action": meta.get("recommended_action") or "Write a clearer meta description.",
            "estimated_impact": "Snippet CTR",
            "estimated_effort": "Low",
            "related_gap": "meta",
            "source": "gsc",
        })
    indexing = diagnosis.get("indexing") or {}
    if indexing.get("status") == "noindex":
        items.append({
            "priority": "Critical",
            "category": "Indexing",
            "issue": "Page is marked noindex",
            "recommended_action": "Remove noindex if this URL should appear in search.",
            "estimated_impact": "Restores eligibility for impressions",
            "estimated_effort": "Low",
            "related_gap": "robots",
            "source": "gsc",
        })
    return items


def merge_gsc_actions(
    plan: list[dict[str, Any]],
    diagnosis: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    """GSC title/H1/meta actions replace overlapping on-page heuristics."""
    plan = list(plan or [])
    gsc_items = list((diagnosis or {}).get("recommended_actions") or [])
    if not gsc_items:
        return plan
    overlap = re.compile(r"\b(title|h1|meta description|meta)\b", re.I)

    def key(item: dict[str, Any]) -> str:
        blob = f"{item.get('category', '')} {item.get('issue', '')} {item.get('related_gap', '')}".lower()
        if overlap.search(blob):
            match = overlap.search(blob)
            return match.group(1).lower() if match else blob
        return blob[:40]

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for item in gsc_items:
        slot = key(item)
        if slot in seen:
            continue
        seen.add(slot)
        merged.append(item)
    for item in plan:
        slot = key(item)
        if slot in seen and overlap.search(f"{item.get('category', '')} {item.get('issue', '')}"):
            continue
        merged.append(item)
        seen.add(slot)
    return merged


def _dominant_intent(diagnosis: dict[str, Any], fallback: str = "informational") -> str:
    split = diagnosis.get("intent_split") or {}
    if split:
        return max(split.items(), key=lambda pair: pair[1])[0]
    targeting = diagnosis.get("keyword_targeting") or {}
    return _query_intent(targeting.get("primary_ranking_query") or targeting.get("target_keyword") or fallback)


def _is_broad_guide(page: Optional[dict[str, Any]], diagnosis: dict[str, Any]) -> bool:
    content_type = str((page or {}).get("content_type") or diagnosis.get("content_type") or "")
    h2s = int((page or {}).get("h2_count") or diagnosis.get("h2_count") or 0)
    queries = diagnosis.get("queries") or []
    if content_type.lower() in {"editorial guide", "listicle"} and h2s >= 6 and len(queries) >= 4:
        return True
    return False


def _is_narrow_howto(page: Optional[dict[str, Any]], diagnosis: dict[str, Any], keyword: str) -> bool:
    blob = f"{(page or {}).get('title', '')} {keyword} {diagnosis.get('content_type', '')}".lower()
    h2s = int((page or {}).get("h2_count") or diagnosis.get("h2_count") or 0)
    return bool(re.search(r"\bhow to\b", blob)) or h2s <= 4


def build_diagnosis_summary(
    diagnosis: Optional[dict[str, Any]],
    *,
    target_keyword: str = "",
    page: Optional[dict[str, Any]] = None,
    content_gaps: Optional[dict[str, Any]] = None,
    competitor_avg_words: Optional[float] = None,
) -> dict[str, Any]:
    """Single most likely traffic reason, with confidence and seasonal caveats."""
    diagnosis = diagnosis or {}
    targeting = diagnosis.get("keyword_targeting") or {}
    trend = diagnosis.get("trend") or {}
    impressions = diagnosis.get("impressions")
    ctr = diagnosis.get("ctr")
    position = diagnosis.get("position")
    keyword = target_keyword or targeting.get("target_keyword") or ""
    sample_ok = isinstance(impressions, (int, float)) and impressions >= IMPRESSION_FLOOR
    seasonal = _is_seasonal(
        str(diagnosis.get("url") or (page or {}).get("url") or ""),
        keyword,
        str((page or {}).get("content_type") or ""),
    )
    comparisons = diagnosis.get("comparisons") or {}
    yoy = comparisons.get("year_ago") or {}
    yoy_pct = yoy.get("impressions_delta_pct") if yoy.get("status") == "ok" else None
    caveat = ""
    if seasonal and yoy_pct is None:
        caveat = " Seasonal/travel pages often swing; treat this as a hypothesis pending a year-over-year comparison."
    intent = _dominant_intent(diagnosis)
    broad = _is_broad_guide(page, diagnosis)
    narrow = _is_narrow_howto(page, diagnosis, keyword)

    def pack(kind: str, text: str, confidence: str, **extra: Any) -> dict[str, Any]:
        wording = text
        if confidence == "low" and not wording.lower().startswith("possible"):
            wording = "Possible cause (low sample): " + wording[0].lower() + wording[1:]
        if caveat and kind in {"visibility_drop", "ctr_gap"}:
            wording = wording.rstrip(".") + "." + caveat
        return {
            "kind": kind,
            "text": wording,
            "confidence": confidence,
            "intent": intent,
            "seasonal_caveat": bool(caveat) and kind in {"visibility_drop", "ctr_gap"},
            **extra,
        }

    drop_pct = trend.get("impressions_delta_pct")
    if drop_pct is None:
        drop_pct = (comparisons.get("previous") or {}).get("impressions_delta_pct")
    drop_abs = trend.get("impressions_delta")
    if drop_abs is None:
        drop_abs = (comparisons.get("previous") or {}).get("impressions_delta")
    if isinstance(drop_pct, (int, float)) and drop_pct <= -30:
        confidence = "high" if sample_ok else "low"
        period = (diagnosis.get("period") or {}).get("label") or ""
        window_note = f" over {period.lower()}" if period else ""
        delta_note = f"{drop_pct:.0f}% impressions vs the previous period"
        if isinstance(drop_abs, (int, float)):
            delta_note += f" ({int(drop_abs)})"
        if isinstance(yoy_pct, (int, float)) and yoy_pct > -10:
            return pack(
                "seasonal_swing",
                f"Traffic is down{window_note} vs the previous period ({delta_note}), "
                f"but year-ago impressions are {yoy_pct:+.0f}%. This looks seasonal, not a collapse.",
                "medium" if sample_ok else "low",
                delta_pct=drop_pct,
                delta=drop_abs,
                year_ago_delta_pct=yoy_pct,
            )
        if isinstance(yoy_pct, (int, float)) and yoy_pct <= -30:
            delta_note += f"; also {yoy_pct:.0f}% vs last year"
        return pack(
            "visibility_drop",
            f"Visibility drop{window_note} — investigate deindexing/technical issue ({delta_note}).",
            confidence,
            delta_pct=drop_pct,
            delta=drop_abs,
        )

    primary = targeting.get("primary_ranking_query") or ""
    mismatch = bool(targeting.get("mismatch"))
    missing_placement = not (
        targeting.get("in_title") or targeting.get("in_h1") or targeting.get("in_url")
    )
    if mismatch and missing_placement and primary:
        confidence = "high" if sample_ok and narrow and not broad else ("medium" if sample_ok else "low")
        if broad and not narrow:
            text = (
                f"The strongest ranking query is “{primary}”, which differs from the target "
                f"“{keyword}”. That can be expected on a broad editorial guide with several H2s."
            )
            confidence = "medium" if sample_ok else "low"
        else:
            text = (
                f"Keyword-title mismatch: the page ranks for “{primary}” but the title/H1/URL "
                f"target “{keyword}”."
            )
        return pack("keyword_mismatch", text, confidence, primary_query=primary, target_keyword=keyword)

    expected = expected_ctr(position, intent)
    if (
        sample_ok
        and isinstance(ctr, (int, float))
        and isinstance(position, (int, float))
        and expected is not None
        and ctr < expected * 0.55
    ):
        return pack(
            "ctr_gap",
            "Title/snippet not compelling enough to earn clicks despite ranking "
            f"(CTR {ctr:.1%} vs ~{expected:.0%} expected for {intent} queries around position {position:.0f}).",
            "high",
        )

    your_words = int((page or {}).get("word_count") or diagnosis.get("word_count") or 0)
    if (
        isinstance(impressions, (int, float))
        and impressions < 500
        and competitor_avg_words
        and your_words
        and your_words + 400 < competitor_avg_words
    ):
        confidence = "high" if sample_ok else "low"
        return pack(
            "thin_visibility",
            "Insufficient topical authority/content depth to be shown for enough queries "
            f"({int(impressions)} impressions vs competitor extracts averaging {int(competitor_avg_words)} words).",
            confidence,
        )

    gap_topic = ""
    table = (content_gaps or {}).get("table") or []
    if table:
        gap_topic = table[0].get("missing_topic") or table[0].get("recommended_heading") or ""
    text = "On-page content gaps vs competitors"
    if gap_topic:
        text = f"On-page content gaps vs competitors — start with “{gap_topic}”."
    confidence = "medium" if table else "low"
    return pack("content_gaps", text, confidence)
