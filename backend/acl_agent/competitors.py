"""
Competitor analysis: scrape a source blog, run a live SERP snapshot,
score ranking pages, and surface search intent plus content gaps.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from acl_agent.auto_brief import analyze_serp
from acl_agent.config import logger
from acl_agent.models import ContentBrief, SEOAnalysis
from acl_agent.scoring import score_article
from acl_agent.validation import word_count as count_words

ProgressFn = Optional[Callable[[str, str], None]]

HIGH_AUTHORITY_HOSTS = {
    "wikipedia.org",
    "nytimes.com",
    "forbes.com",
    "hubspot.com",
    "shopify.com",
    "amazon.com",
    "microsoft.com",
    "google.com",
    "apple.com",
    "zdnet.com",
    "wired.com",
    "techcrunch.com",
    "cnet.com",
    "pcmag.com",
    "tomsguide.com",
    "wirecutter.com",
    "nytimes.com",
    "bbc.com",
    "theguardian.com",
    "harvard.edu",
    "mit.edu",
    "moz.com",
    "semrush.com",
    "ahrefs.com",
    "searchengineland.com",
    "contentmarketinginstitute.com",
    "neilpatel.com",
    "backlinko.com",
    "hootsuite.com",
    "salesforce.com",
    "ibm.com",
    "oracle.com",
}

COMMERCIAL_TERMS = (
    "best", "vs", "versus", "compare", "comparison", "review",
    "top", "tools", "software", "pricing", "price", "buy",
    "alternative", "alternatives", "for", "ecommerce", "shopify",
)
INFO_TERMS = (
    "how", "what", "why", "guide", "tutorial", "learn",
    "explained", "tips", "examples", "meaning", "definition",
)
NAV_TERMS = (
    "login", "official", "homepage", "home", "about", "contact",
    "docs", "documentation", "app",
)
USER_AGENT = (
    "Mozilla/5.0 (compatible; ACLBlogAgent/1.0; "
    "+https://blog-agent.local)"
)


def _emit(on_progress: ProgressFn, stage: str, message: str) -> None:
    if on_progress:
        on_progress(stage, message)


def _host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _same_site(url_a: str, url_b: str) -> bool:
    a, b = _host(url_a), _host(url_b)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def _favicon(url: str) -> str:
    host = _host(url) or "example.com"
    return f"https://www.google.com/s2/favicons?domain={host}&sz=32"


def _authority(url: str) -> str:
    host = _host(url)
    if not host:
        return "Emerging"
    if any(host == d or host.endswith("." + d) for d in HIGH_AUTHORITY_HOSTS):
        return "High authority"
    parts = host.split(".")
    if len(parts) >= 2 and parts[-1] in {"edu", "gov"}:
        return "High authority"
    if len(urlparse(url).path.strip("/").split("/")) <= 1:
        return "Medium authority"
    return "Medium authority"


def _content_type(title: str, text: str) -> str:
    blob = f"{title} {text[:400]}".lower()
    if re.search(r"\b(vs\.?|versus|compar(?:e|ison))\b", blob):
        return "Comparison"
    if re.search(r"\b(best|top\s+\d+|roundup|list)\b", blob):
        return "Listicle"
    if re.search(r"\breview", blob):
        return "Review"
    if re.search(r"\b(how to|guide|tutorial|playbook|handbook)\b", blob):
        return "Editorial guide"
    if re.search(r"\b(pricing|buy|shop|product)\b", blob):
        return "Product page"
    return "Editorial guide"


def _relative_updated(dt: Optional[datetime]) -> str:
    if not dt:
        return "Updated recently"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    days = max(0, (datetime.now(timezone.utc) - dt).days)
    if days <= 0:
        return "Updated today"
    if days == 1:
        return "Updated 1 day ago"
    if days < 7:
        return f"Updated {days} days ago"
    weeks = days // 7
    if weeks == 1:
        return "Updated 1 week ago"
    if weeks < 8:
        return f"Updated {weeks} weeks ago"
    months = max(1, days // 30)
    if months == 1:
        return "Updated 1 month ago"
    return f"Updated {months} months ago"


def _parse_datetime(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(value.replace("Z", "+0000"), fmt)
            return parsed
        except Exception:
            continue
    return None


def _detect_keyword(title: str, h1: str, url: str) -> str:
    raw = (h1 or title or "").strip()
    raw = re.split(r"\s*[|\u2013\u2014]\s*", raw)[0]
    raw = re.sub(
        r"^(how to|the complete|ultimate|a complete|complete)\s+",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    raw = re.sub(r"\s+", " ", raw).strip(" -:|")
    if len(raw) >= 3:
        return raw[:80]
    path = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", path).strip()
    return slug[:80]


def _count_hits(text: str, terms: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for term in terms if re.search(rf"\b{re.escape(term)}\b", lowered))


def _intent_weights(text: str) -> dict[str, int]:
    commercial = _count_hits(text, COMMERCIAL_TERMS) + 1
    informational = _count_hits(text, INFO_TERMS) + 1
    navigational = _count_hits(text, NAV_TERMS) + 1
    return {
        "commercial": commercial,
        "informational": informational,
        "navigational": navigational,
    }


def _normalize_intents(weights: dict[str, int]) -> dict[str, int]:
    commercial = max(0, weights.get("commercial", 0))
    informational = max(0, weights.get("informational", 0))
    navigational = max(0, weights.get("navigational", 0))
    total = commercial + informational + navigational or 1
    commercial = round(commercial / total * 100)
    informational = round(informational / total * 100)
    navigational = max(0, 100 - commercial - informational)
    return {
        "commercial": commercial,
        "informational": informational,
        "navigational": navigational,
    }


def _fetch_html(url: str) -> tuple[str, dict[str, str]]:
    response = requests.get(
        url,
        timeout=12,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True,
    )
    response.raise_for_status()
    headers = {k.lower(): v for k, v in response.headers.items()}
    return response.text, headers


def _heading_texts(root, tag: str) -> list[str]:
    """Count real <h1>/<h2> tags in article content, not page chrome."""
    if root is None:
        return []
    skip_parents = ("nav", "footer", "aside", "form", "iframe", "noscript")
    seen: set[str] = set()
    texts: list[str] = []
    for node in root.find_all(tag, recursive=True):
        if getattr(node, "name", "").lower() != tag:
            continue
        if node.find_parent(skip_parents):
            continue
        header_parent = node.find_parent("header")
        if header_parent and not header_parent.find_parent("article"):
            continue
        if node.has_attr("hidden") or str(node.get("aria-hidden", "")).lower() == "true":
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        if len(text) < 2:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        texts.append(text)
    return texts


_CHROME_TAGS = [
    "script", "style", "noscript", "svg", "nav", "footer", "aside",
    "iframe", "form", "template", "button",
]
_CHROME_HINT = re.compile(
    r"(announcement|mega-menu|menu-drawer|cart-drawer|predictive-search|"
    r"header-wrapper|breadcrumb|site-nav|toolbar|newsletter|cookie|"
    r"popup|modal|drawer|skip-to-content|visually-hidden)",
    re.IGNORECASE,
)
_CONTENT_SELECTORS = [
    "[itemprop='articleBody']",
    ".article-template .rte",
    ".article__content",
    ".article-content",
    ".blog-post-content",
    ".article-body",
    ".post-content",
    ".entry-content",
    "article .rte",
    "div.rte",
    "article",
    "main",
]


def _strip_chrome(root) -> None:
    if root is None:
        return
    for tag in list(root.find_all(_CHROME_TAGS)):
        tag.decompose()
    for tag in list(root.find_all(True)):
        blob = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
        name = (tag.name or "").lower()
        if name in {"header"} and not tag.find_parent("article"):
            tag.decompose()
            continue
        if _CHROME_HINT.search(blob):
            tag.decompose()


def _content_root(soup):
    for selector in _CONTENT_SELECTORS:
        try:
            node = soup.select_one(selector)
        except Exception:
            node = None
        if node is None:
            continue
        if getattr(node, "name", "") != "article":
            parent_article = node.find_parent("article")
            if parent_article is not None and parent_article.find(["h1", "h2"]):
                node = parent_article
        probe = BeautifulSoup(str(node), "html.parser")
        _strip_chrome(probe)
        text = probe.get_text(" ", strip=True)
        if count_words(text) >= 80:
            return node
    return soup.find("article") or soup.find("main") or soup.body or soup


def _html_to_markdown(root) -> str:
    if root is None:
        return ""
    chunks: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        name = (el.name or "").lower()
        if name == "p" and el.find_parent(["li", "h1", "h2", "h3", "h4", "blockquote"]):
            continue
        text = " ".join(el.get_text(" ", strip=True).split())
        if len(text) < 2:
            continue
        if name == "h1":
            chunks.append(f"# {text}")
        elif name == "h2":
            chunks.append(f"## {text}")
        elif name == "h3":
            chunks.append(f"### {text}")
        elif name == "h4":
            chunks.append(f"#### {text}")
        elif name == "li":
            chunks.append(f"- {text}")
        elif name == "blockquote":
            chunks.append(f"> {text}")
        else:
            chunks.append(text)
    return "\n\n".join(chunks)


def _extract_readable_article(soup) -> tuple[str, Any]:
    """Return clean markdown from the blog body, never raw page HTML."""
    root = _content_root(soup)
    cleaned = BeautifulSoup(str(root), "html.parser")
    _strip_chrome(cleaned)
    markdown = _html_to_markdown(cleaned)
    words = count_words(markdown)
    return markdown, cleaned, words


def _page_stats(url: str, html: str, headers: dict[str, str]) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()

    markdown, cleaned, md_words = _extract_readable_article(soup)
    h1_headings = _heading_texts(cleaned, "h1")
    h2_headings = _heading_texts(cleaned, "h2")
    h1 = h1_headings[0] if h1_headings else ""
    if not title:
        title = h1 or url

    logger.info(
        "Heading audit %s: %s H1 %s | %s H2 %s | extract_words=%s",
        url,
        len(h1_headings),
        h1_headings,
        len(h2_headings),
        h2_headings,
        md_words,
    )

    text = cleaned.get_text(" ", strip=True) if cleaned else ""
    words = md_words or count_words(text)
    article_html = markdown[:80000]

    modified = headers.get("last-modified", "")
    if not modified:
        meta = soup.find("meta", attrs={"property": "article:modified_time"})
        if meta:
            modified = meta.get("content") or ""
    if not modified:
        time_el = soup.find("time")
        if time_el:
            modified = time_el.get("datetime") or time_el.get_text(" ", strip=True)

    return {
        "url": url,
        "title": title[:240],
        "h1": h1[:240],
        "h1_count": len(h1_headings),
        "h2_count": len(h2_headings),
        "h1_headings": h1_headings,
        "h2_headings": h2_headings,
        "word_count": words,
        "text": text[:20000],
        "article_html": article_html,
        "source_markdown": markdown[:45000],
        "extract_ok": words >= 100,
        "updated": _relative_updated(_parse_datetime(modified)),
        "content_type": _content_type(title or h1, text),
        "authority": _authority(url),
        "favicon": _favicon(url),
        "domain": _host(url) or url,
    }


def _heuristic_scores(
    keyword: str,
    title: str,
    text: str,
    words: int,
    h1_count: int,
    h2_count: int,
) -> dict[str, int]:
    blob = f"{title} {text[:1500]}".lower()
    kw = (keyword or "").lower()
    seo = 38
    geo = 34
    aeo = 32
    if kw and kw in (title or "").lower():
        seo += 16
        geo += 8
    if kw and kw in blob:
        seo += 8
        aeo += 8
    if h1_count:
        seo += 8
    if h2_count >= 3:
        seo += 8
        geo += 10
    if words >= 800:
        seo += 8
    if words >= 1500:
        seo += 6
        geo += 8
    if "?" in text[:2000] or re.search(r"\b(faq|how do|what is)\b", blob):
        aeo += 16
        geo += 10
    if re.search(r"\b(vs|compare|table|pros|cons)\b", blob):
        seo += 6
        aeo += 8
    if re.search(r"\b(according to|study|source|research)\b", blob):
        geo += 12
    return {
        "seo": min(96, seo),
        "geo": min(94, geo),
        "aeo": min(94, aeo),
    }


def _score_page(keyword: str, page: dict[str, Any]) -> dict[str, int]:
    title = page.get("title") or keyword or "Untitled page"
    brief_title = title if len(title) >= 5 else f"{keyword} guide"
    article = page.get("article_html") or page.get("text") or title
    try:
        brief = ContentBrief(
            primary_keyword=(keyword or title)[:200] or "blog",
            title=brief_title[:200],
            article_angle=f"On-page analysis of ranking content for {keyword}.",
            target_word_count=max(300, min(8000, int(page.get("word_count") or 1500))),
            website=f"https://{page.get('domain') or 'example.com'}",
        )
        seo_model = SEOAnalysis(
            primary_keyword=brief.primary_keyword,
            meta_title=title[:70],
            meta_description=(page.get("text") or "")[:160],
        )
        report = score_article(article, brief, seo_model)
        return {
            "seo": int(report["seo"]["score"]),
            "geo": int(report["geo"]["score"]),
            "aeo": int(report["aeo"]["score"]),
        }
    except Exception as error:
        logger.warning("score_article failed for %s: %s", page.get("url"), error)
        return _heuristic_scores(
            keyword,
            title,
            page.get("text") or "",
            int(page.get("word_count") or 0),
            int(page.get("h1_count") or 0),
            int(page.get("h2_count") or 0),
        )


def _opportunity_signals(page: dict[str, Any]) -> list[dict[str, str]]:
    blob = f"{page.get('title', '')} {page.get('text', '')[:2500]}".lower()
    signals: list[dict[str, str]] = []

    def add(kind: str, label: str) -> None:
        if len(signals) < 3:
            signals.append({"kind": kind, "label": label})

    if re.search(r"\b(vs|versus|compar(?:e|ison)|alternative)\b", blob):
        add("positive", "Strong product comparisons")
    if re.search(r"\b(faq|people also|common questions)\b", blob) or blob.count("?") >= 3:
        add("positive", "Answers common questions")
    if re.search(r"\b(workflow|playbook|step-by-step|how to)\b", blob):
        add("positive", "Clear process walkthrough")
    if re.search(r"\b(table|pros|cons|criteria)\b", blob):
        add("positive", "Clear buying criteria")
    if not re.search(r"\b(shopify|woocommerce|cart|checkout|ecommerce|store)\b", blob):
        add("warning", "No ecommerce workflow")
    if not re.search(r"\b(faq|questions)\b", blob) and blob.count("?") < 2:
        add("warning", "Missing FAQ coverage")
    if int(page.get("word_count") or 0) < 900:
        add("warning", "Thin on supporting detail")
    if not re.search(r"\b(example|case study|template)\b", blob):
        add("warning", "Few practical examples")
    if not signals:
        add("positive", "Solid on-page structure")
    return signals


def _scrape_url(url: str) -> Optional[dict[str, Any]]:
    try:
        html, headers = _fetch_html(url)
        return _page_stats(url, html, headers)
    except Exception as error:
        logger.warning("Could not scrape %s: %s", url, error)
        return None


def _fallback_page(url: str, title: str, snippet: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": title or url,
        "h1": title or "",
        "h1_count": 1 if title else 0,
        "h2_count": 0,
        "h1_headings": [title] if title else [],
        "h2_headings": [],
        "word_count": max(400, count_words(snippet) * 40),
        "text": snippet,
        "article_html": f"<h1>{title}</h1><p>{snippet}</p>",
        "source_markdown": "",
        "extract_ok": False,
        "updated": "Updated recently",
        "content_type": _content_type(title, snippet),
        "authority": _authority(url),
        "favicon": _favicon(url),
        "domain": _host(url) or url,
    }


def _writing_cue(intent: dict[str, Any]) -> str:
    dominant = intent.get("heading") or "Readers are researching"
    if "compar" in dominant.lower():
        return "Lead with a comparison the searcher can scan, then name a clear recommendation."
    if "learn" in dominant.lower() or "research" in dominant.lower():
        return "Answer the core question in the first screen, then expand with steps and examples."
    return "Make the destination obvious: who this is for, what they get, and the next step."


def _intent_heading(weights: dict[str, int]) -> str:
    ranked = sorted(weights.items(), key=lambda item: item[1], reverse=True)
    top = ranked[0][0] if ranked else "informational"
    if top == "commercial":
        return "Readers are comparing"
    if top == "navigational":
        return "Readers are looking for a destination"
    return "Readers are researching"


def _clean_section_label(text: str) -> Optional[str]:
    """Keep short section names; drop scraped list items, dates, and snippets."""
    heading = " ".join((text or "").split())
    if len(heading) < 8 or len(heading) > 70:
        return None
    if re.search(r"<[^>]+>", heading):
        return None
    if re.match(r"^\d+[\.)]", heading):
        return None
    if "·" in heading or "|" in heading:
        return None
    if re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b.*\d{4}",
        heading,
        flags=re.IGNORECASE,
    ):
        return None
    if heading.lower().startswith(("discover ", "shop ", "buy ", "subscribe")):
        return None
    if not _looks_complete(heading):
        return None
    return heading


def _looks_complete(text: str) -> bool:
    text = " ".join((text or "").split())
    if len(text) < 8:
        return False
    if text[-1] in ".!?":
        return True
    last = text.split()[-1].lower().strip(" ,;:\"'")
    return last not in {
        "a", "an", "the", "and", "or", "but", "to", "for", "of", "in",
        "on", "with", "does", "do", "is", "are", "it", "its", "this",
        "that", "than", "then", "be", "by", "from", "as",
    }


def _finished_sentence(text: str) -> str:
    text = " ".join((text or "").split())
    if not text:
        return ""
    if text[-1] not in ".!?":
        text = text.rstrip(" ,;:-") + "."
    return text


_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
_QUESTION_START = re.compile(
    r"^(how|what|why|is|does|can|when|where|who|which|should|are|do)\b",
    re.IGNORECASE,
)
_ENTITY_SKIP = {
    "table of contents", "key takeaways", "frequently asked",
    "related articles", "privacy policy", "terms of service",
    "cookie policy", "all rights reserved", "read more",
}


def _page_blob(your_page: Optional[dict[str, Any]]) -> str:
    your_text = (your_page or {}).get("text", "").lower()
    your_html = (your_page or {}).get("article_html", "").lower()
    your_h2 = " ".join((your_page or {}).get("h2_headings") or []).lower()
    return f"{your_text} {your_html} {your_h2}"


def _phrase_covered(phrase: str, blob: str) -> bool:
    tokens = [t for t in re.findall(r"[a-z0-9]+", phrase.lower()) if len(t) > 3]
    if not tokens:
        return True
    return sum(1 for t in tokens if t in blob) >= max(1, len(tokens) // 2)


def _dedupe_gaps(gaps: list[dict[str, str]], limit: int = 8) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for gap in gaps:
        key = (gap.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(gap)
        if len(unique) >= limit:
            break
    return unique


def _sort_gaps(gaps: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        gaps,
        key=lambda gap: _SEVERITY_RANK.get(str(gap.get("severity") or "low"), 9),
    )


def _missing_competitor_topics(
    your_page: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> list[str]:
    blob = _page_blob(your_page)
    missing: list[str] = []
    seen: set[str] = set()
    for competitor in competitors:
        for heading in competitor.get("h2_headings") or []:
            cleaned = _clean_section_label(heading)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen or _phrase_covered(cleaned, blob):
                continue
            seen.add(key)
            missing.append(cleaned)
    return missing


def _build_entity_gaps(
    your_page: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Named entities on ranking pages that do not appear on the user's page."""
    blob = _page_blob(your_page)
    counts: dict[str, int] = {}
    for competitor in competitors:
        text = " ".join([
            str(competitor.get("title") or ""),
            str(competitor.get("text") or "")[:4000],
        ])
        for match in re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text):
            cleaned = " ".join(match.split())
            if len(cleaned) < 6 or cleaned.lower() in _ENTITY_SKIP:
                continue
            if _phrase_covered(cleaned, blob):
                continue
            counts[cleaned] = counts.get(cleaned, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    gaps: list[dict[str, str]] = []
    for name, hits in ranked[:6]:
        gaps.append({
            "severity": "medium" if hits >= 2 else "low",
            "title": f"Missing entity: {name}",
            "description": _finished_sentence(
                f'Ranking pages mention "{name}", and your page never names it'
            ),
        })
    return gaps


def _build_paa_opportunities(
    related_queries: list[str],
    your_page: Optional[dict[str, Any]],
) -> list[dict[str, Any]]:
    blob = _page_blob(your_page)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in related_queries:
        phrase = " ".join(str(query or "").split())
        if not phrase:
            continue
        if not (phrase.endswith("?") or _QUESTION_START.match(phrase)):
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "query": phrase,
            "answered": _phrase_covered(phrase, blob),
        })
        if len(items) >= 12:
            break
    return items


