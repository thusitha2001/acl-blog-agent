"""
ACL Blog Agent - Pydantic data models.

Request/response schemas for the content brief, outline, SEO
analysis, single-call article, and knowledge base chunks.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from acl_agent.config import BRAND_NAME as _DEFAULT_BRAND_NAME
from acl_agent.config import BRAND_SITE as _DEFAULT_WEBSITE

class KeywordTarget(BaseModel):
    phrase: str
    intent: str = "informational"
    priority: str = "secondary"


class ProductFact(BaseModel):
    name: str
    fact: str
    source_url: Optional[str] = None


class InternalLink(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    anchor_text: str = Field(default="", max_length=200)
    reason: str = Field(default="", max_length=300)


class ContentBrief(BaseModel):
    brand_name: str = Field(
        default=_DEFAULT_BRAND_NAME,
        min_length=1,
        max_length=200,
        description=(
            "The brand/business this article is being written for. "
            "Drives the writer persona and editorial voice in every "
            "prompt - this is what makes the agent usable for any "
            "blog, not just one fixed brand."
        ),
    )
    website: str = Field(
        default=_DEFAULT_WEBSITE,
        min_length=1,
        max_length=300,
        description=(
            "The brand's website (e.g. https://example.com). Internal "
            "links in the brief and in the SEO output are validated "
            "against this domain."
        ),
    )
    primary_keyword: str = Field(
        min_length=2,
        max_length=200,
    )
    title: str = Field(
        min_length=5,
        max_length=200,
    )
    audience: str = "US consumers"
    search_intent: str = Field(
        default="informational",
        description=(
            "Search intent the article should satisfy: "
            "informational, commercial, transactional, or navigational."
        ),
    )
    article_angle: str = Field(
        min_length=10,
        max_length=1000,
    )
    target_word_count: int = Field(
        default=1500,
        ge=300,
        le=8000,
    )
    secondary_keywords: list[KeywordTarget] = Field(
        default_factory=list,
    )
    required_topics: list[str] = Field(
        default_factory=list,
    )
    reader_questions: list[str] = Field(
        default_factory=list,
    )
    product_facts: list[ProductFact] = Field(
        default_factory=list,
    )
    internal_links: list[InternalLink] = Field(
        default_factory=list,
    )
    additional_instructions: str = ""

    # Structure/formatting toggles the user picked at request time.
    # Set programmatically after the brief LLM call (never trusted
    # from the model's own output) so extra_validate() can check
    # deterministically whether the article actually honored them,
    # instead of re-parsing additional_instructions text.
    include_h3: bool = True
    include_tables: bool = False
    include_lists: bool = True
    include_quotes: bool = False
    include_italics: bool = False
    include_bold: bool = False


class OutlineSection(BaseModel):
    heading: str
    level: int = Field(
        default=2,
        ge=2,
        le=3,
    )
    purpose: str
    points_to_cover: list[str] = Field(
        default_factory=list,
    )
    practical_example: Optional[str] = None
    product_relevance: Optional[str] = None


class ArticleOutline(BaseModel):
    h1: str
    reader_problem: str
    editorial_angle: str
    introduction_goal: str
    sections: list[OutlineSection]
    ending_goal: str


class SEOIssue(BaseModel):
    issue_type: str
    location: str
    recommendation: str
    severity: str = "warning"


class SEOAnalysis(BaseModel):
    primary_keyword: str
    secondary_keywords: list[str] = Field(
        default_factory=list,
    )
    meta_title: str
    meta_description: str
    issues: list[SEOIssue] = Field(
        default_factory=list,
    )
    faqs: list[dict[str, str]] = Field(
        default_factory=list,
    )
    internal_links: list[InternalLink] = Field(
        default_factory=list,
    )
    alt_texts: list[str] = Field(
        default_factory=list,
    )
    cannibalization_flags: list[dict[str, str]] = Field(
        default_factory=list,
    )


class KnowledgeChunk(BaseModel):
    chunk_id: str
    text: str
    title: str
    url: Optional[str] = None
    source_type: str
    section: Optional[str] = None


class SingleCallArticle(BaseModel):
    """
    Everything needed for one article, produced from a single model
    call: the article itself plus its SEO metadata. Used by the
    "single" generation mode to minimize API requests per article.
    """
    h1: str = Field(min_length=5, max_length=200)
    article_markdown: str = Field(min_length=200)
    meta_title: str = Field(
        min_length=5,
        max_length=200,
    )
    meta_description: str = Field(
        min_length=10,
        max_length=300,
    )
    faqs: list[dict[str, str]] = Field(
        default_factory=list,
    )
    alt_texts: list[str] = Field(
        default_factory=list,
    )

