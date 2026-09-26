"""Content gaps, citation opportunities, traffic reasons, originality, action plan."""
from __future__ import annotations

import re
from typing import Any, Optional

from acl_agent.gsc_diagnosis import expected_ctr
from acl_agent.keywords import (
    article_intent,
    classify_page_intent,
    content_tokens,
    fold_phrase,
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
    contributing: set[str] = set()
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
            contributing.add(domain or row.get("url") or "")
    editorial_count = len(contributing)

    rows = []
    for heading, meta in covered.items():
        if any(_similar(heading, mine_h) for mine_h in mine):
            continue
        if heading.lower() in body:
            continue
        domains = meta["domains"]
        if (
            editorial_count >= 2
            and len(domains) < 2
            and not set(content_tokens(heading)) & set(content_tokens(keyword))
        ):
            continue
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

    rows.sort(key=lambda item: (0 if item["importance"] == "high" else 1, -len(item.get("covered_by_competitors") or [])))
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
            "interpretation": "Writing-naturalness analysis.",
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
        "interpretation": "Writing-naturalness analysis.",
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


_GENERIC_ALTS = {
    "hero", "image", "photo", "banner", "picture", "img", "graphic", "thumbnail",
    "untitled", "featured image", "blog image", "header image", "placeholder",
}
_FILE_ALT = re.compile(r"^(img|dsc|pxl|image|photo|screenshot|untitled)[\s_-]*\d*$|\.(jpe?g|png|webp|gif|avif)$", re.I)
ALT_MAX_CHARS = 125


def _generic_alt(alt: str) -> bool:
    lowered = alt.lower().strip()
    if lowered in _GENERIC_ALTS or _FILE_ALT.search(lowered):
        return True
    return " " not in lowered and ("-" in lowered or "_" in lowered)


def _suggest_alt(image: dict[str, Any]) -> tuple[str, str]:
    caption = image.get("caption") or ""
    words = image.get("filename_words") or []
    if caption:
        base, basis = caption, "caption"
    elif len(words) >= 2:
        base, basis = " ".join(words).capitalize(), "file name"
    else:
        return "", ""
    if len(base) > ALT_MAX_CHARS:
        base = base[:ALT_MAX_CHARS].rsplit(" ", 1)[0]
    return base, basis


def _image_filename(src: str) -> str:
    return (src or "").split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1][:80]


