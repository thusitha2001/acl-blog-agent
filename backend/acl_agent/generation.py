"""
ACL Blog Agent - article generation (single-call).

Holds the single-call prompt strings (editorial voice and SEO)
and the generation logic that uses them.

generate_single_call_article() produces the complete article - draft,
structure, and SEO metadata - from a single model API call.

Prompt functions take brand_name as an argument so one instance can
write for any brand/domain the caller supplies in the content brief.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from acl_agent.llm import call_model_for_json
from acl_agent.models import (
    ContentBrief,
    SingleCallArticle,
)
from acl_agent.validation import (
    check_originality,
    count_h1,
    keyword_count,
    word_count,
    word_count_band,
)


def brand_writing_style(brand_name: str) -> str:
    return f"""
{brand_name} EDITORIAL STYLE

Write for one real reader who has a specific problem or decision.
Sound like a working editor at {brand_name}, not a content mill.

VOICE
- Warm, practical, and conversational without being sloppy.
- Helpful rather than salesy.
- Clear American English unless the brief asks otherwise.
- Use examples that fit the brand's actual products or category
  when the brief supports them.

TONE AND AUDIENCE
- Honor the brief's tone, audience, point of view, readability,
  search intent, and brand voice exactly.
- Match search_intent in the brief:
  informational = teach and explain; commercial = compare options
  before a purchase; transactional = help the reader complete an
  action; navigational = help them find a specific brand, page,
  or product.
- Professional quality with contractions where they fit:
  you're, it's, don't, you'll, that's, can't, won't.
- Prefer simple words: use, help, show, need, start, buy, fix.
- No promotional hype, stacked adjectives, or exaggerated claims.

PRODUCT MENTIONS
- Mention products or services only when they naturally help.
- Explain why a feature or material matters in practice.
- Never force a product in for SEO.
- Never invent specs, certifications, quotes, or testimonials.
"""


HUMAN_EDITORIAL_VOICE = """
WRITE THE FINAL ARTICLE DIRECTLY

Do not produce a generic first draft and then dress it up.
Write the publish-ready piece in one pass, in a natural
editorial voice a magazine or brand blog would actually run.

HUMAN WRITING STYLE
- Write for real readers, not search engines.
- Vary sentence length and structure. Mix short lines with
  longer ones. Do not let three sentences in a row share
  the same shape.
- Vary paragraph length. Some paragraphs can be one sentence.
  Others can run a few sentences. Do not make every section
  the same length or follow the same mini-template.
- Do not start every paragraph with a topic sentence, then
  explanation, then wrap-up.
- Use meaning-based transitions. Skip stock connectors like
  Furthermore, Moreover, Additionally, However, and Therefore
  unless the sentence truly needs that word.
- Conversational where it fits; still edited and professional.
- Specific examples, practical observations, and useful detail
  instead of generic statements.
- Cut filler. If a sentence adds no new information, delete it.
- Do not repeat the same point in different words.
- Do not invent statistics, research, quotes, testimonials,
  personal experiences, or facts.
- Do not copy or closely imitate competitor wording from the
  SERP notes or style references.
- Do not force keywords. Use the primary keyword and related
  terms only where they sound like something a person would say.
- Do not keyword-stuff or repeat the main phrase in every section.
- Do not add fake spelling mistakes, awkward grammar, or
  random punctuation to seem "human."
- Do not mention AI, AI detection, detectors, or any writing
  process in the article.

AVOID THESE PHRASES unless they truly belong
In today's world; When it comes to; Whether you're;
It's important to note; It's worth mentioning; Let's dive in;
Let's explore; In conclusion; Overall; To summarize;
In this article we will; Without further ado; Look no further;
This comprehensive guide; the world of; the realm of;
not only...but also.

NATURALNESS CHECK (silent — never describe this in the article)
Before keeping a sentence, ask: would an experienced editor
publish this as-is? If it sounds templated, predictable,
repetitive, overly polished, or robotic, rewrite it now.

