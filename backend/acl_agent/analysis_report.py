"""Content gaps, citation opportunities, traffic reasons, originality, action plan."""
from __future__ import annotations

import re
from typing import Any, Optional

from acl_agent.keywords import (
    article_intent,
    classify_page_intent,
    content_tokens,
    relevance_score,
    validate_keyword,
)
from acl_agent.metrics import UNAVAILABLE
from acl_agent.readability import analyze_readability
from acl_agent.validation import AI_FILLER_PHRASES, humanization_checks, ngram_overlap_ratio


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _similar(a: str, b: str, threshold: float = 0.45) -> bool:
    ta, tb = set(_norm(a).split()), set(_norm(b).split())
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= threshold


_BOILER_HEADING = re.compile(
    r"\b(buy|shop|online|price|prices|cart|collection|amazon|bewakoof|crazymonk)\b",
    re.I,
)

_STYLE_TOPIC_GAPS = [
    ("How should an oversized hoodie fit?", "How should an oversized hoodie fit?",
     ["What oversized means on the shoulders", "How long the hem should sit", "What to avoid"]),
    ("What pants pair well with an oversized hoodie?", "What to wear with an oversized hoodie",
     ["Jeans and trousers that balance the volume", "Joggers vs tailored pants", "Tuck and proportion tips"]),
    ("Best shoes for an oversized hoodie outfit", "Shoes that work with oversized hoodie outfits",
     ["Sneakers", "Boots", "When dress shoes fail"]),
    ("Layering oversized hoodies with jackets or coats", "Layering ideas for different seasons",
     ["Light overshirts", "Coats in cold weather", "What not to layer"]),
    ("Oversized hoodie outfits for casual and streetwear looks", "Casual and streetwear outfit combinations",
     ["Weekend errands", "Streetwear layers", "One elevated evening look"]),
    ("How to style oversized hoodies in warm weather", "Warm-weather oversized hoodie outfits",
     ["Fabric weight", "Shorts pairings", "When to skip the hoodie"]),
    ("Common oversized hoodie styling mistakes", "Common styling mistakes to avoid",
     ["Too much volume", "Wrong shoe weight", "Missing a belt or hem"]),
    ("Outfit ideas for different body types", "How to choose a flattering oversized fit",
     ["Petite", "Tall", "Broad shoulders"]),
    ("How to choose the right hoodie color", "How to choose the right hoodie color",
     ["Neutrals", "Contrast with pants", "Print vs solid"]),
    ("How to accessorize an oversized hoodie outfit", "Accessories that finish an oversized hoodie outfit",
     ["Hats", "Bags", "Jewelry without clutter"]),
]

_DEFAULT_OUTLINE = [
    "What makes an oversized hoodie look stylish?",
    "Choose the right oversized hoodie fit.",
    "What to wear with an oversized hoodie.",
    "Best pants and jeans for oversized hoodies.",
    "Shoes that work with oversized hoodie outfits.",
    "Layering ideas for different seasons.",
    "Casual and streetwear outfit combinations.",
    "Common styling mistakes to avoid.",
    "Frequently asked questions.",
]


def _heading_pool(row: dict[str, Any]) -> list[str]:
    title = str(row.get("title") or "").strip().lower()
    values = list(row.get("h2_headings") or []) + list(row.get("h3_headings") or [])
    extra = row.get("h2") or []
    if isinstance(extra, list):
        values.extend(extra)
    return [item.strip() for item in values if item and str(item).strip().lower() != title]


def _usable_content_heading(heading: str, keyword: str, page_title: str = "", page_relevance: float = 0.0) -> bool:
    raw = " ".join((heading or "").split())
    if len(raw.split()) < 2 or len(raw.split()) > 14:
        return False
    if raw.lower() == (page_title or "").strip().lower():
        return False
    if "|" in raw or " – " in raw or " — " in raw:
        return False
    if _BOILER_HEADING.search(raw):
        return False
    flags = validate_keyword(
        raw,
        keyword,
        source="heading",
        page_title=page_title,
        page_relevance=page_relevance,
    )
    if flags["accepted"]:
        return True
    if raw.endswith("?") and (
        relevance_score(raw, keyword) >= 0.12
        or set(content_tokens(raw)) & set(content_tokens(keyword))
    ):
        return flags["rejection_reason"] in {"word_count", "title_or_sentence", "low_topic_relevance", ""}
    if flags["rejection_reason"] in {
        "brand_or_domain",
        "product_boilerplate",
        "navigation",
        "page_title_only",
        "different_product_entity",
        "intent_mismatch",
    }:
        return False
    return bool(set(content_tokens(raw)) & set(content_tokens(keyword))) and flags["rejection_reason"] == "word_count"


