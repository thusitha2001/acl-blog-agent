"""
ACL Blog Agent - article generation (single-call).

Holds the single-call prompt strings (editorial voice,
humanization, SEO) and the generation logic that uses them.

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
    word_count,
    word_count_band,
)


def brand_writing_style(brand_name: str) -> str:
    return f"""
{brand_name} EDITORIAL STYLE

VOICE
- Warm, practical, knowledgeable, and conversational.
- Premium but never pretentious.
- Helpful rather than aggressively sales-focused.
- Write for real customers using clear American English.
- Use concrete examples relevant to the brand's product or service
  category when relevant.

TONE
- Professional but approachable.
- Educational and editorial.
- Confident without unsupported absolute claims.
- Avoid exaggerated marketing claims.
- Avoid generic lifestyle-copy language.

PRODUCT MENTIONS
- Mention products or services only when they naturally support the topic.
- Explain why a feature, material, or characteristic matters.
- Never force products into a paragraph for SEO.
- Never invent product specifications or certifications.

SEO STYLE
- Use the primary keyword naturally.
- Use related terms only when they help the reader.
- Do not keyword-stuff.
- Answer likely reader questions directly.
"""


NATURAL_EDITORIAL_STYLE = """
NATURAL EDITORIAL WRITING PROFILE

Write for one real reader with a specific problem or decision.

OPENING
- Start with the reader's situation, hesitation, or question.
- Give the useful point early.
- Do not begin with a dictionary definition.
- Avoid "In today's world", "When it comes to", and
  "Whether you're" unless the phrase is genuinely necessary.

PARAGRAPHS
- Keep most paragraphs focused on one useful idea.
- Mix one-sentence paragraphs with paragraphs of two to four sentences.
- Do not make every section the same length.
- Avoid predictable paragraph formulas.

RHYTHM
- Mix short, medium, and occasional longer sentences.
- Use contractions naturally.
- Avoid repetitive sentence openings.
- Avoid mechanically symmetrical lists.
- Prefer plain, specific language over corporate wording.

EDITORIAL JUDGMENT
- Explain what matters most.
- Tell the reader what can be skipped.
- Mention realistic constraints and trade-offs.
- Give practical rules of thumb.
- Use concrete examples.
- Do not invent personal experiences.

SPECIFICITY
- Replace vague advice with observable actions.
- Explain why a recommendation matters.
- Include examples, use cases, or decisions where appropriate.
- Do not invent statistics, studies, certifications, or product claims.

ENDING
- End with a useful next step or a calm editorial takeaway.
- Do not add a generic summary.
- Do not use "In conclusion", "Overall", or
  "To summarize".

The final article should feel edited, not regenerated.
"""


HUMANIZATION_VOICE = """
HUMANIZATION - NON-NEGOTIABLE

Write as if you are a real person who knows this topic, not a model
producing content on demand. The article must pass AI detectors.

VOICE
- Write in second person ("you") with occasional first person ("I",
  "we") to create a conversational, direct-address feel.
- Include 2-3 casual asides per article using em dashes or parentheses:
  "Linen wrinkles easily — honestly, that's part of the charm."
- Ask the reader a rhetorical question at least twice in the article.
- Use at least one sentence that starts with "But" or "And" to mimic
  how humans actually write.
- Include one moment of mild opinion or preference:
  "I'd pick the mid-weight version every time."
- Use at least one short declarative sentence that stands alone as
  its own paragraph for emphasis.

SENTENCE RHYTHM
- Alternate short punchy sentences with longer flowing ones.
- Never let three consecutive sentences share the same structure.
- Vary sentence openings: question, prepositional phrase, dependent
  clause, name, number, gerund, or imperative — at least once per
  section.
- Include one sentence under 8 words per section.
- Include at least one sentence over 30 words per section to create
  rhythm contrast.
- Start at least two sentences per section with a subordinating
  conjunction: "Although...", "Since...", "While...", "Because...".

PARAGRAPH SHAPE
- Mix 1-sentence paragraphs with 3-5 sentence paragraphs.
- No two consecutive paragraphs should have similar word counts.
- Use an em dash or parenthetical aside at least once per article
  to mimic how humans interrupt their own thought.
- Include one brief personal-style observation per section:
  "Most people don't realize...", "Here's the thing...",
  "The honest answer is...", "What nobody tells you...",
  "I've seen this mistake a hundred times..."

VOCABULARY
- Use contractions naturally: don't, it's, you'll, that's, can't,
  won't, shouldn't, we're, they're, you've, let's, isn't, doesn't.
- Prefer plain words: "use" not "utilize", "help" not "facilitate",
  "show" not "demonstrate", "need" not "require", "start" not
  "commence", "buy" not "acquire", "fix" not "remediate".
- Never use: "delve into", "realm", "tapestry", "embark",
  "landscape" as metaphor, "moreover", "furthermore",
  "in this blog post", "it goes without saying", "leveraging",
  "synergy", "holistic", "seamless", "robust", "unlock",
  "empower", "navigate", "shed light", "game-changer",
  "at the end of the day", "in a nutshell", "rest assured",
  "dive deep", "tap into", " shed light on", " underscore ".