def image_alt_report(
    yours: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
    keyword: str = "",
) -> dict[str, Any]:
    """Per-image alt-text issues for your article plus how competitors use images."""
    if not yours:
        return {"status": "unavailable", "reason": "Add a blog URL to audit its images.", "items": [], "recommendations": []}
    images = list(yours.get("images") or [])
    kw = " ".join(content_tokens(keyword))
    alt_counts: dict[str, int] = {}
    for image in images:
        key = image.get("alt", "").lower().strip()
        if key:
            alt_counts[key] = alt_counts.get(key, 0) + 1
    with_kw = [
        image for image in images
        if kw and kw in " ".join(content_tokens(image.get("alt") or ""))
    ]
    stuffing = len(with_kw) >= 3 and len(with_kw) > len(images) / 2
    summary = {key: 0 for key in ("total", "ok", "missing", "empty", "generic", "too_long", "stuffed", "duplicate", "decorative")}
    summary["total"] = len(images)
    items: list[dict[str, Any]] = []
    seen_kw = 0
    for image in images:
        alt = image.get("alt") or ""
        issue, severity, kind = "", "", ""
        if image.get("decorative") and not alt:
            summary["decorative"] += 1
            continue
        if not image.get("has_alt_attr"):
            issue, severity, kind = "No alt attribute", "high", "missing"
        elif not alt:
            issue, severity, kind = "Empty alt (only right for purely decorative images)", "medium", "empty"
        elif _generic_alt(alt):
            issue, severity, kind = "Generic or file-name alt text", "high", "generic"
        elif len(alt) > ALT_MAX_CHARS:
            issue, severity, kind = f"Longer than {ALT_MAX_CHARS} characters", "low", "too_long"
        elif stuffing and image in with_kw:
            seen_kw += 1
            if seen_kw > 1:
                issue, severity, kind = "Target keyword repeated across most alts", "medium", "stuffed"
        if not issue and alt and alt_counts.get(alt.lower().strip(), 0) > 1:
            issue, severity, kind = "Same alt text as another image", "low", "duplicate"
        if not issue:
            summary["ok"] += 1
            continue
        summary[kind] += 1
        suggestion, basis = _suggest_alt(image)
        items.append({
            "src": image.get("src") or "",
            "filename": _image_filename(image.get("src") or ""),
            "section": image.get("section") or "",
            "alt": alt,
            "issue": issue,
            "severity": severity,
            "suggested_alt": suggestion or (alt[:ALT_MAX_CHARS].rsplit(" ", 1)[0] if kind == "too_long" else ""),
            "suggestion_basis": basis,
        })
    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: order.get(item["severity"], 3))

    comp_pages = [
        row for row in competitors
        if not row.get("intent_mismatch") and not row.get("topic_mismatch") and row.get("images") is not None
    ]
    comp_summary = None
    if comp_pages:
        counts = [len(row.get("images") or []) for row in comp_pages]
        described = []
        for row in comp_pages:
            imgs = [img for img in row.get("images") or [] if not img.get("decorative")]
            if imgs:
                good = sum(1 for img in imgs if img.get("alt") and not _generic_alt(img["alt"]))
                described.append(good / len(imgs) * 100)
        comp_summary = {
            "pages": len(comp_pages),
            "avg_images": round(sum(counts) / len(counts), 1),
            "avg_descriptive_pct": round(sum(described) / len(described)) if described else None,
        }

    recs: list[str] = []
    fix_n = summary["missing"] + summary["generic"] + summary["empty"]
    if fix_n:
        recs.append(
            f"Write descriptive alt text for {fix_n} image{'s' if fix_n != 1 else ''}: "
            "say what the image shows in one short sentence."
        )
    if stuffing:
        recs.append(f"Use “{keyword}” in at most one alt (the main image) and describe the rest plainly.")
    if summary["too_long"]:
        recs.append(f"Trim {summary['too_long']} alt text(s) to under {ALT_MAX_CHARS} characters.")
    if comp_summary and comp_summary["avg_images"] - len(images) >= 3:
        pictured = {image.get("section") for image in images}
        bare = [h for h in (yours.get("h2_headings") or []) if h not in pictured][:3]
        tail = f" Candidates: {', '.join('“' + h + '”' for h in bare)}." if bare else ""
        recs.append(
            f"Competitors average {comp_summary['avg_images']:g} article images; you have {len(images)}. "
            f"Add original photos or diagrams to sections without one.{tail}"
        )
    if not images:
        recs.append("Your article has no images. Add at least one original image near the top with descriptive alt text.")
    return {
        "status": "ok",
        "reason": None,
        "summary": summary,
        "items": items[:20],
        "competitors": comp_summary,
        "recommendations": recs[:4],
        "note": "Suggested alt text is drafted from the image caption or file name. Check it matches what the image actually shows.",
    }