def content_gaps(
    yours: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
    keyword: str = "",
) -> dict[str, Any]:
    keyword = keyword or (yours or {}).get("title") or ""
    article_intent_label = article_intent(keyword, yours)
    yours_h = _heading_pool(yours or {}) + [(yours or {}).get("h1") or ""]
    mine = [_norm(h) for h in yours_h if _norm(h)]
    mine.append(_norm((yours or {}).get("title") or ""))
    body = ((yours or {}).get("full_text") or (yours or {}).get("text") or "").lower()
    covered: dict[str, dict[str, Any]] = {}
    for row in competitors:
        intent = classify_page_intent(row)
        if article_intent_label == "informational" and intent in {"transactional", "navigational"}:
            continue
        domain = row.get("domain") or ""
        page_rel = relevance_score(
            " ".join([row.get("title") or "", row.get("snippet") or "", " ".join(_heading_pool(row)[:6])]),
            keyword,
        )
        for heading in _heading_pool(row)[:24]:
            if not _usable_content_heading(heading, keyword, row.get("title") or "", page_rel):
                continue
            key = _norm(heading)
            if len(key.split()) < 2:
                continue
            slot = covered.setdefault(heading.strip(), {"domains": [], "intent": intent, "heading": heading.strip()})
            if domain and domain not in slot["domains"]:
                slot["domains"].append(domain)

    rows = []
    for heading, meta in covered.items():
        if any(_similar(heading, mine_h) for mine_h in mine):
            continue
        if heading.lower() in body:
            continue
        domains = meta["domains"]
        importance = "high" if len(domains) >= 2 else "medium"
        rec = heading if heading.endswith("?") else heading.rstrip(".")
        rows.append({
            "missing_topic": heading,
            "evidence_type": "competitor_heading",
            "evidence_sources": domains[:4],
            "covered_by_competitors": domains[:4],
            "covered_by": ", ".join(domains[:4]) or UNAVAILABLE,
            "importance": importance,
            "intent": "informational" if meta["intent"] in {"informational", "mixed"} else meta["intent"],
            "search_intent": "informational" if meta["intent"] in {"informational", "mixed"} else meta["intent"],
            "recommended_heading": rec,
            "suggested_outline": ["Define the subtopic in two sentences", "Give a specific example", "Add a short how-to"],
            "reason": "Competitor H2/H3 coverage that your article does not yet match.",
        })

    kw_tokens = set(content_tokens(keyword))
    if {"hoodie"} <= kw_tokens and ({"style", "outfit", "wear"} & kw_tokens):
        for topic, heading, outline in _STYLE_TOPIC_GAPS:
            if any(_similar(topic, mine_h) or _similar(heading, mine_h) for mine_h in mine):
                continue
            if any(_similar(topic, row["missing_topic"]) for row in rows):
                continue
            evidence = [d for item, meta in covered.items() if _similar(topic, item) for d in meta["domains"]]
            rows.append({
                "missing_topic": topic,
                "evidence_type": "competitor_heading" if evidence else "semantic_gap",
                "evidence_sources": evidence[:4],
                "covered_by_competitors": evidence[:4],
                "covered_by": ", ".join(evidence[:4]) or "topic model",
                "importance": "high" if any(token in topic.lower() for token in ("fit", "pants", "mistake")) else "medium",
                "intent": "informational",
                "search_intent": "informational",
                "recommended_heading": heading,
                "suggested_outline": outline,
                "reason": "Topic-model gap for an informational styling article, labeled as semantic_gap when competitors do not already use this H2.",
            })

    rows.sort(key=lambda item: (0 if item["importance"] == "high" else 1, -len(item.get("covered_by_competitors") or [])))
    if {"hoodie"} <= kw_tokens and ({"style", "outfit"} & kw_tokens):
        recommended = list(_DEFAULT_OUTLINE)
    else:
        your_h2 = [h for h in ((yours or {}).get("h2_headings") or [])[:3] if not _BOILER_HEADING.search(h or "")]
        recommended = (your_h2 or ["Introduction"]) + [r["recommended_heading"] for r in rows[:8]]
        if "Frequently asked questions" not in recommended:
            recommended.append("Frequently asked questions")
    recommended = [h for h in recommended if not _BOILER_HEADING.search(h)]
    return {
        "table": rows[:16],
        "recommended_outline": recommended[:12],
        "note": "Recommendations are for a more useful original article, not a copy of competitor titles or product pages.",
    }