def _build_recommended_structure(
    your_page: Optional[dict[str, Any]],
    common_headings: list[str],
    topical_gaps: list[dict[str, str]],
    missing_topics: list[str],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(heading: str, status: str, source: str) -> None:
        cleaned = _clean_section_label(heading) or " ".join((heading or "").split())
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        items.append({"heading": cleaned, "status": status, "source": source})

    for heading in (your_page or {}).get("h2_headings") or []:
        add(heading, "keep", "your page")
    for heading in common_headings:
        add(heading, "add", "competitor H2s")
    for heading in missing_topics:
        add(heading, "add", "competitor H2s")
    for gap in topical_gaps:
        title = str(gap.get("title") or "")
        implied = re.sub(r"^missing (?:section|core section):\s*", "", title, flags=re.I)
        if implied and implied.lower() not in {"missing faq block", "no ecommerce workflow", "shorter than ranking pages"}:
            add(implied, "add", "topical gap")
    return items[:16]


def _build_gaps(
    keyword: str,
    your_page: Optional[dict[str, Any]],
    competitors: list[dict[str, Any]],
    related_queries: list[str],
    common_headings: list[str],
) -> dict[str, Any]:
    """
    Split content gaps into keyword, topical, and entity lists.

    Also returns a combined `gaps` list (all three, severity-sorted)
    so existing readers of the flat field keep working.
    """
    blob = _page_blob(your_page)
    missing_topics = _missing_competitor_topics(your_page, competitors)

    keyword_gaps: list[dict[str, str]] = []
    query_hits = [q for q in related_queries if q and not _phrase_covered(q, blob)]
    for query in query_hits[:5]:
        keyword_gaps.append({
            "severity": "high" if not keyword_gaps else "medium",
            "title": f'Uncovered query: {query}',
            "description": _finished_sentence(
                f'People also search for "{query}", '
                "and your page does not answer that query yet"
            ),
        })

    topical_gaps: list[dict[str, str]] = []
    for topic in missing_topics[:5]:
        topical_gaps.append({
            "severity": "high",
            "title": f"Missing section: {topic}",
            "description": _finished_sentence(
                f'Ranking pages cover "{topic}", and your post does not'
            ),
        })
    seen_topics = {t.lower() for t in missing_topics}
    for heading in common_headings:
        cleaned = _clean_section_label(heading)
        if cleaned and not _phrase_covered(cleaned, blob) and cleaned.lower() not in seen_topics:
            topical_gaps.append({
                "severity": "medium",
                "title": f"Missing core section: {cleaned}",
                "description": _finished_sentence(
                    f'Several ranking pages treat "{cleaned}" as a core section, '
                    "and your draft does not"
                ),
            })
            break

    comp_words = [int(c.get("word_count") or 0) for c in competitors]
    avg_words = int(sum(comp_words) / len(comp_words)) if comp_words else 0
    your_words = int((your_page or {}).get("word_count") or 0)
    if your_page and avg_words and your_words < avg_words * 0.7:
        topical_gaps.append({
            "severity": "high",
            "title": "Shorter than ranking pages",
            "description": _finished_sentence(
                f"Your page is about {your_words:,} words, "
                f"while ranking competitors average {avg_words:,} words"
            ),
        })

    ecommerce_comp = sum(
        1 for c in competitors
        if re.search(
            r"\b(shopify|woocommerce|ecommerce|checkout|workflow)\b",
            f"{c.get('title', '')} {c.get('text', '')[:1200]}".lower(),
        )
    )
    if ecommerce_comp >= 2 and your_page and "ecommerce" not in blob and "shopify" not in blob:
        topical_gaps.append({
            "severity": "medium",
            "title": "No ecommerce workflow",
            "description": _finished_sentence(
                "Ranking pages show how this applies in a store or checkout flow, "
                "and your post never gets that specific"
            ),
        })

    faq_comp = sum(
        1 for c in competitors
        if "faq" in f"{c.get('title', '')} {c.get('text', '')[:1500]}".lower()
        or f"{c.get('text', '')}".count("?") >= 4
    )
    if faq_comp >= 2 and your_page and "faq" not in blob:
        topical_gaps.append({
            "severity": "low",
            "title": "Missing FAQ block",
            "description": _finished_sentence(
                "Answer engines reward a short set of direct questions and answers, "
                "and your page does not include an FAQ"
            ),
        })

    if not your_page:
        topical_gaps.append({
            "severity": "medium",
            "title": f"Own the {keyword} angle",
            "description": _finished_sentence(
                "Add a source URL next time to see which ranking sections you still miss"
            ),
        })

    entity_gaps = _build_entity_gaps(your_page, competitors)
    keyword_gaps = _dedupe_gaps(keyword_gaps)
    topical_gaps = _dedupe_gaps(topical_gaps)
    entity_gaps = _dedupe_gaps(entity_gaps)
    combined = _sort_gaps(keyword_gaps + topical_gaps + entity_gaps)
    if not combined:
        topical_gaps = [{
            "severity": "low",
            "title": "Sharpen the unique angle",
            "description": _finished_sentence(
                "Ranking pages overlap, so call out the audience and outcome they skip"
            ),
        }]
        combined = list(topical_gaps)
    return {
        "keyword_gaps": keyword_gaps,
        "topical_gaps": topical_gaps,
        "entity_gaps": entity_gaps,
        "gaps": combined,
        "missing_topics": missing_topics,
    }


def analyze_competitors(
    blog_url: Optional[str] = None,
    keyword: Optional[str] = None,
    on_progress: ProgressFn = None,
) -> dict[str, Any]:
    """
    Live SERP competitor snapshot plus content-gap analysis.

    Extra keys on the returned dict (plain dict, no Pydantic model):
      keyword_gaps / topical_gaps / entity_gaps: severity/title/description
      gaps: concatenation of those three, sorted by severity
      paa_opportunities: {query, answered} from related question queries
      recommended_structure: {heading, status keep|add, source}
    """
    blog_url = (blog_url or "").strip() or None
    keyword = (keyword or "").strip() or None
    if not blog_url and not keyword:
        raise ValueError("Enter a blog URL or a target keyword.")

    your_page: Optional[dict[str, Any]] = None
    if blog_url:
        _emit(on_progress, "fetch_page", "Fetching your page")
        your_page = _scrape_url(blog_url)
        if your_page is None:
            raise ValueError(
                "Could not fetch that blog URL. Check the link or enter a keyword manually."
            )
        if not keyword:
            keyword = _detect_keyword(
                your_page.get("title") or "",
                your_page.get("h1") or "",
                blog_url,
            )

    if not keyword:
        raise ValueError("Could not detect a keyword. Enter one manually.")

    _emit(on_progress, "serp", "Running SERP")
    serp = analyze_serp(keyword, max_results=8)
    if not serp.results:
        raise ValueError("No search results found for that keyword. Try a more specific phrase.")

    _emit(on_progress, "competitors", "Analyzing competitors")
    ranked = []
    for result in serp.results:
        if blog_url and _same_site(blog_url, result.url):
            continue
        ranked.append(result)
        if len(ranked) >= 5:
            break
    if not ranked:
        ranked = serp.results[:5]

    scraped_by_url: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_scrape_url, item.url): item.url for item in ranked}
        for future in as_completed(futures):
            page = future.result()
            if page:
                scraped_by_url[page["url"]] = page

    _emit(on_progress, "scoring", "Scoring")
    competitors: list[dict[str, Any]] = []
    for item in ranked:
        page = scraped_by_url.get(item.url) or _fallback_page(
            item.url, item.title, item.snippet
        )
        scores = _score_page(keyword, page)
        competitors.append({
            "url": item.url,
            "domain": page["domain"],
            "favicon": page["favicon"],
            "title": page["title"] or item.title,
            "content_type": page["content_type"],
            "authority": page["authority"],
            "word_count": page["word_count"],
            "updated": page["updated"],
            "h1_count": page["h1_count"],
            "h2_count": page["h2_count"],
            "h1_headings": page.get("h1_headings") or [],
            "h2_headings": page.get("h2_headings") or [],
            "scores": scores,
            "signals": _opportunity_signals(page),
            "snippet": item.snippet,
            "text": page.get("text") or item.snippet,
        })

    your_scores = {"seo": 0, "geo": 0, "aeo": 0}
    if your_page:
        your_scores = _score_page(keyword, your_page)

    your_intent_source = ""
    if your_page:
        your_intent_source = f"{your_page.get('title', '')} {your_page.get('text', '')[:3000]}"
    else:
        your_intent_source = keyword
    competitor_intent_source = " ".join(
        f"{c.get('title', '')} {c.get('snippet', '')}" for c in competitors
    )
    your_intent = _normalize_intents(_intent_weights(your_intent_source or keyword))
    competitor_intent = _normalize_intents(_intent_weights(competitor_intent_source or keyword))
    heading = _intent_heading(your_intent if your_page else competitor_intent)

    best = {"seo": 0, "geo": 0, "aeo": 0, "h1_count": 0, "h2_count": 0, "word_count": 0}
    best_keyword = "—"
    if competitors:
        best_seo = max(competitors, key=lambda c: c["scores"]["seo"])
        best_geo = max(competitors, key=lambda c: c["scores"]["geo"])
        best_aeo = max(competitors, key=lambda c: c["scores"]["aeo"])
        best_h1 = max(competitors, key=lambda c: int(c.get("h1_count") or 0))
        best_h2 = max(competitors, key=lambda c: int(c.get("h2_count") or 0))
        best_words = max(competitors, key=lambda c: int(c.get("word_count") or 0))
        best = {
            "seo": best_seo["scores"]["seo"],
            "geo": best_geo["scores"]["geo"],
            "aeo": best_aeo["scores"]["aeo"],
            "h1_count": best_h1.get("h1_count") or 0,
            "h2_count": best_h2.get("h2_count") or 0,
            "word_count": best_words.get("word_count") or 0,
        }
        for comp in competitors:
            if keyword.lower() in (comp.get("title") or "").lower():
                best_keyword = keyword
                break
        if best_keyword == "—":
            best_keyword = keyword

    your_keyword = "—"
    if your_page and keyword.lower() in f"{your_page.get('title', '')} {your_page.get('h1', '')}".lower():
        your_keyword = keyword
    elif your_page:
        your_keyword = "Not in H1"

    comparison = {
        "your_blog": {
            "seo": your_scores["seo"] if your_page else None,
            "geo": your_scores["geo"] if your_page else None,
            "aeo": your_scores["aeo"] if your_page else None,
            "primary_keyword": your_keyword if your_page else None,
            "h1_count": (your_page or {}).get("h1_count"),
            "h2_count": (your_page or {}).get("h2_count"),
            "word_count": (your_page or {}).get("word_count"),
        },
        "best_competitor": {
            "seo": best["seo"],
            "geo": best["geo"],
            "aeo": best["aeo"],
            "primary_keyword": best_keyword,
            "h1_count": best["h1_count"],
            "h2_count": best["h2_count"],
            "word_count": best["word_count"],
        },
    }

    gap_bundle = _build_gaps(
        keyword,
        your_page,
        competitors,
        list(serp.related_queries or []),
        list(serp.common_headings or []),
    )
    paa_opportunities = _build_paa_opportunities(
        list(serp.related_queries or []),
        your_page,
    )
    recommended_structure = _build_recommended_structure(
        your_page,
        list(serp.common_headings or []),
        gap_bundle["topical_gaps"],
        gap_bundle.get("missing_topics") or [],
    )

    source_article = ""
    source_title = ""
    source_extract_error = False
    if your_page:
        markdown = (your_page.get("source_markdown") or your_page.get("article_html") or "").strip()
        extract_ok = bool(your_page.get("extract_ok")) and count_words(markdown) >= 100
        if extract_ok and not re.search(r"<(?:html|head|nav|svg|script)\b", markdown, flags=re.I):
            source_article = markdown[:45000]
        else:
            source_extract_error = True
            source_article = ""
        source_title = your_page.get("h1") or your_page.get("title") or ""

    analyzed_at = datetime.now(timezone.utc).isoformat()
    slim_competitors = []
    for row in competitors:
        slim_competitors.append({
            "url": row.get("url"),
            "domain": row.get("domain"),
            "title": row.get("title"),
            "content_type": row.get("content_type"),
            "authority": row.get("authority"),
            "word_count": row.get("word_count"),
            "scores": row.get("scores") or {},
            "h1_count": row.get("h1_count"),
            "h2_count": row.get("h2_count"),
        })
    return {
        "blog_url": blog_url or "",
        "target_keyword": keyword,
        "analyzed_at": analyzed_at,
        "your_page": {
            "title": source_title,
            "word_count": (your_page or {}).get("word_count") or 0,
            "h1_count": (your_page or {}).get("h1_count") or 0,
            "h2_count": (your_page or {}).get("h2_count") or 0,
            "h1_headings": (your_page or {}).get("h1_headings") or [],
            "h2_headings": (your_page or {}).get("h2_headings") or [],
        } if your_page else None,
        "source_article": source_article,
        "source_title": source_title,
        "source_extract_error": source_extract_error,
        "old_scores": your_scores if your_page else {"seo": 0, "geo": 0, "aeo": 0},
        "competitors": slim_competitors,
        "intent": {
            "heading": heading,
            "your": your_intent,
            "competitor_avg": competitor_intent,
            "cue": _writing_cue({"heading": heading}),
        },
        "comparison": comparison,
        "gaps": gap_bundle["gaps"],
        "keyword_gaps": gap_bundle["keyword_gaps"],
        "topical_gaps": gap_bundle["topical_gaps"],
        "entity_gaps": gap_bundle["entity_gaps"],
        "paa_opportunities": paa_opportunities,
        "recommended_structure": recommended_structure,
        "serp": {
            "keyword": serp.keyword,
            "related_queries": serp.related_queries[:8],
            "common_headings": serp.common_headings[:8],
        },
    }
