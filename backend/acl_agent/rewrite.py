"""
ACL Blog Agent - rewrite an existing article.

Takes a source article plus optional style controls and produces a
new, original HTML article that keeps the same facts.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from urllib.parse import urlparse

from acl_agent.config import BRAND_NAME, BRAND_SITE, logger
from acl_agent.generation import (
    extract_outline_from_markdown,
    generate_single_call_article,
)
from acl_agent.models import ContentBrief, InternalLink, SEOAnalysis
from acl_agent.scoring import score_article
from acl_agent.validation import count_h1, keyword_count, word_count


def _plain_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _guess_title(source: str, title: Optional[str]) -> str:
    if title and len(title.strip()) >= 5:
        return title.strip()[:200]

    match = re.search(
        r"<h1\b[^>]*>(.*?)</h1>",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        heading = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if len(heading) >= 5:
            return heading[:200]

    match = re.search(r"^#\s+(.+)$", source, flags=re.MULTILINE)
    if match and len(match.group(1).strip()) >= 5:
        return match.group(1).strip()[:200]

    first = _plain_text(source)[:80].strip(" .,-")
    if len(first) >= 5:
        return first[:200]
    return "Rewritten Blog Article"


def _guess_keyword(source: str, keyword: Optional[str], title: str) -> str:
    if keyword and len(keyword.strip()) >= 2:
        return keyword.strip()[:200]
    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", title)
    if len(words) >= 2:
        return " ".join(words[:6]).lower()
    if words:
        return words[0].lower()
    fallback = _plain_text(source).split()[:4]
    phrase = " ".join(fallback).strip()
    return phrase[:200] if len(phrase) >= 2 else "blog article"


def _normalize_internal_suggestions(
    items: list[Any],
    website: str,
) -> list[InternalLink]:
    site = (website or "https://example.com").rstrip("/")
    out: list[InternalLink] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        topic = " ".join(
            str(
                item.get("topic")
                or item.get("anchor_text")
                or item.get("reason")
                or ""
            ).split()
        )
        if len(topic) < 3:
            continue
        key = topic.lower()
        if key in seen:
            continue
        seen.add(key)
        anchor = str(item.get("anchor_text") or topic)[:200]
        reason = str(item.get("reason") or "").strip()
        if "link to your page about" not in reason.lower():
            reason = f"Link to your page about {topic}" + (f". {reason}" if reason else "")
        out.append(
            InternalLink(
                url=f"{site}/",
                anchor_text=anchor,
                reason=reason[:300],
            )
        )
        if len(out) >= 8:
            break
    return out


def _normalize_external_suggestions(items: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        raw = str(
            item.get("url") or item.get("source_type") or item.get("source") or ""
        ).strip()
        reason = str(item.get("reason") or "").strip()
        if not raw and not reason:
            continue
        label = raw
        if raw.lower().startswith("http"):
            parsed = urlparse(raw)
            host = (parsed.netloc or "").lower()
            if host.endswith(".gov") or host.endswith(".edu"):
                label = f"{parsed.scheme}://{host}/"
            elif host:
                label = host
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "url": (label or "authoritative industry source")[:300],
            "reason": (reason or "Relevant supporting source for this topic")[:300],
        })
        if len(out) >= 4:
            break
    return out


def _build_implementation_checklist(
    seo_analysis: SEOAnalysis,
    stats: dict[str, Any],
) -> dict[str, list[str]]:
    critical: list[str] = []
    high: list[str] = []
    medium: list[str] = []
    low: list[str] = []
    if seo_analysis.meta_title or seo_analysis.meta_description:
        critical.append("Publish new title/meta")
    if (stats.get("h1_count") or 0) != 1:
        high.append("Keep a single H1 on the published page")
    if seo_analysis.faqs:
        high.append("Add FAQPage schema")
    if seo_analysis.internal_links:
        high.append("Place suggested internal links in the live article")
    if seo_analysis.alt_texts:
        medium.append("Apply ALT texts to images")
    if seo_analysis.external_source_suggestions:
        medium.append("Cite suggested external sources where claims need support")
    if (stats.get("keyword_count") or 0) == 0:
        medium.append("Mention the primary keyword in the opening section")
    if (stats.get("word_count") or 0) >= 800:
        low.append("Spot-check word count against ranking pages before publish")
    else:
        low.append("Expand thin sections before publish")
    return {
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low,
    }


def _build_priority(scores: dict[str, Any]) -> str:
    overall = scores.get("overall")
    if overall is None and isinstance(scores.get("seo"), dict):
        parts = [
            int((scores.get(key) or {}).get("score") or 0)
            for key in ("seo", "geo", "aeo")
        ]
        overall = round(sum(parts) / 3) if parts else 0
    value = int(overall or 0)
    if value < 50:
        return "High"
    if value <= 75:
        return "Medium"
    return "Low"


def _build_expected_impact(
    seo_analysis: SEOAnalysis,
    scores: dict[str, Any],
    stats: dict[str, Any],
    source_words: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if seo_analysis.faqs:
        rows.append({
            "change": "FAQ answers added",
            "mechanism": "Direct Q&A matches People Also Ask phrasing",
            "expected_effect": "Stronger AEO / featured-snippet eligibility",
        })
    rewritten_words = int(stats.get("word_count") or 0)
    if source_words and rewritten_words > source_words:
        rows.append({
            "change": "Draft is longer than the source",
            "mechanism": "More of the topic is covered than the original page",
            "expected_effect": "Better topical depth versus the source article",
        })
    if seo_analysis.internal_links:
        rows.append({
            "change": "Internal link suggestions",
            "mechanism": "Pass relevance to related pages on your own site",
            "expected_effect": "Clearer site architecture for search crawlers",
        })
    if seo_analysis.external_source_suggestions:
        rows.append({
            "change": "Authoritative source suggestions",
            "mechanism": "Cite trusted publishers where facts need backup",
            "expected_effect": "Higher trust for GEO citation and editorial review",
        })
    if seo_analysis.meta_title or seo_analysis.meta_description:
        rows.append({
            "change": "New title and meta description",
            "mechanism": "On-page metadata restated around the target keyword",
            "expected_effect": "Clearer SERP snippet targeting",
        })
    if not rows:
        rows.append({
            "change": "Editorial rewrite",
            "mechanism": "Wording and structure changed without inventing facts",
            "expected_effect": "A cleaner page to publish and score again",
        })
    return rows[:6]


def rewrite_article(
    source_article: str,
    keyword: Optional[str] = None,
    title: Optional[str] = None,
    tone: str = "friendly",
    target_word_count: Optional[int] = None,
    point_of_view: Optional[str] = None,
    readability: Optional[str] = None,
    brand_voice: Optional[str] = None,
    language: str = "en-US",
    brand_name: Optional[str] = None,
    website: Optional[str] = None,
    audience: Optional[str] = None,
    additional_instructions: str = "",
    include_faq: bool = True,
    include_takeaways: bool = True,
    include_conclusion: bool = True,
    include_tables: bool = False,
    include_h3: bool = True,
    include_lists: bool = True,
    include_quotes: bool = False,
    on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    source = (source_article or "").strip()
    if len(source) < 200:
        raise ValueError("Source article must be at least 200 characters.")

    _brand = (brand_name or BRAND_NAME or "Blog Agent").strip() or "Blog Agent"
    _site = (website or BRAND_SITE or "https://example.com").rstrip("/")
    resolved_title = _guess_title(source, title)
    resolved_keyword = _guess_keyword(source, keyword, resolved_title)
    source_words = word_count(source) or 800
    target = target_word_count or max(300, min(8000, source_words))

    def emit(event_type: str, **payload: Any) -> None:
        if on_event:
            on_event(event_type, payload)

    logger.info("=== Rewrite: '%s' ===", resolved_title)
    emit(
        "stage",
        stage="parse",
        status="running",
        message="Reading the source article...",
    )

    structure_notes = []
    if include_faq:
        structure_notes.append("Include a FAQ section (3–5 questions).")
    if include_takeaways:
        structure_notes.append("Include a Key Takeaways section.")
    if include_conclusion:
        structure_notes.append("End with a practical conclusion.")
    if include_h3:
        structure_notes.append("Use H3 subheadings under H2 sections.")
    else:
        structure_notes.append("Do not use H3 subheadings.")
    if include_lists:
        structure_notes.append(
            "Use numbered lists for steps and bullet lists for features."
        )
    if include_tables:
        structure_notes.append("Include at least one HTML comparison table.")
    if include_quotes:
        structure_notes.append("Include a blockquote where it helps.")

    extra = additional_instructions.strip()
    instructions = f"""REWRITE TASK
