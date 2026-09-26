"""
ACL Blog Agent - SEO, GEO, and AEO scoring.

Deterministic on-page readiness checklist (0-100). These scores
measure whether the draft is structured the way SEO / AEO / GEO
best practices describe — not live rank, AI-citation rate, or
Core Web Vitals.

- SEO: on-page search signals (placement, metadata, structure)
- GEO: citation-readiness for generative engines (extractable
  answers, specifics) — not whether ChatGPT/Perplexity cite it
- AEO: snippet / PAA / voice readiness from the text itself
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

from acl_agent.models import ContentBrief, InternalLink, SEOAnalysis
from acl_agent.validation import (
    AI_FILLER_PHRASES,
    count_h1,
    keyword_count,
    word_count,
    word_count_band,
)


def _grade(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Fair"
    return "Needs work"


def _factor(
    name: str,
    score: int,
    maximum: int,
    note: str,
    tip: str = "",
    status: str = "available",
) -> dict[str, Any]:
    earned = max(0, min(maximum, int(score)))
    return {
        "name": name,
        "score": earned if status == "available" else None,
        "max": maximum,
        "passed": status == "available" and earned >= maximum,
        "note": note,
        "tip": tip if status == "available" and earned < maximum else "",
        "status": status,
    }


def _pack(label: str, summary: str, factors: list[dict[str, Any]], confidence: str = "medium") -> dict[str, Any]:
    usable = [f for f in factors if f.get("status") != "unavailable"]
    earned = sum(int(f["score"] or 0) for f in usable)
    maximum = sum(int(f["max"]) for f in usable)
    total = 0 if maximum <= 0 else int(round(100 * earned / maximum))
    total = max(0, min(100, total))
    tips = [f["tip"] for f in usable if f.get("tip")]
    notes = [f["note"] for f in factors if f.get("note")]
    return {
        "label": label,
        "summary": summary,
        "score": total,
        "grade": _grade(total),
        "status": "available" if usable else "unavailable",
        "factors": factors,
        "notes": notes[:8],
        "tips": tips[:6],
        "confidence": confidence,
        "earned_points": earned,
        "max_points": maximum,
    }


def _plain_text(markdown: str) -> str:
    text = re.sub(r"<[^>]+>", " ", markdown)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`>]", "", text)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return text


def _first_n_words(text: str, n: int) -> str:
    words = re.findall(r"\S+", text)
    return " ".join(words[:n])


def _headings(article: str, level: int) -> list[str]:
    prefix = "#" * level
    markdown = re.findall(
        rf"^{prefix}\s+(.+)$",
        article,
        flags=re.MULTILINE,
    )
    html = re.findall(
        rf"<h{level}\b[^>]*>(.*?)</h{level}>",
        article,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = [re.sub(r"<[^>]+>", "", h).strip() for h in html]
    return markdown + [h for h in cleaned if h]


def _markdown_links(article: str) -> list[tuple[str, str]]:
    md = re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", article)
    html = re.findall(
        r'<a\b[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>',
        article,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_pairs = [
        (re.sub(r"<[^>]+>", "", text).strip(), url) for url, text in html
    ]
    return md + html_pairs


def _has_list(article: str) -> bool:
    return bool(
        re.search(
            r"(?:^\s*(?:[-*]|\d+\.)\s+\S|<(?:ul|ol)\b)",
            article,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    )


def _has_table(article: str) -> bool:
    return bool(
        re.search(
            r"(?:\|[\s:-]*-{2,}[\s:-]*\||<table\b)",
            article,
            flags=re.IGNORECASE,
        )
    )


def _h1_text(article: str) -> str:
    html = re.search(
        r"<h1\b[^>]*>(.*?)</h1>",
        article,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if html:
        return re.sub(r"<[^>]+>", "", html.group(1)).strip()
    match = re.search(r"^#\s+(.+)$", article, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


_ENTITY_STOP = {
    "the", "this", "that", "these", "those", "there", "then", "than",
    "when", "what", "where", "which", "while", "after", "before",
    "however", "therefore", "furthermore", "meanwhile", "instead",
    "although", "because", "according", "including", "using", "during",
    "chapter", "section", "table", "figure", "introduction", "conclusion",
}


def _title_case_heading_line(line: str) -> bool:
    words = re.findall(r"[A-Za-z]+", line)
    if not 2 <= len(words) <= 14:
        return False
    titled = sum(1 for word in words if word[:1].isupper())
    return titled / len(words) >= 0.8


def _named_entities(text: str) -> int:
    """Capitalization proxy, not NER. Skips title-case heading lines."""
    found: set[str] = set()
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or _title_case_heading_line(line):
            continue
        for match in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", line):
            found.add(match)
        for match in re.finditer(
            r"(?<=[a-z0-9,;:'\"”)\]]\s)\b([A-Z][a-z]{2,})\b",
            line,
        ):
            word = match.group(1)
            if word.lower() not in _ENTITY_STOP:
                found.add(word)
    return len(found)


def _question_heading(heading: str) -> bool:
    lowered = heading.lower().strip()
    if "?" in heading:
        return True
    return bool(
        re.match(
            r"^(how|what|why|when|where|which|who|can|should|does|do|is|are)\b",
            lowered,
        )
    )


def _definition_pattern(text: str, keyword: str) -> bool:
    """True only when the keyword itself is defined — not any English 'is a' clause."""
    phrase = " ".join((keyword or "").split())
    if not phrase:
        return False
    escaped = re.escape(phrase.lower())
    lowered = " ".join((text or "").lower().split())
    return bool(re.search(rf"\b{escaped}\s+(?:is|are|means|refers to)\b", lowered))


def _covers_reader_question(question: str, blocks: list[str]) -> bool:
    tokens = [t for t in re.findall(r"[a-z0-9']+", (question or "").lower()) if len(t) > 4]
    if len(tokens) < 2:
        return False
    need = max(2, (len(tokens) + 1) // 2)
    for block in blocks:
        blob = (block or "").lower()
        hits = sum(1 for token in tokens if token in blob)
        if hits >= need:
            return True
    return False


def _score_seo(
    article: str,
    brief: ContentBrief,
    seo: SEOAnalysis,
) -> dict[str, Any]:
    keyword = brief.primary_keyword.strip()
    words = word_count(article)
    h1 = _h1_text(article)
    opening = _first_n_words(_plain_text(article), 150).lower()
    h2s = _headings(article, 2)
    kw_hits = keyword_count(article, keyword) if keyword else 0
    density = (kw_hits / words * 100) if words else 0
    min_words, max_words = word_count_band(brief.target_word_count)

    # Keyword in H1
    if keyword and keyword.lower() in h1.lower():
        h1_factor = _factor(
            "Keyword in H1",
            10,
            10,
            f'H1 includes "{keyword}".',
        )
    else:
        h1_factor = _factor(
            "Keyword in H1",
            0,
            10,
            "Primary keyword is missing from the H1.",
            "Put the primary keyword in the article title (H1).",
        )

    # Keyword near opening
    if keyword and keyword.lower() in opening:
        open_factor = _factor(
            "Keyword near opening",
            10,
            10,
            "Primary keyword appears in the first 150 words.",
        )
    else:
        open_factor = _factor(
            "Keyword near opening",
            3 if kw_hits else 0,
            10,
            "Primary keyword is not near the top of the article.",
            "Mention the primary keyword in the first 100–150 words.",
        )

    # Density
    if 0.5 <= density <= 2.5:
        dens_factor = _factor(
            "Keyword density",
            10,
            10,
            f"Density is {density:.1f}% ({kw_hits} mentions).",
        )
    elif 0.2 <= density < 0.5 or 2.5 < density <= 3.5:
        dens_factor = _factor(
            "Keyword density",
            6,
            10,
            f"Density is {density:.1f}% — a bit off the 0.5–2.5% band.",
            "Keep primary-keyword density between 0.5% and 2.5%.",
        )
    else:
        dens_factor = _factor(
            "Keyword density",
            2 if kw_hits else 0,
            10,
            f"Density is {density:.1f}% ({kw_hits} mentions).",
            "Use the primary keyword naturally a few times — avoid stuffing or omitting it.",
        )

    # Meta title
    title = seo.meta_title or ""
    title_has_kw = bool(keyword and keyword.lower() in title.lower())
    title_len_ok = 30 <= len(title) <= 60
    title_pts = (5 if title_len_ok else 2) + (3 if title_has_kw else 0)
    title_factor = _factor(
        "Meta title",
        title_pts,
        8,
        f"{len(title)} characters"
        + ("; includes keyword" if title_has_kw else "; keyword missing"),
        "" if title_pts >= 8 else "Keep the meta title 30–60 characters and include the primary keyword.",
    )

    # Meta description
    desc = seo.meta_description or ""
    desc_ok = 70 <= len(desc) <= 155
    desc_factor = _factor(
        "Meta description",
        8 if desc_ok else (4 if 50 <= len(desc) <= 170 else 1),
        8,
        f"{len(desc)} characters.",
        "" if desc_ok else "Write a meta description between 70 and 155 characters.",
    )

    # Headings
    h1_count = count_h1(article)
    heading_pts = 0
    if h1_count == 1:
        heading_pts += 4
    if len(h2s) >= 4:
        heading_pts += 6
    elif len(h2s) >= 2:
        heading_pts += 3
    heading_factor = _factor(
        "Heading structure",
        heading_pts,
        10,
        f"{h1_count} H1, {len(h2s)} H2 sections.",
        "" if heading_pts >= 10 else "Use exactly one H1 and at least four H2 sections.",
    )

    # Word count
    if min_words <= words <= max_words:
        wc_factor = _factor(
            "Word count",
            10,
            10,
            f"{words} words (target {brief.target_word_count}).",
        )
    else:
        wc_factor = _factor(
            "Word count",
            4,
            10,
            f"{words} words; target band is {min_words}–{max_words}.",
            f"Aim for about {brief.target_word_count} words.",
        )

    # Internal links actually present in the markdown
    article_urls = {url.rstrip("/").lower() for _, url in _markdown_links(article)}
    brief_links = brief.internal_links or []
    if brief_links:
        matched = 0
        for link in brief_links:
            target = (link.url or "").rstrip("/").lower()
            if target and (
                target in article_urls
                or any(target in u or u in target for u in article_urls)
            ):
                matched += 1
        if matched == len(brief_links):
            link_factor = _factor(
                "Internal links",
                10,
                10,
                f"All {len(brief_links)} planned internal links appear in the article.",
            )
        elif matched:
            link_factor = _factor(
                "Internal links",
                6,
                10,
                f"{matched}/{len(brief_links)} planned internal links appear in the article.",
                "Weave every provided internal link into the article as a Markdown link.",
            )
        else:
            link_factor = _factor(
                "Internal links",
                2 if article_urls else 0,
                10,
                "Planned internal links were not used in the article body.",
                "Add Markdown links to your internal pages where they help the reader.",
            )
    elif article_urls:
        link_factor = _factor(
            "Internal links",
            6,
            10,
            f"{len(article_urls)} in-article link(s) found.",
            "Add 2–4 internal links to related pages on your site.",
        )
    else:
        link_factor = _factor(
            "Internal links",
            0,
            10,
            "No internal links found in the article.",
            "Provide internal URLs in the form and they will be woven into the draft.",
        )

    # Secondary keywords
    secondary = [kw.phrase for kw in brief.secondary_keywords if kw.phrase]
    if not secondary:
        secondary = list(seo.secondary_keywords or [])
    article_lower = article.lower()
    used = [p for p in secondary if p.lower() in article_lower]
    if secondary:
        ratio = len(used) / len(secondary)
        sec_pts = 10 if ratio >= 0.5 else (6 if ratio >= 0.25 else 2)
        sec_factor = _factor(
            "Secondary keywords",
            sec_pts,
            10,
            f"{len(used)}/{len(secondary)} secondary keywords used.",
            "" if sec_pts >= 10 else "Work more secondary keywords into headings and body copy.",
        )
    else:
        sec_factor = _factor(
            "Secondary keywords",
            4,
            10,
            "No secondary keywords were provided.",
            "Add related phrases so the article can cover the topic cluster.",
        )

    faqs = seo.faqs or []
    faq_factor = _factor(
        "FAQ block",
        8 if len(faqs) >= 3 else (4 if faqs else 0),
        8,
        f"{len(faqs)} FAQ(s).",
        "" if len(faqs) >= 3 else "Include 3–5 FAQs that match real reader questions.",
    )

    alts = seo.alt_texts or []
    alt_factor = _factor(
        "Image alt text",
        6 if len(alts) >= 2 else (3 if alts else 0),
        6,
        f"{len(alts)} alt text suggestion(s).",
        "" if len(alts) >= 2 else "Add descriptive image alt text that includes the topic.",
    )

    targeting_factors = [h1_factor, open_factor, dens_factor]
    technical_factors = [
        title_factor,
        desc_factor,
        heading_factor,
        wc_factor,
        link_factor,
        sec_factor,
        faq_factor,
        alt_factor,
    ]
    report = _pack(
        "SEO",
        "On-page search checklist: keyword placement, metadata, structure, and links — not rank or backlinks.",
        targeting_factors + technical_factors,
    )

    def _group_score(group: list[dict[str, Any]]) -> int:
        earned = sum(int(item["score"] or 0) for item in group)
        maximum = sum(int(item["max"]) for item in group)
        return 0 if maximum <= 0 else int(round(100 * earned / maximum))

    report["keyword_targeting_score"] = _group_score(targeting_factors)
    report["onpage_technical_score"] = _group_score(technical_factors)
    return report


def _score_geo(
    article: str,
    brief: ContentBrief,
    seo: SEOAnalysis,
) -> dict[str, Any]:
    plain = _plain_text(article)
    opening = _first_n_words(plain, 120)
    h2s = _headings(article, 2)
    faqs = seo.faqs or []
    lowered = article.lower()

    # Direct, quotable answer up top
    opening_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", opening) if s.strip()]
    has_direct = any(
        len(s.split()) >= 8 and not s.endswith("?")
        for s in opening_sentences[:3]
    )
    if brief.primary_keyword.lower() in opening.lower() and has_direct:
        answer_factor = _factor(
            "Direct answer up top",
            15,
            15,
            "The opening gives a citable answer that includes the topic.",
        )
    elif has_direct:
        answer_factor = _factor(
            "Direct answer up top",
            9,
            15,
            "Opening is direct but does not name the primary topic early.",
            "Lead with a 1–2 sentence answer that names the primary keyword.",
        )
    else:
        answer_factor = _factor(
            "Direct answer up top",
            4,
            15,
            "The opening does not give a stand-alone, quotable answer.",
            "Start with a clear, extractable answer an AI overview could cite.",
        )

    # Extractable H2 sections
    if len(h2s) >= 5:
        section_factor = _factor(
            "Extractable sections",
            12,
            12,
            f"{len(h2s)} H2 sections that can be cited independently.",
        )
    elif len(h2s) >= 3:
        section_factor = _factor(
            "Extractable sections",
            8,
            12,
            f"{len(h2s)} H2 sections.",
            "Add more focused H2s so AI engines can pull complete sections.",
        )
    else:
        section_factor = _factor(
            "Extractable sections",
            3,
            12,
            f"{len(h2s)} H2 sections.",
            "Break the article into 4–8 self-contained H2 sections.",
        )

    # FAQ extractability
    solid_faqs = [
        f for f in faqs
        if (f.get("question") or f.get("q"))
        and len((f.get("answer") or f.get("a") or "").split()) >= 20
    ]
    if len(solid_faqs) >= 3:
        faq_factor = _factor(
            "Citable FAQs",
            12,
            12,
            f"{len(solid_faqs)} FAQ answers long enough to cite.",
        )
    elif faqs:
        faq_factor = _factor(
            "Citable FAQs",
            6,
            12,
            "FAQs exist but answers are short or incomplete.",
            "Write 2–4 sentence FAQ answers that stand on their own.",
        )
    else:
        faq_factor = _factor(
            "Citable FAQs",
            0,
            12,
            "No FAQs to extract.",
            "Add FAQs so answer engines can quote Q&A pairs.",
        )

    # Specifics / entities
    numbers = len(re.findall(r"\b\d+(?:[.,]\d+)?\s?(?:%|inches?|feet|mins?|hours?|days?|oz|lbs?)?\b", plain))
    entities = _named_entities(plain)
    specifics = numbers + entities
    if specifics >= 12:
        spec_factor = _factor(
            "Citable specifics",
            12,
            12,
            f"{numbers} numeric details and {entities} capitalized-name proxies (not NER).",
        )
    elif specifics >= 5:
        spec_factor = _factor(
            "Citable specifics",
            7,
            12,
            f"{numbers} numeric details and {entities} capitalized-name proxies (not NER).",
            "Add more concrete names, measurements, or examples AI systems can cite.",
        )
    else:
        spec_factor = _factor(
            "Citable specifics",
            3,
            12,
            "Few numbers or named entities found.",
            "Ground claims in named products, materials, or verifiable details from your brief.",
        )

    filler_hits = sum(1 for phrase in AI_FILLER_PHRASES if phrase in lowered)
    if filler_hits == 0:
        filler_factor = _factor(
            "Low generic filler",
            10,
            10,
            "No common AI filler phrases detected.",
        )
    elif filler_hits <= 2:
        filler_factor = _factor(
            "Low generic filler",
            6,
            10,
            f"{filler_hits} generic filler phrase(s).",
            "Replace stock phrases with specific editorial language.",
        )
    else:
        filler_factor = _factor(
            "Low generic filler",
            2,
            10,
            f"{filler_hits} generic filler phrases.",
            "Cut phrases like 'in today's world' so generative engines treat the copy as original.",
        )

    structure_pts = 0
    if _has_list(article):
        structure_pts += 6
    if _has_table(article):
        structure_pts += 4
    structure_factor = _factor(
        "Extractable lists/tables",
        min(10, structure_pts),
        10,
        "Lists and tables help models quote structured facts."
        if structure_pts
        else "No lists or tables found.",
        "" if structure_pts >= 10 else "Add a comparison table or a scannable list of takeaways.",
    )

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
    short_defs = [
        p for p in paragraphs
        if 20 <= len(p.split()) <= 60 and not p.startswith("#")
    ]
    if len(short_defs) >= 3:
        para_factor = _factor(
            "Self-contained paragraphs",
            10,
            10,
            f"{len(short_defs)} paragraphs are snippet-sized (20–60 words).",
        )
    elif short_defs:
        para_factor = _factor(
            "Self-contained paragraphs",
            6,
            10,
            "A few paragraphs are the right length to quote.",
            "Mix in 20–60 word paragraphs that fully answer one point.",
        )
    else:
        para_factor = _factor(
            "Self-contained paragraphs",
            3,
            10,
            "Paragraphs are not sized for easy citation.",
            "Write some standalone 20–60 word paragraphs generative engines can quote.",
        )

    brand = (brief.brand_name or "").strip()
    brand_ok = bool(brand) and brand.lower() not in {"blog agent", "acl"} and brand.lower() in lowered
    facts_ok = any(
        (fact.name or "").lower() in lowered
        for fact in (brief.product_facts or [])
        if fact.name
    )
    if brand_ok or facts_ok:
        brand_factor = _factor(
            "Brand / entity grounding",
            8,
            8,
            "Article mentions the brand or provided product facts.",
        )
    else:
        brand_factor = _factor(
            "Brand / entity grounding",
            3,
            8,
            "Little brand or product grounding found.",
            "Name your brand or real products where it helps the reader decide.",
        )

    depth_patterns = [
        r"\bit depends\b",
        r"\btrade-?offs?\b",
        r"\bthe catch\b",
        r"\brather than\b",
        r"\bskip (?:this|that|the|them)\b",
        r"\b(?:i|we) (?:recommend|prefer|would(?:n't)?)\b",
        r"\bworth it (?:if|when)\b",
        r"\bdon't bother\b",
    ]
    depth = 0
    for sentence in re.split(r"(?<=[.!?])\s+", lowered):
        if len(sentence.split()) < 10:
            continue
        if any(re.search(pattern, sentence) for pattern in depth_patterns):
            depth += 1
    if depth >= 2:
        depth_factor = _factor(
            "Editorial judgment language",
            11,
            11,
            "Phrase-level proxy for a distinct take — not a true originality check.",
        )
    elif depth == 1:
        depth_factor = _factor(
            "Editorial judgment language",
            6,
            11,
            "Some judgment phrasing is present (proxy, not proof of a unique angle).",
            "Add a clear take: what to skip, a trade-off, or when the usual advice fails.",
        )
    else:
        depth_factor = _factor(
            "Editorial judgment language",
            3,
            11,
            "No judgment phrasing detected (this is a phrase proxy, not NER).",
            "State a unique angle so AI engines have a reason to cite you over competitors.",
        )

    return _pack(
        "GEO",
        "On-page citation-readiness for generative engines — not live ChatGPT/Perplexity citation rate.",
        [
            answer_factor,
            section_factor,
            faq_factor,
            spec_factor,
            filler_factor,
            structure_factor,
            para_factor,
            brand_factor,
            depth_factor,
        ],
    )


def _score_aeo(
    article: str,
    brief: ContentBrief,
    seo: SEOAnalysis,
) -> dict[str, Any]:
    h2s = _headings(article, 2)
    h3s = _headings(article, 3)
    headings = h2s + h3s
    faqs = seo.faqs or []
    plain = _plain_text(article)
    opening = _first_n_words(plain, 200)
    you_count = len(re.findall(r"\byou(?:r|rs|self)?\b", plain, flags=re.IGNORECASE))
    words = max(word_count(article), 1)

    q_headings = [h for h in headings if _question_heading(h)]
    if len(q_headings) >= 3:
        qh_factor = _factor(
            "Question-style headings",
            15,
            15,
            f"{len(q_headings)} headings match how people ask.",
        )
    elif q_headings:
        qh_factor = _factor(
            "Question-style headings",
            8,
            15,
            f"{len(q_headings)} question-style heading(s).",
            "Turn more H2s into the questions readers actually type or say.",
        )
    else:
        qh_factor = _factor(
            "Question-style headings",
            2,
            15,
            "Headings are not framed as questions.",
            "Use headings like 'How do I…' or 'What is…' for snippet eligibility.",
        )

    # Immediate answer after H2: next non-empty line is a paragraph.
    immediate = 0
    lines = article.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^##\s+\S", line) or re.match(r"<h2\b", line, flags=re.I):
            for follow in lines[i + 1:]:
                if not follow.strip():
                    continue
                if follow.startswith("#") or re.match(r"<h[1-3]\b", follow, flags=re.I):
                    break
                if follow.startswith("- ") or follow.startswith("|") or re.search(r"<(?:ul|ol|li|p)\b", follow, flags=re.I):
                    immediate += 1
                    break
                if len(follow.split()) >= 8:
                    immediate += 1
                break
    if h2s and immediate / max(len(h2s), 1) >= 0.6:
        imm_factor = _factor(
            "Answer right after headings",
            15,
            15,
            "Most H2s are followed by a direct answer.",
        )
    elif immediate:
        imm_factor = _factor(
            "Answer right after headings",
            8,
            15,
            f"{immediate}/{len(h2s)} H2s open with a direct answer.",
            "Put a 1–2 sentence answer immediately under each H2 before expanding.",
        )
    else:
        imm_factor = _factor(
            "Answer right after headings",
            3,
            15,
            "Sections do not open with a direct answer.",
            "Lead each section with a snippet-ready one-sentence answer.",
        )

    if len(faqs) >= 3:
        faq_factor = _factor(
            "FAQ coverage",
            15,
            15,
            f"{len(faqs)} FAQs ready for People Also Ask / voice answers.",
        )
    elif faqs:
        faq_factor = _factor(
            "FAQ coverage",
            8,
            15,
            f"{len(faqs)} FAQ(s).",
            "Add at least three FAQs that match related searches.",
        )
    else:
        faq_factor = _factor(
            "FAQ coverage",
            0,
            15,
            "No FAQs.",
            "Enable Include FAQ so answer engines can surface Q&A pairs.",
        )

    snippet_pts = 0
    if _has_list(article):
        snippet_pts += 8
    if _has_table(article):
        snippet_pts += 4
    snippet_factor = _factor(
        "Snippet formats",
        snippet_pts,
        12,
        "Lists and tables match featured-snippet layouts."
        if snippet_pts
        else "No list or table snippet formats.",
        "" if snippet_pts >= 12 else "Add a numbered how-to list or a comparison table.",
    )

    if _definition_pattern(opening, brief.primary_keyword):
        def_factor = _factor(
            "Definition snippet",
            12,
            12,
            "Opening includes a definition of the primary keyword.",
        )
    else:
        def_factor = _factor(
            "Definition snippet",
            4,
            12,
            "No clear 'X is…' definition near the top.",
            f'Open with a definition: "{brief.primary_keyword} is…".',
        )

    paras = [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
    snippet_paras = [p for p in paras[:6] if 40 <= len(p.split()) <= 60]
    if snippet_paras:
        conc_factor = _factor(
            "Concise snippet block",
            10,
            10,
            "A 40–60 word paragraph near the top is snippet-sized.",
        )
    elif any(25 <= len(p.split()) <= 80 for p in paras[:6]):
        conc_factor = _factor(
            "Concise snippet block",
            6,
            10,
            "Early paragraphs are close to snippet length.",
            "Include one 40–60 word paragraph that fully answers the query.",
        )
    else:
        conc_factor = _factor(
            "Concise snippet block",
            3,
            10,
            "No early paragraph is snippet-length.",
            "Add a tight 40–60 word answer block under the introduction.",
        )

    questions = brief.reader_questions or []
    blocks = (
        headings
        + [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
        + [
            f"{item.get('question', '')} {item.get('answer', '')}"
            for item in faqs
        ]
    )
    answered = sum(1 for question in questions if _covers_reader_question(question, blocks))
    if questions and answered >= min(2, len(questions)):
        rq_factor = _factor(
            "Reader questions answered",
            11,
            11,
            f"{answered}/{len(questions)} planned reader questions have same-block token overlap (rough gate).",
        )
    elif questions and answered:
        rq_factor = _factor(
            "Reader questions answered",
            6,
            11,
            f"{answered}/{len(questions)} reader questions have same-block overlap (rough gate, not ground truth).",
            "Answer each reader question in a heading, paragraph, or FAQ.",
        )
    elif questions:
        rq_factor = _factor(
            "Reader questions answered",
            2,
            11,
            "Planned reader questions are not clearly answered in a heading, paragraph, or FAQ.",
            "Mirror People Also Ask phrasing in H2s and FAQs.",
        )
    else:
        rq_factor = _factor(
            "Reader questions answered",
            5,
            11,
            "No reader questions were supplied on the brief.",
            "Add the questions your audience actually asks.",
        )

    you_density = you_count / words
    if you_density >= 0.012:
        pov_factor = _factor(
            "Voice-friendly address",
            10,
            10,
            "Second-person language fits spoken / voice queries.",
        )
    elif you_count >= 8:
        pov_factor = _factor(
            "Voice-friendly address",
            6,
            10,
            "Some direct address is present.",
            "Talk to the reader as 'you' so voice answers sound natural.",
        )
    else:
        pov_factor = _factor(
            "Voice-friendly address",
            3,
            10,
            "Little second-person language.",
            "Use 'you' so answers match how people ask voice assistants.",
        )

    return _pack(
        "AEO",
        "On-page snippet / People Also Ask / voice readiness — not a prediction of featured-snippet wins.",
        [
            qh_factor,
            imm_factor,
            faq_factor,
            snippet_factor,
            def_factor,
            conc_factor,
            rq_factor,
            pov_factor,
        ],
    )


def _score_aio(
    article: str,
    brief: ContentBrief,
    seo: SEOAnalysis,
    signals: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    signals = signals or {}
    plain = _plain_text(article)
    opening = _first_n_words(plain, 80)
    h2s = _headings(article, 2)
    entities = _named_entities(plain)
    has_summary = 25 <= len(opening.split()) <= 90
    numbers = len(re.findall(r"\b\d+(?:[.,]\d+)?\b", plain))
    schema = signals.get("schema_types") or []
    author = signals.get("author") or ""
    factors = [
        _factor("Entity clarity", 12 if entities >= 6 else (6 if entities else 2), 12, f"{entities} capitalized-name proxies.", "Name places, products, or people AI systems can attach to."),
        _factor("Factual clarity", 12 if numbers >= 8 else (6 if numbers else 2), 12, f"{numbers} numeric details.", "Add dated, sourced figures — never invent them."),
        _factor("Structured formatting", 12 if (_has_list(article) or _has_table(article)) else 4, 12, "Lists/tables present." if _has_list(article) or _has_table(article) else "No list or table.", "Add a comparison table or steps list."),
        _factor("Direct answer quality", 12 if len(h2s) >= 3 else 5, 12, f"{len(h2s)} H2s that can host direct answers.", "Lead each H2 with a 1–2 sentence answer."),
        _factor("Summary quality", 12 if has_summary else 5, 12, "Opening can stand alone." if has_summary else "No short standalone summary.", "Write a 40–60 word answer under the H1."),
        _factor("Quotable statements", 10 if re.search(r"\b(i recommend|the catch|rather than|in practice)\b", plain.lower()) else 4, 10, "Judgment phrasing found." if re.search(r"\b(i recommend|the catch|rather than|in practice)\b", plain.lower()) else "Few quotable takes.", "Add one specific, reusable recommendation."),
        _factor("Original insights", 10 if re.search(r"\b(i recommend|it depends|the catch|rather than)\b", plain.lower()) else 4, 10, "Point-of-view language found." if re.search(r"\bit depends\b", plain.lower()) else "Little original take detected.", "State a clear point of view."),
        _factor("Citation-ready claims", 10 if numbers >= 4 else 3, 10, "Numeric or dated claims that can be sourced." if numbers else "Few citation-ready claims.", "Attach a source to each statistic."),
        _factor(
            "Author and trust signals",
            10 if (author or schema) else 0,
            10,
            "Author or schema detected." if author or schema else "Author/schema not present in this extract.",
            "Show an author and Article/FAQ schema.",
            status="available" if (author or schema or article) else "unavailable",
        ),
    ]
    packed = _pack(
        "AIO",
        "AI-search structure and citation-readiness — not live AI visibility.",
        factors,
        confidence="high" if len(plain.split()) >= 120 else "medium",
    )
    return packed


def _score_sxo(
    article: str,
    brief: ContentBrief,
    seo: SEOAnalysis,
    signals: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    plain = _plain_text(article)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", plain) if s.strip()]
    avg = (sum(len(s.split()) for s in sentences) / len(sentences)) if sentences else 0
    h2s = _headings(article, 2)
    has_toc = bool(re.search(r"table of contents|in this (guide|article)", article, re.I))
    intro = _first_n_words(plain, 60)
    intro_ok = 20 <= len(intro.split()) <= 80
    title_ok = 20 <= len((brief.title or "").strip()) <= 70
    paras = [p.strip() for p in re.split(r"\n\s*\n", plain) if p.strip()]
    para_avg = (sum(len(p.split()) for p in paras) / len(paras)) if paras else 0
    intent_ok = bool(brief.primary_keyword) and brief.primary_keyword.split()[0].lower() in plain.lower()
    scannable = _has_list(article) or len(h2s) >= 4
    factors = [
        _factor("Search intent match", 14 if intent_ok else 6, 14, "Opening stays on the target query." if intent_ok else "Intent is unclear in the extract.", "Restate the reader job in the first two sentences."),
        _factor("Title quality", 12 if title_ok else 6, 12, "Title length is snippet-friendly." if title_ok else "Title is missing, short, or bloated.", "Keep the title specific and under ~70 characters."),
        _factor("Introduction quality", 14 if intro_ok else 6, 14, "Intro is snippet-sized." if intro_ok else "Intro is missing or bloated.", "Open with the reader outcome in 2 sentences."),
        _factor("Heading structure", 12 if len(h2s) >= 4 else 5, 12, f"{len(h2s)} H2s.", "Use 4–8 descriptive H2s."),
        _factor("Scannability", 12 if scannable else 5, 12, "Headings/lists help scanning." if scannable else "Wall of text risk.", "Add H2s and a list of takeaways."),
        _factor("Paragraph length", 12 if para_avg and para_avg <= 80 else 6, 12, f"Average paragraph {para_avg:.0f} words." if paras else "Paragraphs could not be split.", "Keep paragraphs under ~60 words."),
        _factor("Lists and tables", 12 if (_has_list(article) or _has_table(article)) else 4, 12, "Lists or tables present." if _has_list(article) or _has_table(article) else "No list or table.", "Add a comparison table or steps list."),
        _factor("Navigation", 12 if has_toc or len(h2s) >= 5 else 5, 12, "TOC or many H2s." if has_toc or len(h2s) >= 5 else "No table of contents.", "Add a jump-link table of contents."),
        _factor("FAQ coverage", 12 if seo.faqs else 4, 12, "FAQ present." if seo.faqs else "No FAQ.", "Answer remaining questions in a FAQ."),
        _factor("CTA relevance", 12 if re.search(r"\b(start|book|try|download|read next|check|shop)\b", plain.lower()) else 5, 12, "A next step is suggested." if re.search(r"\b(start|book|try|check)\b", plain.lower()) else "No clear next step.", "End with one relevant action."),
        _factor("Mobile reading signals", 12 if avg and avg <= 24 and len(h2s) >= 3 else 5, 12, "Short blocks + headings." if avg and avg <= 24 else "Long blocks on mobile.", "Keep paragraphs under ~60 words."),
    ]
    return _pack(
        "SXO",
        "Search-experience / scanability checklist — not a UX lab measurement.",
        factors,
        confidence="high" if len(plain.split()) >= 120 else "medium",
    )


def score_article(
    article: str,
    brief: ContentBrief,
    seo: SEOAnalysis,
    signals: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Return SEO, GEO, AEO, AIO, and SXO checklist reports plus overall.
    """
    seo_report = _score_seo(article, brief, seo)
    geo_report = _score_geo(article, brief, seo)
    aeo_report = _score_aeo(article, brief, seo)
    aio_report = _score_aio(article, brief, seo, signals)
    sxo_report = _score_sxo(article, brief, seo, signals)
    overall = round(
        (
            seo_report["score"]
            + geo_report["score"]
            + aeo_report["score"]
            + aio_report["score"]
            + sxo_report["score"]
        )
        / 5
    )
    return {
        "overall": overall,
        "overall_grade": _grade(overall),
        "seo": seo_report,
        "geo": geo_report,
        "aeo": aeo_report,
        "aio": aio_report,
        "sxo": sxo_report,
    }


def parse_internal_links(raw: str) -> list[InternalLink]:
    """
    Parse a user-supplied internal-link field.

    Accepted lines:
      https://example.com/page
      Anchor text | https://example.com/page
      Anchor text | https://example.com/page | why it belongs
    """
    links: list[InternalLink] = []
    if not raw or not raw.strip():
        return links

    seen: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        parts = [p for p in parts if p]
        if not parts:
            continue

        url = ""
        anchor = ""
        reason = "User-provided internal link"
        for part in parts:
            if re.match(r"^https?://", part, flags=re.IGNORECASE):
                url = part
                break
        if not url:
            continue
        others = [p for p in parts if p != url]
        if others:
            anchor = others[0]
            if len(others) > 1:
                reason = others[1]
        if not anchor:
            path = urlparse(url).path.rstrip("/")
            slug = path.split("/")[-1] if path else ""
            anchor = slug.replace("-", " ").replace("_", " ").strip() or url

        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        links.append(
            InternalLink(
                anchor_text=anchor[:200],
                url=url[:500],
                reason=reason[:300],
            )
        )

    return links