SEO, AEO, AND GEO — WITHOUT SOUNDING LIKE SEO
- Keep the piece easy to find and easy to quote, but never
  sacrifice the writing to hit a keyword quota.
- Use the primary keyword naturally, especially near the
  opening if it fits.
- Answer the reader's real questions directly (AEO): a clear
  answer first, then the useful extra.
- Include specific terminology, named things, places, and
  context from the brief or verified facts when they help
  (GEO). Do not invent entities.
- Do not write a sentence whose only job is to satisfy a
  search engine.

QUALITY BAR
Original, natural, specific, useful, factually careful,
and ready to publish.
"""


def single_call_system_prompt(
    brand_name: str,
    target_word_count: int,
    min_words: int,
    max_words: int,
) -> str:
    return f"""
You are a senior editorial writer for {brand_name}.
Write the finished, publish-ready article in one response.
Do not draft, then rewrite. Do not discuss process.

{brand_writing_style(brand_name)}

{HUMAN_EDITORIAL_VOICE}

ORIGINALITY - NON-NEGOTIABLE
- Every sentence must be written entirely in your own words.
- Do not copy or closely paraphrase sentences, phrases, or sentence
  structures from the STYLE REFERENCES or VERIFIED FACTS below.
- Use references only to learn brand terminology, verified facts,
  and general tone - never as source text to adapt or lightly reword.
- Do not reuse a distinctive phrase, metaphor, or sentence pattern
  from the references anywhere in the article.
- The article must read as original work a human editor would
  recognize as new, not a rewrite of existing material.

'''STRUCTURE - REQUIRED
- Exactly one H1 title using an HTML <h1> tag.
- 4-8 H2 sections using HTML <h2> tags, each covering one required
  topic or a distinct angle on the primary keyword.
- H3 (<h3>) SUBHEADINGS ARE FORBIDDEN unless the CONTENT BRIEF's
  additional_instructions explicitly requests them. Never create
  H3s on your own. Use only H2 sections unless explicitly told
  otherwise.
- The CONTENT BRIEF below includes FORMATTING REQUIREMENTS in its
  additional_instructions field. Follow ALL of them exactly:
  if it says use H3, use H3; if it says use tables, use HTML
  <table> markup; if it says use lists, use lists.

PUBLISH FORMAT — NON-NEGOTIABLE
The article must be completely ready to paste onto a website.
Output clean HTML only. No markdown. No commentary.

Allowed tags: h1, h2, h3, p, ul, ol, li, a, table, thead, tbody,
tr, th, td, blockquote.

- Wrap every paragraph in <p>. Separate headings, paragraphs, and
  lists with a blank line.
- Numbered lists (<ol><li>) for steps, instructions, or processes.
  One step per <li>. Never combine 1. 2. 3. into a single paragraph.
- Bullet lists (<ul><li>) for features, tips, or grouped items.
  One item per <li>. Keep each list item on its own line.
- Internal links as <a href="url">anchor text</a>. Do not invent
  extra URLs. Do not dump links in a list at the end.
- Tables (when requested) as HTML <table> with <thead> and <tbody>.
- NEVER use *, **, _, #, -, or other markdown symbols for styling.
- NEVER use <strong>, <b>, <em>, <i>, <u>, or underline.
- NEVER wrap the article in markdown fences or add notes about
  formatting. Return only the article HTML inside article_markdown.

- Each section must have at least two full paragraphs - no single
  sentence "sections" and no bullet-only sections standing in for
  real explanation.
- Do not skip any topic listed in required_topics in the brief.
- Answer the reader's main question within the first 150 words
  with a direct, quotable statement an AI overview could cite.
- Prefer some H2s framed as questions readers actually ask.
- Follow each H2 with a 1-2 sentence direct answer before expanding.
- Write for the TARGET AUDIENCE in the content brief: examples,
  vocabulary, and decision criteria must match that reader.
- If the brief includes internal_links, weave EACH one into the
  article as <a href="url">anchor text</a> where it naturally
  helps the reader.
- End the final section with a concrete, useful next step - not a
  heading called "Conclusion" and not a generic summary paragraph.

REPETITION - REQUIRED
- Do NOT repeat the primary keyword or topic in every section.
  Spread mentions evenly across the article. Any single word or
  phrase must not appear more than twice in any individual
  section. Use synonyms, related terms, and natural language
  variations instead of repeating the keyword.

FACT VERIFICATION — REQUIRED
- NEVER invent statistics, historical dates, pricing figures,
  rarity levels, mining details, certifications, or product specs
  unless they are EXPLICITLY stated in the VERIFIED FACTS section
  below or the brief's product_facts.
- If a claim about history, price, rarity, mining, or a specific
  fact cannot be verified from the provided VERIFIED FACTS or
  product_facts, do NOT state it. Replace with a general,
  verifiable statement or omit it entirely.
- Do NOT use phrases like "historically," "since ancient times,"
  "costs $X," "worth $Y," "rare," "limited edition," "mined in
  Z country," or specific numerical claims unless they appear in
  the VERIFIED FACTS source material.
- When in doubt about any factual claim, omit it rather than
  fabricate it.'''