Rewrite the SOURCE ARTICLE as a new, original, publish-ready piece.
Keep the same facts, products, names, and claims. Do not invent
statistics, quotes, or testimonials.
Change wording, sentence rhythm, and section structure so this is
not a close paraphrase of the original.
Tone: {tone}. Language: {language}.
{"Audience: " + audience.strip() if audience and audience.strip() else ""}
{"Point of view: " + point_of_view if point_of_view else ""}
{"Readability: " + readability if readability else ""}
{"Brand voice: " + brand_voice.strip() if brand_voice and brand_voice.strip() else ""}

STRUCTURE
{chr(10).join("- " + note for note in structure_notes)}

{("ADDITIONAL INSTRUCTIONS" + chr(10) + extra) if extra else ""}

LINK AND SOURCE SUGGESTIONS
Also return internal_links and external_source_suggestions in the JSON.
Internal links: suggest destinations on {_site} as
"link to your page about X" in the reason. Do not invent exact paths.
External sources: 2–4 items. Prefer .gov, .edu, or well-known industry
domains. If you cannot be sure a specific URL is live, return the
source type or domain only — never a fabricated article URL.
""".strip()

    brief = ContentBrief(
        brand_name=_brand,
        website=_site,
        primary_keyword=resolved_keyword,
        title=resolved_title,
        audience=(audience or "").strip() or "readers of the original article",
        search_intent="informational",
        article_angle=(
            "Fresh editorial rewrite of the provided article that "
            "keeps the facts and improves readability."
        ),
        target_word_count=target,
        additional_instructions=instructions,
        include_h3=include_h3,
        include_tables=include_tables,
        include_lists=include_lists,
        include_quotes=include_quotes,
        include_italics=False,
        include_bold=False,
    )

    emit(
        "stage",
        stage="parse",
        status="done",
        message=f"Source ready ({source_words} words)",
    )
    emit(
        "stage",
        stage="rewrite",
        status="running",
        message="Rewriting the article...",
    )

    generated = generate_single_call_article(
        brief=brief,
        style_context="",
        fact_context=(
            "SOURCE ARTICLE — keep these facts; do not copy sentences "
            "or distinctive phrasing:\n\n"
            + source
        ),
    )

    emit(
        "stage",
        stage="rewrite",
        status="done",
        message="Draft rewritten",
    )
    emit(
        "stage",
        stage="seo",
        status="running",
        message="Scoring the rewritten article...",
    )

    seo_analysis = SEOAnalysis(
        primary_keyword=brief.primary_keyword,
        secondary_keywords=[],
        meta_title=generated.meta_title,
        meta_description=generated.meta_description,
        issues=[],
        faqs=generated.faqs,
        internal_links=_normalize_internal_suggestions(
            generated.internal_links,
            _site,
        ),
        alt_texts=generated.alt_texts,
        external_source_suggestions=_normalize_external_suggestions(
            generated.external_source_suggestions,
        ),
        cannibalization_flags=[],
    )
    scores = score_article(
        article=generated.article_markdown,
        brief=brief,
        seo=seo_analysis,
    )
    stats = {
        "word_count": word_count(generated.article_markdown),
        "h1_count": count_h1(generated.article_markdown),
        "keyword_count": keyword_count(
            generated.article_markdown,
            brief.primary_keyword,
        ),
    }

    emit("stage", stage="seo", status="done", message="Scores ready")
    logger.info("=== Rewrite complete: '%s' ===", resolved_title)

    return {
        "brief": brief.model_dump(),
        "article": generated.article_markdown,
        "outline": extract_outline_from_markdown(generated.article_markdown),
        "seo": seo_analysis.model_dump(),
        "serp": {"keyword": resolved_keyword},
        "stats": stats,
        "scores": scores,
        "generation_mode": "rewrite",
        "implementation_checklist": _build_implementation_checklist(
            seo_analysis, stats
        ),
        "priority": _build_priority(scores),
        "expected_impact": _build_expected_impact(
            seo_analysis, scores, stats, source_words
        ),
    }
