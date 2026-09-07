"""
ACL Blog Agent - blog post pipeline.

Orchestrates: SERP analysis -> auto-brief generation ->
article generation (generate_full_pipeline / generate_1click).

Usage:
    result = generate_1click("how to choose linen table runners")
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from acl_agent.config import (
    BRAND_NAME,
    BRAND_SITE,
    HYBRID_FACT_TOP_K,
    HYBRID_STYLE_TOP_K,
    logger,
)
from acl_agent.auto_brief import analyze_serp, auto_generate_brief
from acl_agent.generation import extract_outline_from_markdown, generate_single_call_article
from acl_agent.knowledge_base import retrieve_context
from acl_agent.models import ContentBrief, SEOAnalysis
from acl_agent.scraping import scrape_url_for_request
from acl_agent.validation import validate_article


def generate_full_pipeline(
    brief: ContentBrief,
    extra_style_context: Optional[str] = None,
    extra_fact_context: Optional[str] = None,
) -> dict[str, Any]:
    """
    Produces the full article and its SEO metadata from ONE model
    API call (retries only happen if the model's response fails
    schema, word-count, or originality checks - the happy path is
    exactly 1 request).

    extra_style_context / extra_fact_context are optional fresh
    scraps for THIS request only (e.g. a user-provided URL). When
    present, they are prepended to the knowledge-base retrieval so
    the article is grounded on the user's own site.
    """
    style_context = retrieve_context(
        query=brief.article_angle,
        top_k=HYBRID_STYLE_TOP_K,
        source_type="style",
    )

    if extra_style_context:
        style_context = (
            f"{extra_style_context}\n\n{style_context}"
        ).strip()

    if not style_context:
        logger.warning(
            "No human-written 'style' chunks found in the "
            "knowledge base - falling back to general articles "
            "for style reference. Tag human-written blogs in "
            "your ingest CSV to fix this."
        )

        style_context = retrieve_context(
            query=brief.article_angle,
            top_k=HYBRID_STYLE_TOP_K,
            source_type="article",
        )

    fact_context = retrieve_context(
        query=brief.primary_keyword,
        top_k=HYBRID_FACT_TOP_K,
        source_type="article",
    )

    if extra_fact_context:
        fact_context = (
            f"{extra_fact_context}\n\n{fact_context}"
        ).strip()

    result = generate_single_call_article(
        brief=brief,
        style_context=style_context,
        fact_context=fact_context,
    )

    # internal_links come straight from the brief - the user already
    # verified them, so there's no need to ask the model to invent
    # or re-derive them.
    seo_analysis = SEOAnalysis(
        primary_keyword=brief.primary_keyword,
        secondary_keywords=[
            kw.phrase for kw in brief.secondary_keywords
        ],
        meta_title=result.meta_title,
        meta_description=result.meta_description,
        issues=[],
        faqs=result.faqs,
        internal_links=brief.internal_links,
        alt_texts=result.alt_texts,
        cannibalization_flags=[],
    )

    validation = validate_article(
        article=result.article_markdown,
        brief=brief,
        meta_title=result.meta_title,
        meta_description=result.meta_description,
        internal_links=brief.internal_links,
        reference_text=style_context + "\n\n" + fact_context,
    )

    return {
        "brief": brief.model_dump(),
        "article": result.article_markdown,
        "outline": extract_outline_from_markdown(result.article_markdown),
        "seo": seo_analysis.model_dump(),
        "validation": validation,
        "generation_mode": "single",
    }


def generate_1click(
    keyword: str,
    title: Optional[str] = None,
    size: str = "medium",
    article_type: Optional[str] = None,
    tone: str = "friendly",
    point_of_view: Optional[str] = None,
    readability: Optional[str] = None,
    brand_voice: Optional[str] = None,
    language: str = "en-US",
    brand_name: Optional[str] = None,
    website: Optional[str] = None,
    include_faq: bool = True,
    include_takeaways: bool = True,
    include_conclusion: bool = True,
    include_tables: bool = False,
    include_h3: bool = True,
    include_lists: bool = True,
    include_quotes: bool = False,
    include_italics: bool = False,
    include_bold: bool = True,
    hook_type: str = "question",
    hook_brief: Optional[str] = None,
    additional_instructions: str = "",
    on_event: Optional[Callable[[str, dict[str, Any]], None]] = None,
) -> dict[str, Any]:
    """
    Generate a complete blog article from just a keyword.

    1. SERP analysis (competitor data)
    2. Auto-brief generation (LLM creates full ContentBrief)
    3. Article generation (existing pipeline)

    Returns dict with keys:
        - serp: SERP analysis data
        - brief: ContentBrief used for generation
        - article: generated markdown
        - seo: SEO analysis
        - validation: validation results
    """
    _brand = brand_name or BRAND_NAME
    _site = website or BRAND_SITE

    logger.info(
        "=== 1-Click Generation: '%s' ===",
        keyword,
    )

    def emit(event_type: str, **payload: Any) -> None:
        if on_event:
            on_event(event_type, payload)

    # Step 1: SERP analysis
    logger.info("Step 1/3: SERP analysis...")
    emit("stage", stage="serp", status="running",
         message="Analyzing search results for competitors...")
    serp = analyze_serp(keyword)
    emit("stage", stage="serp", status="done",
         message=f"Analyzed {len(serp.results)} competitor results",
         data={
             "results_count": len(serp.results),
             "nlp_keywords": serp.nlp_keywords,
             "common_headings": serp.common_headings,
             "related_queries": serp.related_queries,
         })

    # Step 2: Auto-generate brief
    logger.info("Step 2/3: Generating content brief...")
    emit("stage", stage="brief", status="running",
         message="Drafting the content brief...")
    brief = auto_generate_brief(
        keyword=keyword,
        serp=serp,
        title=title,
        size=size,
        article_type=article_type,
        tone=tone,
        point_of_view=point_of_view,
        readability=readability,
        brand_voice=brand_voice,
        language=language,
        include_faq=include_faq,
        include_takeaways=include_takeaways,
        include_conclusion=include_conclusion,
        include_tables=include_tables,
        include_h3=include_h3,
        include_lists=include_lists,
        include_quotes=include_quotes,
        include_italics=include_italics,
        include_bold=include_bold,
        hook_type=hook_type,
        hook_brief=hook_brief,
        additional_instructions=additional_instructions,
        brand_name=_brand,
        website=_site,
    )
    emit("stage", stage="brief", status="done",
         message=f"Brief ready: '{brief.title}' ({brief.target_word_count} words)",
         data={"title": brief.title, "target_word_count": brief.target_word_count})

    # Step 3: Generate article
    logger.info("Step 3/3: Generating article...")
    emit("stage", stage="draft", status="running",
         message="Writing the full article - this is the slowest step...")

    # Optional request-time scrape: only when the user EXPLICITLY
    # provided a website at request time - scrape it fresh NOW so
    # this article is grounded on that site. Skip when website is
    # None (falls back to the pre-ingested BRAND_SITE from .env).
    # Result is in-memory only - never persisted to the knowledge
    # base or data/.
    extra_style_context: Optional[str] = None
    extra_fact_context: Optional[str] = None

    if website:
        logger.info(
            "Request-time scrape of user-provided site: %s",
            website,
        )
        emit("stage", stage="scrape", status="running",
             message=f"Scraping {website} for this article...")
        scraped = scrape_url_for_request(website)

        if scraped:
            extra_style_context = scraped
            extra_fact_context = scraped
            logger.info(
                "Scraped %s characters from %s for this "
                "request (in-memory only).",
                len(scraped),
                website,
            )
            emit("stage", stage="scrape", status="done",
                 message="Scrape complete for this request")
        else:
            logger.info(
                "No content scraped from %s - continuing with "
                "knowledge base only.",
                website,
            )
            emit("stage", stage="scrape", status="done",
                 message="No content found to scrape - skipped")

    result = generate_full_pipeline(
        brief,
        extra_style_context=extra_style_context,
        extra_fact_context=extra_fact_context,
    )
    emit("stage", stage="draft", status="done",
         message="Article drafted. Running SEO and validation...")

    # SEO / validation are bundled into the single-call result
    emit("stage", stage="seo", status="done",
         message="SEO metadata complete")
    emit("stage", stage="validate", status="running",
         message="Validating quality, originality, and word count...")
    emit("stage", stage="validate", status="done",
         message="Validation complete")

    # Add SERP data to result
    result["serp"] = {
        "keyword": keyword,
        "results_count": len(serp.results),
        "nlp_keywords": serp.nlp_keywords,
        "common_headings": serp.common_headings,
        "related_queries": serp.related_queries,
    }

    logger.info(
        "=== 1-Click Generation Complete: '%s' ===",
        keyword,
    )

    return result