LENGTH - REQUIRED, STRICT
- The user's target word count for this article is EXACTLY
  {target_word_count} words.
- The article body (everything except the H1 line) MUST land between
  {min_words} and {max_words} words. Aim for {target_word_count}
  words as closely as you can - do not stop short of the minimum and
  do not run past the maximum.
- Plan section-by-section length before writing so the total lands
  in range on the first attempt: with N sections, budget roughly
  {target_word_count} / N words per section.
- Under-length or over-length articles will be rejected and you will
  be asked to rewrite, so treat the word count as a hard constraint,
  not a suggestion.

Return a single JSON object with EXACTLY these fields (no wrapper
key, no markdown fences, no commentary before or after the JSON):

{{
  "h1": "string - the article title, matching the H1 in article_markdown",
  "article_markdown": "string - the FULL article as clean publish-ready HTML (h1, h2, p, ul/ol/li), no markdown, no commentary, with \\n for line breaks",
  "meta_title": "string - under 60 characters",
  "meta_description": "string - under 155 characters",
  "faqs": [
    {{"question": "string", "answer": "string"}}
  ],
  "alt_texts": ["string", "string"],
  "internal_links": [
    {{"anchor_text": "string", "reason": "link to your page about X — do not invent a specific path"}}
  ],
  "external_source_suggestions": [
    {{"url": "string — a source type or well-known domain (.gov, .edu, or a known industry site), not a fabricated article URL", "reason": "string"}}
  ]
}}

