"""
ACL Blog Agent - automatic content brief generation.

Takes SERP analysis data + user settings (keyword, tone, size,
etc.) and makes one LLM call to produce a complete ContentBrief.
This is the core of the 1-click blog post feature.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from acl_agent.config import SERP_RESULTS_COUNT, logger


@dataclass
class SERPResult:
    title: str
    url: str
    snippet: str


@dataclass
class SERPAnalysis:
    keyword: str
    results: list[SERPResult] = field(default_factory=list)
    nlp_keywords: list[str] = field(default_factory=list)
    common_headings: list[str] = field(default_factory=list)
    related_queries: list[str] = field(default_factory=list)
    avg_word_count: int = 1750
    content_gaps: list[str] = field(default_factory=list)


def search_serp(
    keyword: str,
    max_results: int = SERP_RESULTS_COUNT,
) -> list[SERPResult]:
    """
    Search DuckDuckGo for the keyword and return top results
    with title, URL, and snippet.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        logger.warning(
            "ddgs not installed. "
            "Run: pip install ddgs"
        )
        return []

    results: list[SERPResult] = []

    try:
        with DDGS() as ddgs:
            for r in ddgs.text(
                keyword,
                max_results=max_results,
                region="wt-wt",
            ):
                results.append(
                    SERPResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    )
                )
    except Exception as error:
        logger.warning(
            "SERP search failed for '%s': %s",
            keyword,
            error,
        )

    return results


def extract_nlp_keywords(
    keyword: str,
    results: list[SERPResult],
) -> list[str]:
    """
    Extract semantically related keywords from SERP titles
    and snippets. Filters out generic/dictionary results
    and focuses on topic-relevant terms.
    """
    # Combine all text from results
    all_text = " ".join(
        f"{r.title} {r.snippet}" for r in results
    ).lower()

    # Split into words
    words = re.findall(r"[a-z]+", all_text)

    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does",
        "did", "will", "would", "could", "should", "may",
        "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into",
        "through", "during", "before", "after", "above",
        "below", "between", "out", "off", "over", "under",
        "again", "further", "then", "once", "here", "there",
        "when", "where", "why", "how", "all", "both", "each",
        "few", "more", "most", "other", "some", "such", "no",
        "nor", "not", "only", "own", "same", "so", "than",
        "too", "very", "just", "and", "but", "or", "if",
        "this", "that", "these", "those", "it", "its",
        "you", "your", "we", "our", "they", "their",
        "what", "which", "who", "whom", "about",
        "also", "like", "well", "back", "even", "still",
        "new", "way", "use", "one", "two", "first",
        "get", "make", "know", "take", "come", "think",
        "see", "want", "give", "use", "find", "tell",
        "ask", "work", "seem", "feel", "try", "leave",
        "call", "need", "become", "keep", "let", "begin",
        "show", "hear", "play", "run", "move", "live",
        "believe", "happen", "lot", "thing", "thing",
        "definition", "meaning", "dictionary", "define",
        "noun", "verb", "synonym", "antonym", "example",
        "definition", "mean", "significance", "defined",
    }

    # Extract unigrams (content words) - minimum 4 chars
    unigrams = [
        w for w in words
        if w not in stopwords
        and len(w) > 3
        and not w.isdigit()
    ]

    # Extract bigrams
    bigrams: list[str] = []
    sentences = re.split(r"[.!?]+", all_text)

    for sentence in sentences:
        sentence_words = sentence.split()
        for i in range(len(sentence_words) - 1):
            w1, w2 = (
                sentence_words[i],
                sentence_words[i + 1],
            )
            if (
                w1 not in stopwords
                and w2 not in stopwords
                and len(w1) > 2
                and len(w2) > 2
            ):
                bigrams.append(f"{w1} {w2}")

    # Count frequencies
    unigram_counts = Counter(unigrams)
    bigram_counts = Counter(bigrams)

    # Score terms - prefer topic-relevant ones
    keyword_parts = set(keyword.lower().split())

    scored: list[tuple[str, float]] = []

    for term, count in unigram_counts.most_common(40):
        score = float(count)
        # Boost terms related to keyword
        if any(p in term for p in keyword_parts):
            score *= 3
        # Boost longer, more specific terms
        if len(term) > 5:
            score *= 1.5
        # Penalty for very common generic terms
        if count > len(results) * 2:
            score *= 0.5
        scored.append((term, score))

    for term, count in bigram_counts.most_common(30):
        score = float(count) * 2.0
        if any(p in term for p in keyword_parts):
            score *= 3
        scored.append((term, score))

    scored.sort(key=lambda x: -x[1])

    # Deduplicate and return top keywords
    seen: set[str] = set()
    nlp_keywords: list[str] = []

    for term, _ in scored:
        normalized = term.lower().strip()
        if (
            normalized not in seen
            and normalized != keyword.lower()
            and len(normalized) > 3
        ):
            seen.add(normalized)
            nlp_keywords.append(term)
        if len(nlp_keywords) >= 12:
            break

    return nlp_keywords