def citation_opportunities(
    keyword: str,
    yours: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> dict[str, Any]:
    text = (
        (yours or {}).get("full_text")
        or (yours or {}).get("text")
        or (yours or {}).get("source_markdown")
        or ""
    ).lower()
    heads = " ".join(
        list((yours or {}).get("h2_headings") or [])
        + list((yours or {}).get("h1_headings") or [])
        + [(yours or {}).get("title") or ""]
        + [(yours or {}).get("h1") or ""]
    ).lower()
    blob = f"{text} {heads}"
    items = []

    def add(question: str, fmt: str, location: str, present: bool, evidence: str) -> None:
        items.append({
            "keyword_or_question": question,
            "recommended_answer": f"Give a 40–60 word standalone answer for “{question}”.",
            "required_evidence": evidence,
            "format": fmt,
            "citation_potential": 82 if present else 70,
            "location": location,
            "status": "existing" if present else "missing",
        })

    topic = (keyword or (yours or {}).get("title") or "this topic").strip()
    add(f"What is {topic}?", "definition", "Opening", bool(re.search(r"\bis\b|\bare\b", blob[:800])), "First-hand definition, not a copied blurb")
    add(f"How do I start with {topic}?", "step-by-step list", "How-to section", bool(re.search(r"\b(step|first|then|how to)\b", blob)), "Concrete steps from experience")
    add("How much does it cost?", "table or numbered facts", "Early H2", bool(re.search(r"\b(cost|price|fee|\$|₹|rs)\b", blob)), "Named prices with date and source")
    faq = (yours or {}).get("faq") or {}
    add("FAQ the reader will ask", "FAQPage-ready Q&A", "FAQ block", int(faq.get("answered") or 0) > 0 or "?" in heads, "Answer in 2–4 sentences")
    has_stats = bool(re.search(r"\b\d{2,}\b", blob))
    add("A verifiable statistic", "quoted stat + source", "Proof paragraph", has_stats, "Link a primary source; never invent numbers")
    seen = {item["keyword_or_question"].lower() for item in items}
    for row in competitors or []:
        for heading in (row.get("h2_headings") or [])[:8]:
            if "?" not in heading and not re.match(r"^(how|what|why|when|where|which)\b", heading or "", re.I):
                continue
            key = heading.strip()
            if not key or key.lower() in seen:
                continue
            seen.add(key.lower())
            present = key.lower() in heads
            add(key, "direct answer", "New H2 or FAQ", present, "Answer in 40–60 words with one specific example")
            if len(items) >= 10:
                break

    unsupported = []
    if re.search(r"\b(studies show|experts say|research proves)\b", blob) and not re.search(r"https?://", ((yours or {}).get("source_markdown") or "")):
        unsupported.append("Claims like “studies show” without a named source — add a citation or remove the claim.")

    return {
        "items": items[:10],
        "existing": [i for i in items if i["status"] == "existing"],
        "missing": [i for i in items if i["status"] == "missing"],
        "unsupported_claims": unsupported,
        "disclaimer": "Citation potential is an on-page readiness estimate, not a prediction that ChatGPT or AI Overviews will cite the page. Never invent statistics or experts.",
    }


def traffic_reasons(
    yours: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
    your_scores: dict[str, Any],
    avg_scores: dict[str, Any],
) -> dict[str, Any]:
    reasons = []
    your_words = int((yours or {}).get("word_count") or 0)
    avg_words = 0
    if competitors:
        avg_words = int(sum(int(r.get("word_count") or 0) for r in competitors) / len(competitors))
    if avg_words and your_words and your_words + 300 < avg_words:
        reasons.append({
            "reason": "Shorter topical depth than ranking pages",
            "evidence": f"Your extract is {your_words} words vs competitor average {avg_words} (on-page extract, not traffic).",
            "severity": "High",
            "fix": "Cover missing H2s from the content-gap table with original examples.",
            "impact": "Better intent satisfaction on ranking pages",
            "difficulty": "Medium",
            "priority": 88,
        })
    seo_you = your_scores.get("seo")
    seo_avg = avg_scores.get("seo")
    try:
        seo_you_n = float(seo_you)
        seo_avg_n = float(seo_avg)
    except (TypeError, ValueError):
        seo_you_n = seo_avg_n = None
    if seo_you_n is not None and seo_avg_n is not None and seo_you_n + 8 < seo_avg_n:
        reasons.append({
            "reason": "Weaker on-page SEO checklist score",
            "evidence": f"Your SEO checklist {seo_you} vs competitor average {seo_avg}.",
            "severity": "High",
            "fix": "Use the SEO factor tips: H1 keyword, headings, FAQs, alt text.",
            "impact": "Improved on-page readiness, not a guaranteed rank lift",
            "difficulty": "Low",
            "priority": 84,
        })
    if not (yours or {}).get("schema_types"):
        reasons.append({
            "reason": "Little or no detected schema",
            "evidence": "JSON-LD @type was not found on your page extract.",
            "severity": "Medium",
            "fix": "Add Article and FAQPage JSON-LD that matches visible content.",
            "impact": "Clearer machine-readable answers",
            "difficulty": "Low",
            "priority": 70,
        })
    if not (yours or {}).get("updated_at"):
        reasons.append({
            "reason": "No trustworthy modified date detected",
            "evidence": "article:modified_time / JSON-LD dateModified was missing.",
            "severity": "Medium",
            "fix": "Publish a real update and expose modified_time in meta/JSON-LD.",
            "impact": "Freshness signal for users and extractors",
            "difficulty": "Low",
            "priority": 65,
        })
    reasons.append({
        "reason": "Off-page authority is unknown in this tool",
        "evidence": "Domain authority, backlinks, referring domains, and Core Web Vitals are Data unavailable (no third-party API).",
        "severity": "Low",
        "fix": "Pair this checklist with Search Console or a backlink tool you already have access to.",
        "impact": "Unknown here — do not treat on-page scores as traffic.",
        "difficulty": "Medium",
        "priority": 40,
    })
    return {
        "reasons": reasons[:7],
        "disclaimer": "These are possible on-page disadvantages, not verified traffic, rankings, or CTR. Estimates are approximate unless you connect first-party data.",
    }


def originality_report(yours: Optional[dict[str, Any]], competitors: list[dict[str, Any]]) -> dict[str, Any]:
    mine = (yours or {}).get("text") or (yours or {}).get("source_markdown") or ""
    if len(mine.split()) < 80:
        return {
            "score": None,
            "similarity_pct": None,
            "risk": UNAVAILABLE,
            "matches": [],
            "disclaimer": "Internal similarity check only. Not a definitive legal plagiarism determination. Review required if the extract is too short to compare.",
        }
    matches = []
    worst = 0.0
    for row in competitors:
        other = row.get("text") or row.get("snippet") or ""
        if len(other.split()) < 40:
            continue
        ratio = float(ngram_overlap_ratio(mine[:12000], other[:12000]))
        worst = max(worst, ratio)
        if ratio >= 0.08:
            matches.append({
                "url": row.get("url"),
                "domain": row.get("domain"),
                "similarity_pct": round(ratio * 100, 1),
                "note": "Possible similarity detected — review required.",
            })
    score = max(0, min(100, int(round(100 - worst * 140))))
    if worst >= 0.25:
        risk = "High risk"
    elif worst >= 0.12:
        risk = "Medium risk"
    else:
        risk = "Low risk"
    return {
        "score": score,
        "similarity_pct": round(worst * 100, 1),
        "risk": risk,
        "matches": matches[:6],
        "disclaimer": "Internal similarity check only. Possible similarity detected is n-gram overlap against analyzed competitor extracts. Review required. Not a definitive legal plagiarism determination.",
    }


def humanization_report(text: str) -> dict[str, Any]:
    if len((text or "").split()) < 40:
        return {
            "score": None,
            "status": "unavailable",
            "reason": "Article text could not be extracted.",
            "interpretation": "Writing-naturalness analysis — not definitive AI detection.",
            "metrics": {},
            "warnings": [],
            "ai_like_phrases": [],
            "improvements": [],
            "disclaimer": "This is not a claim that the text is or is not AI-generated.",
        }
    checks = humanization_checks(text or "")
    metrics = checks.get("metrics") or {}
    warnings = checks.get("warnings") or []
    filler = int(metrics.get("filler_phrase_count") or 0)
    score = 88
    score -= min(24, filler * 6)
    score -= min(16, len(warnings) * 4)
    score = max(20, min(100, score))
    found = [p for p in AI_FILLER_PHRASES if p in (text or "").lower()][:8]
    return {
        "score": score,
        "interpretation": "Writing-naturalness analysis — not definitive AI detection.",
        "metrics": metrics,
        "warnings": warnings[:8],
        "ai_like_phrases": found,
        "improvements": [
            "Replace stock transitions with a specific observation.",
            "Add one first-hand example or constraint.",
            "Vary sentence length in dense sections.",
        ],
        "disclaimer": "This is not a claim that the text is or is not AI-generated.",
    }


def action_plan(
    yours: Optional[dict[str, Any]],
    your_scores: dict[str, Any],
    keyword_gaps: dict[str, Any],
    gaps: dict[str, Any],
    readability: dict[str, Any],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add(priority: str, category: str, issue: str, action: str, impact: str, effort: str, related: str = "") -> None:
        items.append({
            "issue": issue,
            "category": category,
            "current_status": issue,
            "recommended_action": action,
            "implementation": action,
            "priority": priority,
            "estimated_impact": impact,
            "estimated_effort": effort,
            "related_gap": related,
        })

    if not (yours or {}).get("extract_ok"):
        add("Critical", "Extraction", "Your article text could not be extracted reliably",
            "Fix the live URL or paste the article; scores are not meaningful on placeholders.",
            "Unblocks every other check", "Low")
    seo = your_scores.get("seo")
    if isinstance(seo, int) and seo < 60:
        add("High Priority", "SEO", "On-page SEO checklist is behind ranking pages",
            "Apply the SEO factor tips: title, H1, headings, FAQ, alt text.",
            "On-page readiness", "Medium")
    for gap in (keyword_gaps.get("gaps") or {}).get("high-priority") or []:
        add("High Priority", "Keyword", f"Missing keyword topic: {gap.get('keyword')}",
            gap.get("recommended_action") or gap.get("recommendation") or "Cover the subtopic in a natural H2.",
            "Topical coverage", "Medium", gap.get("keyword") or "")
        if len([i for i in items if i["category"] == "Keyword"]) >= 4:
            break
    for row in (gaps.get("table") or [])[:3]:
        add("High Priority", "Content", f"Missing section: {row.get('missing_topic')}",
            f"Add H2 “{row.get('recommended_heading')}” with original examples.",
            "Completeness vs SERP", "Medium", row.get("missing_topic") or "")
    if (readability.get("score") or 100) < 55:
        add("Medium Priority", "Readability", "Dense sentences on the extracted article",
            "Shorten 25+ word sentences and add a 40–60 word answer block.",
            "Scanability", "Low")
    if not (yours or {}).get("schema_types"):
        add("Medium Priority", "AEO", "No JSON-LD schema detected",
            "Add Article/FAQPage markup that matches visible FAQs.",
            "Answer-engine readiness", "Low")
    add("Low Priority", "Off-page", "Authority and CWV not measured here",
        "Use Search Console / CrUX / a backlink tool you already pay for.",
        "Unknown in this app", "Medium")
    return items