faqs should answer the brief's reader_questions where relevant.
internal_links are suggestions only: describe the destination in reason
as "link to your page about X". Do not invent exact site paths.
external_source_suggestions: 2–4 items. Prefer source types
(.gov, .edu, known industry publishers). If you are not certain a
specific article URL is live, return the domain or type instead.
Do not invent statistics, certifications, studies, or product specs
beyond what is given in VERIFIED FACTS or the brief's product_facts.
"""


def generate_single_call_article(
    brief: ContentBrief,
    style_context: str,
    fact_context: str,
) -> SingleCallArticle:
    """
    Produces the complete article - draft, structure, and SEO
    metadata - from a single model call. This trades away the
    section-by-section drafting and separate editorial pass of the
    multi-call pipeline in exchange for using exactly one API
    request per article in the normal case (retries only fire if
    the model's response fails validation).
    """
    prompt = f"""
CONTENT BRIEF
{brief.model_dump_json(indent=2)}

STYLE REFERENCES (tone/voice only - do not copy or paraphrase)
{style_context}

VERIFIED FACTS (facts only - do not copy phrasing)
{fact_context}

Write the complete, final article and return it in the required JSON
schema. Do not include notes about writing style, SEO, or process.
"""

    minimum_words, maximum_words = word_count_band(
        brief.target_word_count
    )

    def extra_validate(parsed: SingleCallArticle) -> Optional[str]:
        count = word_count(parsed.article_markdown)
        article = parsed.article_markdown
        issues: list[str] = []

        if count_h1(article) != 1:
            return (
                "the article must contain exactly one H1 heading "
                "(use a single <h1> title)"
            )

        # Word count — min_words/max_words were computed and put in
        # the prompt as a "hard, strict" requirement but never actually
        # checked here, so the model's word count could drift with no
        # retry. Enforce it (with schema_retries=2 giving it room to
        # correct) so the returned article's length actually matches
        # what the user asked for.
        if count < minimum_words:
            issues.append(
                f"the article body is {count} words, below the "
                f"required minimum of {minimum_words} (target is "
                f"{brief.target_word_count}). Expand it - add more "
                f"depth, examples, or detail to existing sections "
                f"rather than padding with filler."
            )
        elif count > maximum_words:
            issues.append(
                f"the article body is {count} words, above the "
                f"required maximum of {maximum_words} (target is "
                f"{brief.target_word_count}). Trim it down without "
                f"losing key information."
            )

        # Heading hierarchy — H3 only when the user asked for it, and
        # (just as important) actually present when they did ask -
        # the brief's include_h3/include_tables/include_lists flags
        # come straight from the request, not the model's own output.
        h3_matches = re.findall(
            r"(?:^###\s+.+$|<h3\b[^>]*>)",
            article,
            flags=re.MULTILINE | re.IGNORECASE,
        )

        if not brief.include_h3:
            if h3_matches:
                return (
                    "H3 subheadings are not allowed in this article. "
                    "Use only H2 sections. Remove all H3 headings."
                )
        elif not h3_matches:
            issues.append(
                "the user requested H3 subheadings but the article "
                "has none. Add H3 subheadings nested under at "
                "least some of the H2 sections."
            )

        if brief.include_tables:
            has_table = bool(re.search(
                r"(?:\|[\s:-]*-{2,}[\s:-]*\||<table\b)",
                article,
                flags=re.IGNORECASE,
            ))
            if not has_table:
                issues.append(
                    "the user requested at least one comparison "
                    "table but the article has none. Add an HTML "
                    "<table> in the most relevant section."
                )

        if brief.include_lists:
            has_list = bool(re.search(
                r"(?:^\s*(?:[-*]|\d+\.)\s+\S|<(?:ul|ol)\b)",
                article,
                flags=re.MULTILINE | re.IGNORECASE,
            ))
            if not has_list:
                issues.append(
                    "the user requested lists but the article has "
                    "none. Use <ol> for steps and <ul> for tips "
                    "or features, with one item per <li>."
                )

        if re.search(r"\*\*[^*]+\*\*|__[^_]+__", article):
            issues.append(
                "do not use asterisks, underscores, bold, or italic "
                "markup. Write plain HTML with h1/h2/p/ul/ol only."
            )

        # Repetition — keyword must not dominate any single section
        kw = brief.primary_keyword
        kw_count = keyword_count(article, kw)
        if kw_count > 0:
            sections = re.split(
                r"(?:^##\s+.+$|<h2\b[^>]*>.*?</h2>)",
                article,
                flags=re.MULTILINE | re.IGNORECASE | re.DOTALL,
            )
            for section in sections:
                section_count = keyword_count(section, kw)
                section_words = max(len(section.split()), 1)
                # Allow natural usage: up to 3 mentions plus one per
                # ~40 words. Flag only clearly repetitive sections.
                limit = 3 + section_words // 40
                if section_count > limit:
                    issues.append(
                        f"The keyword '{kw}' appears {section_count} "
                        f"times in one section (limit {limit}). "
                        "Spread mentions evenly across the article "
                        "and use synonyms."
                    )
                    break

        # Fact verification — flag suspicious unsupported claims.
        # Deliberately limited to words that reliably signal an actual
        # historical/factual assertion. Generic words like "price",
        # "since", "first", "rare", or "worth" used to be in this list,
        # but they're so common in ordinary prose (any e-commerce or
        # jewelry article will say "price" repeatedly) that they flagged
        # nearly every article as an "unsupported claim" regardless of
        # whether it actually asserted anything - burning the one retry
        # and then failing generation outright.
        fact_keywords = ["historically", "ancient", "limited edition",
                         "mined", "mining", "invented", "discovered",
                         "million years", "billion"]
        article_lower = article.lower()
        for kw_fact in fact_keywords:
            if kw_fact in article_lower and kw_fact not in (
                fact_context + "\n" + str(brief.product_facts)
            ).lower():
                issues.append(
                    f"Claim may reference an unsupported fact "
                    f"('{kw_fact}'). Only state facts that appear in "
                    f"the VERIFIED FACTS or product_facts source "
                    f"material. Remove or verify this claim."
                )
                break

        filler_hits = sum(
            1 for phrase in (
                "in today's world",
                "when it comes to",
                "it's important to note",
                "it's worth mentioning",
                "let's dive in",
                "let's explore",
                "in conclusion",
                "without further ado",
                "this comprehensive guide",
                "in this article",
                "look no further",
            )
            if phrase in article_lower
        )
        if filler_hits >= 2:
            issues.append(
                "the prose uses stock filler phrases. Rewrite those "
                "sentences in plain editorial language. Do not add "
                "notes about writing style."
            )

        if issues:
            return "; ".join(issues)

        originality_issue = check_originality(
            parsed.article_markdown,
            style_context + "\n\n" + fact_context,
        )

        if originality_issue:
            return (
                "the draft is too close to the reference material - "
                "rewrite the overlapping sections entirely in your "
                "own words and sentence structure: " + originality_issue
            )

        return None

    # Scale the output token budget to what this article actually
    # needs instead of always asking for the max. A flat 16000-token
    # request for a 600-word article is wasteful, and some HF Inference
    # Providers backing the model enforce their own (lower) max_tokens
    # cap - when the router load-balances onto one of those under
    # concurrent traffic, an oversized request gets rejected outright
    # with a 400 rather than throttled.
    max_tokens = max(3000, min(16000, brief.target_word_count * 2 + 1200))

    return call_model_for_json(
        single_call_system_prompt(
            brief.brand_name,
            brief.target_word_count,
            minimum_words,
            maximum_words,
        ),
        prompt,
        SingleCallArticle,
        temperature=0.72,
        max_tokens=max_tokens,
        # 3 retries (4 attempts total): extra_validate now stacks
        # several hard requirements at once (word count band, H3s,
        # tables, lists all have to pass together), so it needs more
        # room to converge than the single retry originally allowed.
        schema_retries=3,
        extra_validate=extra_validate,
    )


def extract_outline_from_markdown(article_markdown: str) -> dict[str, Any]:
    """
    Reconstructs a lightweight outline from HTML or Markdown headings.
    """
    h1_match = re.search(
        r"<h1\b[^>]*>(.*?)</h1>",
        article_markdown,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not h1_match:
        h1_match = re.search(
            r"^#\s+(.+)$",
            article_markdown,
            flags=re.MULTILINE,
        )

    def _clean_heading(value: str) -> str:
        return re.sub(r"<[^>]+>", "", value).strip()

    h1 = _clean_heading(h1_match.group(1)) if h1_match else ""

    sections = []

    for match in re.finditer(
        r"<h([23])\b[^>]*>(.*?)</h\1>",
        article_markdown,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        sections.append(
            {
                "heading": _clean_heading(match.group(2)),
                "level": int(match.group(1)),
            }
        )

    if not sections:
        for match in re.finditer(
            r"^(##|###)\s+(.+)$",
            article_markdown,
            flags=re.MULTILINE,
        ):
            level = 2 if match.group(1) == "##" else 3
            sections.append(
                {
                    "heading": match.group(2).strip(),
                    "level": level,
                }
            )

    return {
        "h1": h1,
        "sections": sections,
    }