def extract_headings_from_snippets(
    results: list[SERPResult],
) -> list[str]:
    """
    Extract common heading patterns from SERP titles.
    Filters out dictionary/definition results and
    focuses on informational content headings.
    """
    headings: list[str] = []
    skip_patterns = {
        "definition", "meaning", "dictionary",
        "synonym", "antonym", "define",
        "wikipedia", "wiktionary", "merriam",
        "dictionary.com", "cambridge",
    }

    for result in results:
        title = result.title.strip()
        if not title:
            continue

        # Skip dictionary/definition results
        title_lower = title.lower()
        if any(p in title_lower for p in skip_patterns):
            continue

        # Clean up common suffixes
        cleaned = re.sub(
            r"\s*[\|\-–—]\s*(?:www\.|https?://).*$",
            "",
            title,
        )
        cleaned = re.sub(
            r"\s*[\|\-–—]\s*(?:Home|Blog|News).*$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.strip()

        if (
            cleaned
            and len(cleaned) > 10
            and cleaned not in headings
        ):
            headings.append(cleaned)

        # Extract capitalized phrases from snippets
        snippet = result.snippet
        phrases = re.findall(
            r"(?:^|\.\s+)([A-Z][^.!?]{15,80})",
            snippet,
        )
        for phrase in phrases:
            cleaned = phrase.strip().rstrip(".")
            if (
                cleaned
                and cleaned not in headings
                and len(cleaned) > 15
                and not any(
                    p in cleaned.lower()
                    for p in skip_patterns
                )
            ):
                headings.append(cleaned)

    return headings[:12]


def extract_related_queries(
    keyword: str,
) -> list[str]:
    """
    Extract related/People Also Ask queries from DuckDuckGo
    suggestions.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return []

    queries: list[str] = []

    try:
        with DDGS() as ddgs:
            suggestions = ddgs.suggestions(keyword)
            if suggestions:
                for s in suggestions[:5]:
                    phrase = s.get("phrase", "")
                    if (
                        phrase
                        and phrase != keyword
                        and phrase not in queries
                    ):
                        queries.append(phrase)
    except Exception:
        pass

    # If no suggestions, generate some from keyword
    if not queries:
        base = keyword.rstrip("?")
        queries = [
            f"{base} guide",
            f"{base} tips",
            f"{base} for beginners",
        ]

    return queries[:5]


def analyze_serp(
    keyword: str,
    max_results: int = SERP_RESULTS_COUNT,
) -> SERPAnalysis:
    """
    Full SERP analysis: search, extract keywords, headings,
    and related queries. Returns structured SERPAnalysis
    for auto-brief generation.
    """
    logger.info(
        "Running SERP analysis for: '%s'",
        keyword,
    )

    results = search_serp(keyword, max_results)

    logger.info(
        "Found %s SERP results",
        len(results),
    )

    nlp_keywords = extract_nlp_keywords(
        keyword, results
    )

    common_headings = extract_headings_from_snippets(
        results
    )

    related_queries = extract_related_queries(keyword)

    analysis = SERPAnalysis(
        keyword=keyword,
        results=results,
        nlp_keywords=nlp_keywords,
        common_headings=common_headings,
        related_queries=related_queries,
        avg_word_count=1750,
    )

    logger.info(
        "SERP analysis complete: %s NLP keywords, "
        "%s headings, %s related queries",
        len(nlp_keywords),
        len(common_headings),
        len(related_queries),
    )

    return analysis



import json

from acl_agent.config import (
    BRAND_NAME,
    BRAND_SITE,
    logger,
)
from acl_agent.llm import call_model_for_json
from acl_agent.models import (
    ContentBrief,
    InternalLink,
    KeywordTarget,
)


SIZE_MAP = {
    "x-small": 600,
    "small": 900,
    "medium": 1750,
    "large": 2400,
    "x-large": 3600,
}


def auto_generate_brief(
    keyword: str,
    serp: SERPAnalysis,
    title: Optional[str] = None,
    size: str = "medium",
    article_type: Optional[str] = None,
    tone: str = "friendly",
    point_of_view: Optional[str] = None,
    readability: Optional[str] = None,
    brand_voice: Optional[str] = None,
    language: str = "en-US",
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
    brand_name: str = BRAND_NAME,
    website: str = BRAND_SITE,
) -> ContentBrief:
    """
    Generate a complete ContentBrief from SERP data and user
    settings via a single LLM call.
    """
    target_word_count = SIZE_MAP.get(size, 1750)

    # Build SERP context for the LLM
    serp_context = _format_serp_context(serp)

    # If user didn't provide a title, LLM will generate one
    title_instruction = (
        f'Title: "{title}"'
        if title
        else (
            "Generate a compelling, SEO-optimized title "
            "under 60 characters that includes the primary "
            "keyword naturally."
        )
    )

    # Build article type context
    article_type_instruction = ""
    if article_type:
        type_map = {
            "how-to": "How-to guide: step-by-step instructions solving a specific problem",
            "listicle": "Listicle: numbered/organized list of items, tips, or examples",
            "review": "Product review: honest evaluation with pros, cons, and verdict",
            "news": "News article: timely reporting of events, trends, or announcements",
            "comparison": "Comparison: side-by-side analysis of options/products",
            "case-study": "Case study: real-world example with problem, solution, and results",
            "opinion": "Opinion piece: informed perspective backed by evidence",
            "tutorial": "Tutorial: detailed instructional walkthrough",
            "roundup": "Roundup post: curated collection of recommendations or resources",
            "qa": "Q&A page: structured question-and-answer format",
        }
        article_type_instruction = (
            f"ARTICLE TYPE: {type_map.get(article_type, article_type)}\n"
        )

    # Build POV context
    pov_instruction = ""
    if point_of_view:
        pov_map = {
            "first-singular": "Use first person singular (I, me, my, mine). Write as a personal authority sharing expertise.",
            "first-plural": "Use first person plural (we, us, our, ours). Write as the brand team speaking directly.",
            "second": "Use second person (you, your, yours). Write addressing the reader directly.",
            "third": "Use third person (he, she, it, they). Write as an objective observer.",
        }
        pov_instruction = (
            f"POINT OF VIEW: {pov_map.get(point_of_view, point_of_view)}\n"
        )

    # Build readability context
    readability_instruction = ""
    if readability:
        read_map = {
            "5th": "5th grade reading level: use simple words, short sentences (under 15 words), no jargon. Understandable by 11-year-olds.",
            "6th": "6th grade reading level: conversational language, common words, brief paragraphs.",
            "7th": "7th grade reading level: fairly easy to read, mix of short and medium sentences.",
            "8th-9th": "8th-9th grade reading level: easily understood by most adults. Balanced vocabulary and sentence structure. RECOMMENDED.",
            "10th-12th": "10th-12th grade reading level: fairly difficult, more complex sentences and vocabulary.",
            "college": "College reading level: complex sentence structures, academic vocabulary, nuanced arguments.",
            "college-grad": "College graduate level: very difficult, dense prose, specialized terminology.",
            "professional": "Professional/technical level: extremely difficult, field-specific jargon, advanced concepts.",
        }
        readability_instruction = (
            f"READABILITY: {read_map.get(readability, readability)}\n"
        )

    # Build brand voice context
    brand_voice_instruction = ""
    if brand_voice:
        brand_voice_instruction = (
            f"BRAND VOICE: Write in this specific brand voice style:\n"
            f"{brand_voice}\n"
        )

    # Build structure context
    structure_notes = []
    if include_faq:
        structure_notes.append(
            "Include a FAQ section at the end (3-5 questions)"
        )
    if include_takeaways:
        structure_notes.append(
            "Include a Key Takeaways section near the end"
        )
    if include_conclusion:
        structure_notes.append(
            "End with a practical conclusion (not generic)"
        )
    structure_notes.append(
        f"Opening hook style: {hook_type}"
    )
    if hook_brief:
        structure_notes.append(
            f"Hook brief: {hook_brief}"
        )

    formatting_notes = []
    if include_tables:
        formatting_notes.append(
            "Include at least one comparison table in Markdown format "
            "(| col1 | col2 |) with header row and separator row. "
            "Tables are REQUIRED — do not skip this."
        )
    if include_h3:
        formatting_notes.append("Use H3 subheadings under H2 sections")
    if include_lists:
        formatting_notes.append("Use bulleted/numbered lists for scannability")
    if include_quotes:
        formatting_notes.append("Include blockquotes for expert quotes or key insights")
    if include_italics:
        formatting_notes.append("Use italics for emphasis on key terms")
    if include_bold:
        formatting_notes.append("Use bold for key phrases and important points")

    system_prompt = f"""
You are the editorial planning manager for {brand_name}.

Your job: create a complete, detailed content brief for a blog
article based on SERP competitor analysis data.

The brief must be a single JSON object matching the ContentBrief
schema EXACTLY:

{{
  "brand_name": "string",
  "website": "string",
  "primary_keyword": "string",
  "title": "string (5-200 chars)",
  "audience": "string",
  "search_intent": "informational | commercial | transactional",
  "article_angle": "string (10-1000 chars) - what unique angle
    will differentiate this article from competitors?",
  "target_word_count": {target_word_count},
  "secondary_keywords": [
    {{"phrase": "string", "intent": "informational",
      "priority": "secondary"}}
  ],
  "required_topics": ["string", "string"],
  "reader_questions": ["string", "string"],
  "product_facts": [{{"name": "string", "fact": "string", "source_url": "string or null"}}],
  "internal_links": [{{"anchor_text": "string", "url": "string", "reason": "string"}}],
  "additional_instructions": "string"
}}

RULES:
- Use exactly the field names above (no wrappers, no extras).
- secondary_keywords: pick 3-6 from the NLP keywords that are
  semantically relevant but not redundant with the primary keyword.
- required_topics: use competitor headings + gaps to define 4-8
  topics the article MUST cover. Each should be distinct.
- reader_questions: infer 2-4 questions readers searching this
  keyword would want answered.
- article_angle: identify what competitors are MISSING or doing
  POORLY, and make that the differentiating angle.
- audience: infer from the search intent and competitor content.
- Keep additional_instructions under 500 characters.
- Return ONLY the JSON object, no commentary.
"""

    user_prompt = f"""
PRIMARY KEYWORD: {keyword}

SIZE: {size} ({target_word_count} words)
TONE: {tone}
LANGUAGE: {language}

{article_type_instruction}
{pov_instruction}
{readability_instruction}
{brand_voice_instruction}

STRUCTURE:
{chr(10).join("- " + n for n in structure_notes)}

FORMATTING:
{chr(10).join("- " + f for f in formatting_notes) if formatting_notes else "- No specific formatting requirements"}

{additional_instructions and f"ADDITIONAL INSTRUCTIONS: {additional_instructions}" or ""}

{title_instruction}

SERP COMPETITOR DATA:
{serp_context}

Generate the complete content brief as a single JSON object.
"""

    logger.info(
        "Auto-generating brief for keyword: '%s' "
        "(size=%s, tone=%s)",
        keyword,
        size,
        tone,
    )

    brief = call_model_for_json(
        system_prompt,
        user_prompt,
        ContentBrief,
        temperature=0.5,
        max_tokens=3000,
        schema_retries=3,
    )

    # Inject formatting requirements into additional_instructions
    # so they survive into the article generation prompt
    formatting_directives = []
    if include_tables:
        formatting_directives.append(
            "Include comparison tables where relevant."
        )
    if include_h3:
        formatting_directives.append(
            "Use H3 subheadings under H2 sections to break up "
            "content."
        )
    if include_lists:
        formatting_directives.append(
            "Use bulleted and numbered lists for scannability "
            "throughout the article."
        )
    if include_quotes:
        formatting_directives.append(
            "Include blockquotes (>) for expert quotes or key "
            "insights."
        )
    if include_italics:
        formatting_directives.append(
            "Use italics (*text*) for emphasis on key terms."
        )
    if include_bold:
        formatting_directives.append(
            "Use bold (**text**) for key phrases and important "
            "points throughout the article."
        )

    if formatting_directives:
        fmt_block = (
            "\n\nFORMATTING REQUIREMENTS - MUST INCLUDE IN ARTICLE:\n"
            + "\n".join(
                f"- {d}" for d in formatting_directives
            )
        )
        if brief.additional_instructions:
            brief.additional_instructions += fmt_block
        else:
            brief.additional_instructions = fmt_block.strip()

    # Ensure the brief has the right brand/website
    brief.brand_name = brand_name
    brief.website = website
    brief.primary_keyword = keyword

    # Use LLM-generated title if user didn't provide one
    if not title and brief.title:
        logger.info(
            "Auto-generated title: '%s'",
            brief.title,
        )

    # Inject NLP keywords as secondary if LLM left them sparse
    if len(brief.secondary_keywords) < 3 and serp.nlp_keywords:
        existing = {
            kw.phrase.lower()
            for kw in brief.secondary_keywords
        }
        for nlp_kw in serp.nlp_keywords[:5]:
            if nlp_kw.lower() not in existing:
                brief.secondary_keywords.append(
                    KeywordTarget(
                        phrase=nlp_kw,
                        intent="informational",
                        priority="secondary",
                    )
                )
                existing.add(nlp_kw.lower())

    # Inject related queries as reader questions if sparse
    if (
        len(brief.reader_questions) < 2
        and serp.related_queries
    ):
        brief.reader_questions.extend(
            q
            for q in serp.related_queries
            if q not in brief.reader_questions
        )

    logger.info(
        "Brief generated: '%s' (%s words, %s secondary "
        "keywords, %s required topics)",
        brief.title,
        brief.target_word_count,
        len(brief.secondary_keywords),
        len(brief.required_topics),
    )

    return brief


def _format_serp_context(serp: SERPAnalysis) -> str:
    """Format SERP analysis into a readable context string."""
    parts: list[str] = []

    if serp.results:
        parts.append("TOP COMPETITOR RESULTS:")
        for i, result in enumerate(serp.results, 1):
            parts.append(
                f"\n{i}. {result.title}\n"
                f"   URL: {result.url}\n"
                f"   Snippet: {result.snippet}"
            )

    if serp.nlp_keywords:
        parts.append(
            "\nNLP KEYWORDS (semantically related terms "
            "found in competitor content):\n"
            + ", ".join(serp.nlp_keywords)
        )

    if serp.common_headings:
        parts.append(
            "\nCOMPETITOR TITLES/HEADINGS:\n"
            + "\n".join(
                f"  - {h}" for h in serp.common_headings[:10]
            )
        )

    if serp.related_queries:
        parts.append(
            "\nRELATED SEARCH QUERIES:\n"
            + "\n".join(
                f"  - {q}" for q in serp.related_queries
            )
        )

    parts.append(
        f"\nESTIMATED AVG COMPETITOR WORD COUNT: "
        f"{serp.avg_word_count}"
    )

    return "\n".join(parts)