TRANSITIONS
- Never start consecutive paragraphs with "Additionally" or "Also".
- Use causal transitions at least twice: "Because...", "That means...",
  "So...", "As a result..."
- Use contrast at least once: "But here's what most people miss..."
- Start one paragraph mid-thought to break the linear flow:
  "...and that's where most people go wrong."

SPECIFICITY
- Include one concrete number, measurement, or time frame per section.
- Reference a real scenario, not a hypothetical one.
- Name a specific product, material, or technique when the brief
  provides product_facts or required_topics.
- Avoid vague superlatives ("the best", "amazing", "incredible")
  unless qualified with a reason.

DEPTH SIGNALS - what separates human writing from AI
- Acknowledge uncertainty or trade-offs honestly:
  "This works for most people, though not everyone",
  "There's no single right answer here".
- Disagree with or qualify a common assumption at least once.
- Give the reader permission to make a different choice:
  "If you prefer X, that works too".
- End sections with a thought, not a summary.
- Include one "real talk" moment per article — a blunt, no-BS
  sentence that cuts through the usual advice:
  "Honestly, most of those lists are recycled garbage."

BANNED AI PATTERNS
- No "In today's world", "When it comes to", "Whether you're".
- No "It's important to note", "It's worth mentioning".
- No "In this article, we will explore...".
- No "Let's dive in", "Let's explore", "Without further ado".
- No "Sit back and relax".
- No "So, what are you waiting for?".
- No "Look no further", "Look no further than".
- No "If you're looking for...", "If you've ever wondered...".
- No "we'll cover", "we'll explore", "we'll discuss".
- No "the world of", "the realm of".
- No "not only...but also" constructions.
- No parallel triads: avoid three-part lists where all items
  share the same grammatical structure ("X, Y, and Z" with
  matching verb forms).
- No sentences that begin with "This comprehensive guide".
"""


def single_call_system_prompt(
    brand_name: str,
    target_word_count: int,
    min_words: int,
    max_words: int,
) -> str:
    return f"""
You are the senior editorial writer and SEO editor for {brand_name},
producing a complete, publish-ready article in a single response.

{brand_writing_style(brand_name)}

{NATURAL_EDITORIAL_STYLE}

{HUMANIZATION_VOICE}

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

STRUCTURE - REQUIRED
- Exactly one H1 (the article title), using Markdown "# ".
- 4-8 H2 sections using Markdown "## ", each covering one required
  topic or a distinct angle on the primary keyword.
- The CONTENT BRIEF below includes FORMATTING REQUIREMENTS in its
  additional_instructions field. Follow ALL of them exactly:
  if it says use H3, use H3; if it says use tables, use Markdown
  tables with | pipe syntax; if it says use lists, use lists;
  if it says use blockquotes, use blockquotes; if it says use
  italics or bold, use them throughout the article.
- When tables are requested, include at least one Markdown table
  (| col1 | col2 | format) with a header row and separator row.
  Place it in the most relevant section. Tables are REQUIRED when
  the brief asks for them — do not skip them.
- Each section must have at least two full paragraphs - no single
  sentence "sections" and no bullet-only sections standing in for
  real explanation.
- Do not skip any topic listed in required_topics in the brief.
- Answer the reader's main question within the first 150 words.
- End the final section with a concrete, useful next step - not a
  heading called "Conclusion" and not a generic summary paragraph.

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
  "article_markdown": "string - the FULL article in Markdown, starting with the H1 line, including all H2/H3 sections, as one string with \\n for line breaks",
  "meta_title": "string - under 60 characters",
  "meta_description": "string - under 155 characters",
  "faqs": [
    {{"question": "string", "answer": "string"}}
  ],
  "alt_texts": ["string", "string"]
}}

faqs should answer the brief's reader_questions where relevant.
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

Write the complete article and return it in the required JSON
schema.
"""

    minimum_words, maximum_words = word_count_band(
        brief.target_word_count
    )

    def extra_validate(parsed: SingleCallArticle) -> Optional[str]:
        count = word_count(parsed.article_markdown)

        if count_h1(parsed.article_markdown) != 1:
            return (
                "the article must contain exactly one H1 heading "
                "(a single line starting with '# ')"
            )

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

    return call_model_for_json(
        single_call_system_prompt(
            brief.brand_name,
            brief.target_word_count,
            minimum_words,
            maximum_words,
        ),
        prompt,
        SingleCallArticle,
        temperature=0.65,
        max_tokens=9000,
        schema_retries=0,
        extra_validate=extra_validate,
    )


def extract_outline_from_markdown(article_markdown: str) -> dict[str, Any]:
    """
    Reconstructs a lightweight outline (for the API response's
    "outline" field) by reading headings back out of the generated
    Markdown, since single-call mode doesn't produce a separate
    outline object.
    """
    h1_match = re.search(
        r"^#\s+(.+)$",
        article_markdown,
        flags=re.MULTILINE,
    )

    sections = []

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
        "h1": h1_match.group(1).strip() if h1_match else "",
        "sections": sections,
    }