def action_plan(
    yours: Optional[dict[str, Any]],
    your_scores: dict[str, Any],
    keyword_gaps: dict[str, Any],
    gaps: dict[str, Any],
    readability: dict[str, Any],
    images: Optional[dict[str, Any]] = None,
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
    targeting = your_scores.get("keyword_targeting_score")
    technical = your_scores.get("onpage_technical_score")
    if isinstance(seo, int) and seo < 60:
        split_note = ""
        if targeting is not None or technical is not None:
            split_note = f" Keyword targeting {targeting}; on-page technical {technical}."
        add("High Priority", "SEO", "On-page SEO checklist is behind ranking pages",
            "Apply the SEO factor tips: title, H1, headings, FAQ, alt text." + split_note,
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
    summary = (images or {}).get("summary") or {}
    alt_fixes = summary.get("missing", 0) + summary.get("generic", 0) + summary.get("empty", 0)
    if alt_fixes:
        add("Medium Priority", "Images", f"{alt_fixes} of {summary.get('total', 0)} article images lack descriptive alt text",
            "Describe what each image shows in one short sentence; see the Images & alt text section for drafts.",
            "Image search and accessibility", "Low")
    if not (yours or {}).get("schema_types"):
        add("Medium Priority", "AEO", "No JSON-LD schema detected",
            "Add Article/FAQPage markup that matches visible FAQs.",
            "Answer-engine readiness", "Low")
    add("Low Priority", "Off-page", "Authority and CWV not measured here",
        "Use Search Console / CrUX / a backlink tool you already pay for.",
        "Unknown in this app", "Medium")
    return items


def _mentions_phrase(haystack: str, phrase: str) -> bool:
    if not haystack or not phrase:
        return False
    folded_h, folded_p = fold_phrase(haystack), fold_phrase(phrase)
    if folded_p and folded_p in folded_h:
        return True
    tokens = set(content_tokens(phrase))
    return bool(tokens) and tokens <= set(content_tokens(haystack))


def build_verdict_summary(
    diagnosis_summary: Optional[dict[str, Any]] = None,
    focus: Optional[dict[str, Any]] = None,
    keyword_mismatch: Optional[dict[str, Any]] = None,
    gsc: Optional[dict[str, Any]] = None,
    page: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Observed facts, areas to check, and verification steps — not a single cause."""
    diagnosis_summary = diagnosis_summary or {}
    focus = focus or {}
    gsc = gsc or {}
    page = page or {}
    targeting = gsc.get("keyword_targeting") or {}
    index = gsc.get("index_status") or {}
    observed: list[str] = []
    checks: list[str] = []
    verify: list[str] = []

    if index.get("source") == "url_inspection":
        coverage = index.get("coverage_state") or index.get("label") or "URL Inspection"
        crawl = f" Last crawl {index['last_crawl']}." if index.get("last_crawl") else ""
        observed.append(f"Google index: {index.get('label') or coverage} ({coverage}).{crawl}")
    elif index.get("source") == "robots_only":
        robots_note = index.get("robots_status") or "unknown"
        observed.append(
            f"Google index: Inspection unavailable. Page robots is {robots_note} — that is not a Google index check."
        )
        if index.get("impressions_hint"):
            observed.append(str(index["impressions_hint"]))
    elif index:
        observed.append("Google index: Inspection unavailable.")

    drop_pct = diagnosis_summary.get("delta_pct")
    if isinstance(drop_pct, (int, float)):
        observed.append(f"Impressions changed {drop_pct:+.1f}% versus the previous period.")
    elif diagnosis_summary.get("text"):
        observed.append(str(diagnosis_summary["text"]).split(".")[0] + ".")

    ours = list(focus.get("our_blog") or [])
    best = ours[0] if ours and focus.get("our_blog_basis") == "search_console" else None
    query = ""
    if best and best.get("keyword"):
        query = str(best["keyword"])
        evidence = str(best.get("evidence") or "")
        pos_match = re.search(r"avg position\s+([\d.]+)", evidence, re.I)
        rank_bit = f" at average position {pos_match.group(1)}" if pos_match else ""
        observed.append(f"Search Console already shows demand for “{query}”{rank_bit}.")
        title = str(page.get("title") or "")
        h1 = str(page.get("h1") or (page.get("h1_headings") or [""])[0] or "")
        targets_best = _mentions_phrase(title, query) or _mentions_phrase(h1, query)
        if targets_best:
            observed.append("Title and H1 already mention that query.")
        else:
            observed.append("Title and H1 do not mention that query.")

    if not observed:
        observed.append("No Search Console verdict is available yet. Use the action plan from the on-page extract.")

    if isinstance(drop_pct, (int, float)) and drop_pct <= -30:
        checks.extend(["Ranking decline", "Indexing", "Seasonality", "Competitor changes", "SERP changes"])
    if diagnosis_summary.get("seasonal_caveat"):
        if "Seasonality" not in checks:
            checks.append("Seasonality")
    if keyword_mismatch or targeting.get("mismatch") or (gsc.get("title") or {}).get("issues") or (gsc.get("h1") or {}).get("issues"):
        if "Title/H1 vs ranking query" not in checks:
            checks.append("Title/H1 vs ranking query")
    indexing = (gsc.get("indexing") or {})
    if indexing.get("status") == "noindex" or index.get("robots_status") == "noindex":
        checks.append("noindex on the live URL")
    if index.get("indexed") is False:
        if "Indexing" not in checks:
            checks.append("Indexing")
    if not checks:
        checks.append("On-page extract vs the target keyword")

    if index.get("source") == "url_inspection" and index.get("coverage_state"):
        verify.append(f"URL Inspection already returned: {index['coverage_state']}")
    else:
        verify.append("Check URL indexing in Search Console")
        verify.append("Check Search Console coverage for this URL")
    year_ago = (gsc.get("comparisons") or {}).get("year_ago") or {}
    if year_ago.get("status") != "ok":
        verify.append("Compare a shorter window or wait for year-over-year data (16-month Search Console limit)")
    else:
        verify.append("Compare the year-ago Search Console window already in this report")

    confidence = str(diagnosis_summary.get("confidence") or "").strip()
    text_parts = list(observed)
    if confidence:
        extra = f"Confidence in the sample is {confidence}"
        if diagnosis_summary.get("seasonal_caveat"):
            extra += "; year-over-year data is unavailable, so treat seasonality as a hypothesis"
        text_parts.append(extra + ".")
    return {
        "text": " ".join(text_parts),
        "confidence": confidence or None,
        "seasonal_caveat": bool(diagnosis_summary.get("seasonal_caveat")),
        "observed": observed,
        "areas_to_check": checks,
        "verification": verify,
    }


def merged_content_opportunities(
    new_topics: Optional[list[dict[str, Any]]] = None,
    content_gaps: Optional[dict[str, Any]] = None,
    gsc_queries: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Display merge of keyword-gap phrases and heading-gap rows. Does not change detectors."""
    topics = list(new_topics or [])
    headings = list((content_gaps or {}).get("table") or [])
    items: list[dict[str, Any]] = []

    def importance_rank(value: str) -> int:
        return {"high": 0, "medium": 1, "low": 2}.get((value or "").lower(), 3)

    for row in topics:
        phrase = str(row.get("keyword") or "").strip()
        if not phrase:
            continue
        items.append({
            "topic": phrase,
            "sources": ["keyword_gap"],
            "covered_by": row.get("evidence") or "",
            "importance": "medium",
            "intent": "",
            "recommended_heading": phrase,
        })
    for row in headings:
        heading = str(row.get("missing_topic") or row.get("recommended_heading") or "").strip()
        if not heading:
            continue
        match = next(
            (
                item for item in items
                if _similar(heading, item["topic"])
                or relevance_score(heading, item["topic"]) >= 0.55
            ),
            None,
        )
        if match:
            if "heading_gap" not in match["sources"]:
                match["sources"].append("heading_gap")
            if row.get("covered_by") and row.get("covered_by") != UNAVAILABLE:
                match["covered_by"] = row.get("covered_by")
            if importance_rank(str(row.get("importance") or "")) < importance_rank(match["importance"]):
                match["importance"] = row.get("importance") or match["importance"]
            continue
        items.append({
            "topic": heading,
            "sources": ["heading_gap"],
            "covered_by": row.get("covered_by") or "",
            "importance": row.get("importance") or "medium",
            "intent": row.get("search_intent") or row.get("intent") or "",
            "recommended_heading": row.get("recommended_heading") or heading,
        })
    items.sort(key=lambda item: (
        importance_rank(item["importance"]),
        0 if len(item["sources"]) > 1 else 1,
        item["topic"].lower(),
    ))
    for item in items:
        _annotate_opportunity(item, gsc_queries or [])
    return {
        "table": items,
        "note": "Merged from keyword-gap phrases and competitor headings. Raw new_topics and content_gaps stay in the response.",
    }


def _competitor_breadth(covered_by: str) -> int:
    blob = str(covered_by or "")
    match = re.search(r"used by\s+(\d+)", blob, re.I)
    if match:
        return int(match.group(1))
    parts = [part.strip() for part in re.split(r"[,;]", blob) if part.strip() and part.strip() != UNAVAILABLE]
    return len(parts)


def _related_gsc_query(phrase: str, queries: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for row in queries or []:
        other = str(row.get("query") or "")
        if not other:
            continue
        if _similar(phrase, other) or relevance_score(phrase, other) >= 0.45:
            return row
    return None


def _annotate_opportunity(item: dict[str, Any], queries: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Labels only: why, confidence, coverage class. Does not change detectors."""
    topic = str(item.get("topic") or "")
    related = _related_gsc_query(topic, queries or [])
    breadth = _competitor_breadth(str(item.get("covered_by") or ""))
    importance = str(item.get("importance") or "medium").lower()
    rel = item.get("relevance_score")
    if rel is None and topic:
        rel = 0.5 if "keyword_gap" in (item.get("sources") or []) else 0.4
    why = []
    if breadth:
        why.append(f"{breadth} competitor page(s) cover this topic")
    if topic:
        why.append("Current page does not already use this heading or phrase")
    if related:
        pos = related.get("position")
        pos_bit = f" (avg position {float(pos):.1f})" if isinstance(pos, (int, float)) else ""
        why.append(f"Related Search Console query “{related.get('query')}” already has impressions{pos_bit}")
    if not why:
        why.append("Shown because a competitor heading or keyword-gap phrase matched the existing filters")

    if related and (rel or 0) >= 0.35:
        coverage = "must"
        confidence = "high"
    elif breadth >= 2 and (rel or 0) >= 0.35:
        coverage = "recommended"
        confidence = "medium"
    elif (rel or 0) < 0.35 or importance == "low":
        coverage = "skip"
        confidence = "low"
    else:
        coverage = "optional"
        confidence = "low"

    item["why"] = why
    item["recommendation_confidence"] = confidence
    item["coverage_class"] = coverage
    item["gsc_related_query"] = (related or {}).get("query")
    return item


def _impact_band(priority: str, estimated_impact: str = "") -> str:
    blob = f"{priority} {estimated_impact}".lower()
    if re.search(r"\b\d+\s*clicks?\b|\bforecast\b|\b~", blob):
        estimated_impact = ""
    if "critical" in blob or blob.startswith("high"):
        return "High"
    if blob.startswith("medium"):
        return "Medium"
    return "Low"


def annotate_actions(
    plan: list[dict[str, Any]],
    gsc: Optional[dict[str, Any]] = None,
    fallback_scores: Optional[dict[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Attach why / confidence / coverage class to existing action rows."""
    gsc = gsc or {}
    targeting = gsc.get("keyword_targeting") or {}
    fallback = (fallback_scores or {}).get("confidence") == "low" and (fallback_scores or {}).get("status") == "ok"
    queries = list(gsc.get("queries") or [])
    out = []
    for raw in plan or []:
        item = dict(raw)
        category = str(item.get("category") or "")
        why = []
        coverage = "recommended"
        confidence = "medium"
        if category in {"Title", "H1", "Meta"} and (targeting.get("mismatch") or targeting.get("primary_ranking_query")):
            why.append("Search Console’s strongest query differs from the title/H1 extract")
            coverage = "must"
            confidence = "high"
        elif category == "Indexing":
            why.append("Extracted robots/indexing status says this URL is noindex")
            coverage = "must"
            confidence = "high"
        elif category in {"Keyword", "Content"}:
            related = _related_gsc_query(str(item.get("related_gap") or item.get("issue") or ""), queries)
            if related:
                why.append(f"Related Search Console query “{related.get('query')}” already has impressions")
                coverage = "must"
                confidence = "high"
            else:
                why.append("A competitor heading or keyword-gap phrase is missing from your page")
                coverage = "recommended"
                confidence = "medium"
        elif category == "Images":
            why.append("Extracted images are missing descriptive alt text")
            coverage = "recommended"
            confidence = "high"
        elif category == "Off-page":
            why.append("This app does not measure authority or Core Web Vitals")
            coverage = "skip"
            confidence = "low"
        else:
            why.append(str(item.get("issue") or "On-page checklist finding"))
        if fallback and category == "SEO":
            confidence = "low"
            why.append("Checklist used a fallback scorer")
        item["why"] = why
        item["recommendation_confidence"] = confidence
        item["coverage_class"] = coverage
        original_impact = str(item.get("estimated_impact") or "")
        if re.search(r"\b\d+\s*clicks?\b|\bforecast\b", original_impact, re.I):
            item["impact_note"] = "Not a traffic forecast. " + original_impact
            item["estimated_impact"] = _impact_band(str(item.get("priority") or ""), "")
        else:
            item["impact_note"] = original_impact
            item["estimated_impact"] = _impact_band(str(item.get("priority") or ""), original_impact)
        out.append(item)
    return out


def quick_wins(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wins = []
    for item in plan or []:
        if str(item.get("estimated_effort") or "").lower() != "low":
            continue
        if str(item.get("coverage_class") or "") == "skip":
            continue
        if str(item.get("category") or "") == "Off-page":
            continue
        wins.append(item)
    return wins[:6]


def gsc_query_opportunities(gsc: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Bucket existing Search Console queries by current position. No new API calls."""
    rows = [
        row for row in ((gsc or {}).get("queries") or [])
        if row.get("query") and not row.get("branded")
    ]
    buckets = {"quick_wins": [], "page_two": [], "content": []}
    for row in rows:
        try:
            position = float(row.get("position") or 0)
        except (TypeError, ValueError):
            continue
        item = {
            "query": row.get("query"),
            "position": position,
            "impressions": row.get("impressions"),
            "clicks": row.get("clicks"),
        }
        if 4 <= position <= 10:
            buckets["quick_wins"].append(item)
        elif 10 < position <= 20:
            buckets["page_two"].append(item)
        elif 20 < position <= 50:
            buckets["content"].append(item)
    for key in buckets:
        buckets[key] = sorted(buckets[key], key=lambda item: item["position"])[:8]
    return {
        **buckets,
        "note": "Current Search Console positions for this URL, not a traffic forecast.",
    }


def ctr_checklist(gsc: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Possible CTR checks from extract + GSC. Does not claim SERP features."""
    gsc = gsc or {}
    impressions = gsc.get("impressions")
    ctr = gsc.get("ctr")
    position = gsc.get("position")
    targeting = gsc.get("keyword_targeting") or {}
    intent = "informational"
    split = gsc.get("intent_split") or {}
    if split:
        intent = max(split.items(), key=lambda pair: pair[1])[0]
    expected = expected_ctr(position, intent) if isinstance(position, (int, float)) else None
    gap = (
        isinstance(impressions, (int, float))
        and impressions >= 100
        and isinstance(ctr, (int, float))
        and expected is not None
        and ctr < expected * 0.55
    )
    checks = []
    if targeting.get("mismatch") or not targeting.get("in_title"):
        checks.append("Title does not match the ranking query")
    meta = gsc.get("meta") or {}
    if meta.get("issues"):
        checks.append("Meta description is thin or missing from the extract")
    if isinstance(position, (int, float)) and position > 10:
        checks.append(f"Average position is {position:.1f} (outside page one)")
    if not checks:
        checks.append("Compare the live snippet in Search Console; this app does not see SERP features or ads")
    observed = ""
    if isinstance(ctr, (int, float)) and isinstance(impressions, (int, float)):
        pos_bit = f" at average position {position:.1f}" if isinstance(position, (int, float)) else ""
        observed = f"CTR {ctr:.1%} from {int(impressions)} impressions{pos_bit}."
        if expected is not None:
            observed += f" Intent baseline for {intent} at this position is about {expected:.0%} (checklist, not a forecast)."
    return {
        "status": "gap" if gap else ("ok" if observed else "unavailable"),
        "observed": observed,
        "possible_checks": checks if gap else [],
        "note": "Possible on-page checks only. Not a click forecast and not a SERP-feature diagnosis.",
    }


# Word-count sentence: yours >= 200 words, competitor >= 1.5x and at least +400 words.
# Technical sentence: on-page technical sub-score lead of 15+ points.
# Signal sentence: a positive competitor signal your page does not already have.
_VS_YOU_WORD_RATIO = 1.5
_VS_YOU_WORD_MIN_YOURS = 200
_VS_YOU_WORD_MIN_DELTA = 400
_VS_YOU_TECH_GAP = 15


def competitor_difference(
    yours: Optional[dict[str, Any]],
    your_scores: Optional[dict[str, Any]],
    competitor: Optional[dict[str, Any]],
    yours_signals: Optional[list[dict[str, Any]]] = None,
) -> Optional[str]:
    """One sentence for the largest existing gap vs your page. None if nothing stands out."""
    yours = yours or {}
    your_scores = your_scores or {}
    competitor = competitor or {}
    yours_labels = {
        str(item.get("label") or "").strip().lower()
        for item in (yours_signals or [])
        if item.get("kind") in {"positive", "good"} and item.get("label")
    }
    candidates: list[tuple[float, str]] = []

    yours_words = int(yours.get("word_count") or 0)
    theirs_words = int(competitor.get("word_count") or 0)
    if (
        yours_words >= _VS_YOU_WORD_MIN_YOURS
        and theirs_words >= int(yours_words * _VS_YOU_WORD_RATIO)
        and theirs_words - yours_words >= _VS_YOU_WORD_MIN_DELTA
    ):
        ratio = theirs_words / yours_words
        candidates.append((ratio, f"{theirs_words:,} words ({ratio:.1f}x yours)"))

    yours_tech = your_scores.get("onpage_technical_score")
    theirs_tech = (competitor.get("scores") or {}).get("onpage_technical_score")
    if isinstance(yours_tech, int) and isinstance(theirs_tech, int) and theirs_tech - yours_tech >= _VS_YOU_TECH_GAP:
        candidates.append(((theirs_tech - yours_tech) / _VS_YOU_TECH_GAP, f"on-page technical SEO {theirs_tech} vs your {yours_tech}"))

    if int(competitor.get("table_count") or 0) >= 1 and int(yours.get("table_count") or 0) == 0:
        candidates.append((1.4, "an on-page table you do not have"))

    for item in competitor.get("signals") or []:
        label = str(item.get("label") or "").strip()
        if item.get("kind") not in {"positive", "good"} or not label:
            continue
        if label.lower() in yours_labels:
            continue
        candidates.append((1.2, label[0].lower() + label[1:] if label[0].isupper() else label))
        break

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    lead = candidates[0][1]
    extra = next((pair[1] for pair in candidates[1:] if pair[0] >= 1.2), None)
    sentence = lead[0].upper() + lead[1:]
    if extra:
        sentence += f" and {extra}"
    return sentence + "."
