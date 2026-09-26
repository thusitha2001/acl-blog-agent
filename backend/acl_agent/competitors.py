"""
Competitor analysis: scrape a source blog, run a live SERP snapshot,
and score ranking pages.
"""
from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from acl_agent.auto_brief import (
    SERPAnalysis,
    SERPResult,
    search_serp,
)
from acl_agent.analysis_input import (
    analysis_mode,
    average_competitor_scores,
    page_full_text,
    validate_blog_url,
)
from acl_agent.analysis_report import (
    action_plan,
    citation_opportunities,
    content_gaps,
    humanization_report,
    image_alt_report,
    originality_report,
    traffic_reasons,
)
from acl_agent.config import logger
from acl_agent.gsc_diagnosis import (
    diagnosis_window,
    build_diagnosis_summary,
    diagnose_page_visibility,
    merge_gsc_actions,
    unavailable_diagnosis,
)
from acl_agent.keywords import (
    article_intent,
    classify_page_intent,
    compare_keywords,
    is_closing_section,
    keyword_focus,
)
from acl_agent.metrics import UNAVAILABLE
from acl_agent.models import ContentBrief, SEOAnalysis
from acl_agent.readability import analyze_readability
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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
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


def _url_key(url: str) -> tuple[str, str]:
    parsed = urlparse(url or "")
    return (_host(url), parsed.path.rstrip("/").lower())


def _normalize_competitor_urls(raw: Optional[list[str]]) -> list[str]:
    urls: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in raw or []:
        url = " ".join(str(item or "").split())
        if not url:
            continue
        if not re.match(r"^https?://", url, flags=re.IGNORECASE):
            url = "https://" + url
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        key = _url_key(url)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        urls.append(url)
        if len(urls) >= 10:
            break
    return urls


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
        return "Unknown"
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
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(raw.replace("Z", "+0000"), fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except Exception:
            continue
    return None


def _slug_keyword(url: str) -> str:
    path = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", path)
    slug = re.sub(r"[^a-zA-Z0-9 ]+", " ", slug)
    skip = {
        "html", "php", "aspx", "index", "a", "an", "the", "and", "or", "for",
        "of", "to", "in", "on", "with", "create", "creating", "collections",
        "collection", "complete", "ultimate", "guide", "ideas", "idea",
        "setting", "blog", "news", "post", "how", "your", "our",
    }
    tokens = [
        token.lower()
        for token in slug.split()
        if len(token) > 1 and token.lower() not in skip
    ]
    if len(tokens) >= 2:
        return " ".join(tokens[:6])
    return ""


def _phrase_keyword(text: str) -> str:
    raw = re.split(r"\s*[:|\u2013\u2014]\s*", (text or "").strip())[0]
    raw = re.sub(
        r"^(how to|the complete|ultimate|a complete|complete|best)\s+",
        "",
        raw,
        flags=re.IGNORECASE,
    )
    words = re.findall(r"[A-Za-z0-9']+", raw)
    if len(words) >= 2:
        return " ".join(words[:7]).lower()
    return ""


def _shorten_query(keyword: str) -> str:
    phrase = _phrase_keyword(keyword)
    if phrase and phrase.lower() != keyword.lower():
        return phrase
    words = re.findall(r"[A-Za-z0-9']+", keyword or "")
    if len(words) > 6:
        return " ".join(words[:6]).lower()
    return (keyword or "").strip()


def _detect_keyword(title: str, h1: str, url: str) -> str:
    """Prefer the URL slug (actual query shape) over a long marketing title."""
    slug = _slug_keyword(url)
    if slug:
        return slug[:80]
    for source in (h1, title):
        phrase = _phrase_keyword(source)
        if phrase:
            return phrase[:80]
    return (slug or "blog article")[:80]


def _fetch_html(url: str) -> tuple[str, dict[str, str]]:
    response = requests.get(
        url,
        timeout=12,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
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
    r"popup|modal|drawer|skip-to-content|visually-hidden|"
    r"comment-body|comments-area|comment-list|comment-content|comment-entry|"
    r"pingback|related-posts|elementor-location-header|elementor-location-footer)",
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
    ".elementor-location-single",
    ".elementor-widget-container",
    ".content-area",
    "article .rte",
    "div.rte",
    "[role='main']",
    "article",
    "main",
]


def _strip_chrome(root) -> None:
    if root is None:
        return
    for tag in list(root.find_all(_CHROME_TAGS)):
        if tag is not None:
            tag.decompose()
    for tag in list(root.find_all(True)):
        if tag is None or getattr(tag, "attrs", None) is None:
            continue
        blob = " ".join(tag.get("class") or []) + " " + str(tag.get("id") or "")
        name = (tag.name or "").lower()
        if name in {"header"} and not tag.find_parent("article"):
            tag.decompose()
            continue
        if _CHROME_HINT.search(blob):
            tag.decompose()
            continue
        if name == "article" and re.search(r"\bcomment\b", blob, re.I):
            tag.decompose()


def _measurable_text(node) -> str:
    if node is None:
        return ""
    probe = BeautifulSoup(str(node), "html.parser")
    _strip_chrome(probe)
    return probe.get_text(" ", strip=True)


def _looks_like_comment_node(node) -> bool:
    if node is None or getattr(node, "attrs", None) is None:
        return False
    blob = " ".join(node.get("class") or []) + " " + str(node.get("id") or "")
    return bool(re.search(r"\bcomments?\b", blob, re.I))


def _content_root(soup):
    best = None
    best_words = 0
    seen: set[int] = set()
    nodes: list[Any] = []
    for selector in _CONTENT_SELECTORS:
        try:
            found = soup.select(selector)
        except Exception:
            found = []
        nodes.extend(found)
    widgets = soup.select(".elementor-widget-container")
    if len(widgets) >= 2:
        wrap = BeautifulSoup("<div class='elementor-aggregate'></div>", "html.parser").div
        for widget in widgets:
            wrap.append(BeautifulSoup(str(widget), "html.parser"))
        nodes.append(wrap)
    for node in nodes:
        if node is None:
            continue
        marker = id(node)
        if marker in seen:
            continue
        seen.add(marker)
        if _looks_like_comment_node(node):
            continue
        words = count_words(_measurable_text(node))
        if words > best_words:
            best_words = words
            best = node
    if best is not None and best_words >= 80:
        return best
    return soup.find("main") or soup.body or soup


def _html_to_markdown(root) -> str:
    if root is None:
        return ""
    chunks: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote", "div"]):
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
        elif name == "div":
            if el.find(["p", "h1", "h2", "h3", "h4", "li", "blockquote", "div"]):
                continue
            if len(text.split()) < 8:
                continue
            chunks.append(text)
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


_QUESTION_START = re.compile(
    r"^(how|what|why|is|does|can|when|where|who|which|should|are|do|will)\b",
    re.IGNORECASE,
)


def _jsonld_types(soup) -> list[str]:
    types: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        for item in stack:
            if not isinstance(item, dict):
                continue
            value = item.get("@type")
            if isinstance(value, list):
                types.extend(str(part) for part in value if part)
            elif value:
                types.append(str(value))
    seen: set[str] = set()
    unique: list[str] = []
    for item in types:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _walk_jsonld(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _walk_jsonld(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    if "@graph" in node:
        yield from _walk_jsonld(node.get("@graph"))


def _jsonld_modified_values(soup) -> list[str]:
    values: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for item in _walk_jsonld(data):
            modified = item.get("dateModified")
            if isinstance(modified, str) and modified.strip():
                values.append(modified.strip())
    return values


def _meta_property(soup, property_name: str) -> str:
    node = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(property_name)}$", re.I)})
    if node is None:
        node = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(property_name)}$", re.I)})
    if node is None:
        return ""
    return str(node.get("content") or "").strip()


def _extract_title(soup) -> str:
    og_title = _meta_property(soup, "og:title")
    if og_title:
        return " ".join(og_title.split())[:240]
    if soup.title:
        text = " ".join(soup.title.get_text(" ", strip=True).split())
        if text:
            return text[:240]
    return ""


def _extract_modified_datetime(soup) -> Optional[datetime]:
    candidates = list(_jsonld_modified_values(soup))
    for prop in ("article:modified_time", "og:updated_time"):
        value = _meta_property(soup, prop)
        if value:
            candidates.append(value)
    for raw in candidates:
        parsed = _parse_datetime(raw)
        if parsed:
            return parsed
    return None


def _robots_and_canonical(soup, url: str) -> dict[str, Any]:
    robots = ""
    node = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if node:
        robots = str(node.get("content") or "").strip()
    canonical = ""
    link = soup.find("link", attrs={"rel": re.compile(r"canonical", re.I)})
    if link:
        canonical = str(link.get("href") or "").strip()
    noindex = bool(re.search(r"noindex", robots, re.I))
    path = urlparse(url).path or "/"
    return {
        "robots": robots or "index, follow (not declared)",
        "canonical": canonical,
        "indexed": not noindex,
        "path": path,
    }


def _faq_audit(root) -> dict[str, Any]:
    questions: list[dict[str, Any]] = []
    if root is None:
        return {"questions": [], "asked": 0, "answered": 0, "unanswered": 0}
    for node in root.find_all(["h2", "h3"]):
        text = " ".join(node.get_text(" ", strip=True).split())
        if len(text) < 8:
            continue
        if not (text.endswith("?") or _QUESTION_START.match(text)):
            continue
        bits: list[str] = []
        for sib in node.next_siblings:
            name = getattr(sib, "name", None)
            if name in {"h1", "h2", "h3", "h4"}:
                break
            if getattr(sib, "get_text", None):
                bits.append(" ".join(sib.get_text(" ", strip=True).split()))
        answer = " ".join(bit for bit in bits if bit).strip()
        answered = len(answer) >= 40
        questions.append({"question": text, "answered": answered})
    answered_n = sum(1 for item in questions if item["answered"])
    return {
        "questions": questions[:16],
        "asked": len(questions),
        "answered": answered_n,
        "unanswered": max(0, len(questions) - answered_n),
    }


def _first_number_word_index(text: str) -> Optional[int]:
    words = (text or "").split()
    for index, word in enumerate(words[:400], start=1):
        if re.search(r"(\d|₹|rs\.?)", word, re.I):
            return index
    return None


_FILENAME_NOISE = {
    "img", "image", "images", "photo", "pic", "picture", "untitled", "design", "copy", "final",
    "edited", "scaled", "large", "small", "medium", "thumb", "thumbnail", "banner", "hero",
    "dsc", "pxl", "screenshot", "min", "web", "jpg", "jpeg", "png", "webp", "gif", "file",
    "upload", "uploads", "new", "resized", "cropped", "crop", "version", "progressive",
}


def _filename_words(src: str) -> list[str]:
    name = unquote(urlparse(src).path.rsplit("/", 1)[-1]).lower()
    name = re.sub(r"\.[a-z0-9]{2,5}$", "", name)
    name = re.sub(r"[-_]\d+x\d+$", "", name)
    words = []
    for word in re.split(r"[^a-z0-9]+", name):
        if len(word) < 3 or not word.isalpha() or word in _FILENAME_NOISE:
            continue
        if len(word) > 14:
            continue
        words.append(word)
    return words[:8]


def _int_attr(value: Any) -> Optional[int]:
    match = re.match(r"\s*(\d+)", str(value or ""))
    return int(match.group(1)) if match else None


def _image_inventory(root, url: str, limit: int = 40) -> list[dict[str, Any]]:
    """Article images in document order with the section heading they sit under."""
    items: list[dict[str, Any]] = []
    if root is None:
        return items
    section = ""
    for node in root.find_all(["h1", "h2", "h3", "img"]):
        if node.name != "img":
            section = " ".join(node.get_text(" ", strip=True).split())[:160]
            continue
        src = str(node.get("src") or node.get("data-src") or node.get("data-lazy-src") or "")
        if not src or src.startswith("data:"):
            continue
        width, height = _int_attr(node.get("width")), _int_attr(node.get("height"))
        if width and height and width <= 48 and height <= 48:
            continue
        figure = node.find_parent("figure")
        caption_node = figure.find("figcaption") if figure else None
        caption = " ".join(caption_node.get_text(" ", strip=True).split())[:200] if caption_node else ""
        items.append({
            "src": urljoin(url, src),
            "alt": " ".join(str(node.get("alt") or "").split()),
            "has_alt_attr": node.has_attr("alt"),
            "decorative": str(node.get("role") or "").lower() == "presentation"
            or str(node.get("aria-hidden") or "").lower() == "true",
            "caption": caption,
            "section": section,
            "filename_words": _filename_words(src),
        })
        if len(items) >= limit:
            break
    return items


def _onpage_signals(soup, url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Live HTML facts used by the gap report. Extracted before scripts are stripped."""
    meta = _robots_and_canonical(soup, url)
    schema = _jsonld_types(soup)
    author = ""
    for selector in (
        soup.find("meta", attrs={"name": re.compile(r"author", re.I)}),
        soup.find(attrs={"itemprop": "author"}),
        soup.find(class_=re.compile(r"\bauthor\b", re.I)),
    ):
        if selector is None:
            continue
        if selector.name == "meta":
            author = str(selector.get("content") or "").strip()
        else:
            author = " ".join(selector.get_text(" ", strip=True).split())
        if author:
            break
    images = []
    for img in soup.find_all("img"):
        alt = " ".join(str(img.get("alt") or "").split())
        src = str(img.get("src") or img.get("data-src") or "")
        if not src or src.startswith("data:"):
            continue
        images.append({"alt": alt, "generic": (not alt) or alt.lower() in {"hero", "image", "photo", "banner"}})
    root = _content_root(soup)
    cleaned = BeautifulSoup(str(root), "html.parser")
    _strip_chrome(cleaned)
    faq = _faq_audit(cleaned)
    article_images = _image_inventory(cleaned, url)
    h3 = _heading_texts(cleaned, "h3")
    h4 = _heading_texts(cleaned, "h4")
    tables = len(cleaned.find_all("table")) if cleaned else 0
    text = cleaned.get_text(" ", strip=True) if cleaned else ""
    first_number_at = _first_number_word_index(text)
    h2s = _heading_texts(cleaned, "h2")
    consecutive_q = 0
    best_run = 0
    for heading in h2s:
        if heading.endswith("?") or _QUESTION_START.match(heading):
            consecutive_q += 1
            best_run = max(best_run, consecutive_q)
        else:
            consecutive_q = 0
    h4_without_h3 = bool(h4) and not h3
    year_in_title = bool(re.search(r"\b20\d{2}\b", (soup.title.string if soup.title else "") or ""))
    return {
        "robots": meta["robots"],
        "canonical": meta["canonical"],
        "indexed": meta["indexed"],
        "path": meta["path"],
        "schema_types": schema,
        "author": author[:120],
        "image_count": len(images),
        "generic_alts": sum(1 for item in images if item["generic"]),
        "images": article_images,
        "table_count": tables,
        "h3_count": len(h3),
        "h4_count": len(h4),
        "h3_headings": h3[:20],
        "faq": faq,
        "first_number_at": first_number_at,
        "consecutive_question_h2s": best_run,
        "h4_without_h3": h4_without_h3,
        "year_in_title": year_in_title,
        "has_lastmod": bool(headers.get("last-modified") or soup.find("time") or soup.find("meta", attrs={"property": "article:modified_time"})),
    }


def _page_flags(page: dict[str, Any]) -> dict[str, bool]:
    blob = f"{page.get('title', '')} {page.get('text', '')} {' '.join(page.get('h2_headings') or [])}".lower()
    faq = page.get("faq") or {}
    first_at = page.get("first_number_at")
    return {
        "headline_number": bool(first_at and first_at <= 80),
        "faq_answered": int(faq.get("answered") or 0) > 0,
        "cost_table": int(page.get("table_count") or 0) >= 1,
        "attraction_fees": bool(re.search(r"\b(entry fee|ticket|sightseeing|garden|lake)\b", blob)),
        "day3": bool(re.search(r"\b(3[\s-]?day|three day|3 nights)\b", blob)),
        "origin_city": bool(re.search(
            r"\b(from (bangalore|bengaluru|chennai|mumbai|hyderabad|delhi|coimbatore|kochi|pune))\b",
            blob,
        )),
        "named_hotel": bool(re.search(r"\b(marriott|hyatt|taj|itc|hilton|oyo|treebo|resort)\b", blob)),
        "seasonal": bool(re.search(r"\b(december|summer|off[\s-]?season|peak season|monsoon)\b", blob)),
        "author": bool(page.get("author") or page.get("has_lastmod")),
        "schema_faq": any("faq" in str(item).lower() for item in (page.get("schema_types") or [])),
    }


def _page_stats(url: str, html: str, headers: dict[str, str]) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    try:
        signals = _onpage_signals(soup, url, headers)
    except Exception as error:
        logger.warning("on-page signals failed for %s: %s", url, error)
        signals = {}
    try:
        title = _extract_title(soup)
    except Exception as error:
        logger.warning("title extract failed for %s: %s", url, error)
        title = ""
    try:
        modified_dt = _extract_modified_datetime(soup)
    except Exception as error:
        logger.warning("date extract failed for %s: %s", url, error)
        modified_dt = None
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    try:
        markdown, cleaned, md_words = _extract_readable_article(soup)
    except Exception as error:
        logger.warning("content extract failed for %s: %s", url, error)
        markdown, cleaned, md_words = "", None, 0
    h1_headings = _heading_texts(cleaned, "h1") if cleaned else []
    h2_headings = _heading_texts(cleaned, "h2") if cleaned else []
    h1 = h1_headings[0] if h1_headings else ""
    if not title:
        title = h1

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
    words = count_words(text) or md_words
    article_html = markdown[:80000]
    extract_ok = bool(title) and words >= 100
    meta_description = _meta_property(soup, "og:description") or _meta_property(soup, "description")
    hrefs = re.findall(r"https?://[^\s)\"']+", markdown)
    own_host = _host(url)
    internal_links = sum(1 for href in hrefs if _host(href) == own_host)
    external_links = max(0, len(hrefs) - internal_links)

    return {
        "url": url,
        "title": title[:240] if title else "",
        "h1": h1[:240],
        "h1_count": len(h1_headings),
        "h2_count": len(h2_headings),
        "h1_headings": h1_headings,
        "h2_headings": h2_headings,
        "word_count": words or None,
        "text": text[:20000],
        "article_html": article_html,
        "source_markdown": markdown[:45000],
        "extract_ok": extract_ok,
        "extract_error": None if extract_ok else "unavailable",
        "updated": _relative_updated(modified_dt) if modified_dt else "Unknown",
        "updated_at": modified_dt.isoformat() if modified_dt else None,
        "content_type": _content_type(title or h1, text),
        "authority": _authority(url),
        "favicon": _favicon(url),
        "domain": _host(url) or url,
        "meta_description": (meta_description or "")[:300],
        "internal_links": internal_links,
        "external_links": external_links,
        **signals,
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
        "aio": min(94, max(30, geo - 4)),
        "sxo": min(94, max(30, aeo - 2)),
    }


def _unavailable_score(reason: str) -> dict[str, Any]:
    return {
        "score": None,
        "status": "unavailable",
        "reason": reason,
        "factors": [],
        "notes": [],
        "tips": [],
        "confidence": "low",
    }


def _public_score_block(scores: dict[str, Any]) -> dict[str, Any]:
    return {
        "seo": scores.get("seo"),
        "geo": scores.get("geo"),
        "aeo": scores.get("aeo"),
        "aio": scores.get("aio"),
        "sxo": scores.get("sxo"),
        "overall": scores.get("overall"),
        "confidence": scores.get("confidence"),
        "status": scores.get("status"),
        "reason": scores.get("reason"),
    }


def _score_page(keyword: str, page: dict[str, Any]) -> dict[str, Any]:
    reason = "Article text could not be extracted."
    empty_reports = {
        "seo": _unavailable_score(reason),
        "geo": _unavailable_score(reason),
        "aeo": _unavailable_score(reason),
        "aio": _unavailable_score(reason),
        "sxo": _unavailable_score(reason),
    }
    empty = {
        "seo": None, "geo": None, "aeo": None, "aio": None, "sxo": None,
        "overall": None, "confidence": "unavailable", "status": "unavailable",
        "reason": reason, "reports": empty_reports, "scores": empty_reports,
    }
    article = page_full_text(page)
    if not page.get("extract_ok") or len(article.split()) < 40:
        empty["reason"] = "Article text could not be extracted."
        return empty
    title = page.get("title") or keyword or ""
    if not title:
        return empty
    brief_title = title if len(title) >= 5 else f"{keyword} guide"
    confidence = "high" if page.get("updated_at") else "medium"
    signals = {
        "schema_types": page.get("schema_types") or [],
        "author": page.get("author") or "",
        "faq": page.get("faq") or {},
    }
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
            meta_description=(page.get("meta_description") or article)[:160],
        )
        report = score_article(article, brief, seo_model, signals)
        packed = {}
        for key in ("seo", "geo", "aeo", "aio", "sxo"):
            block = report.get(key) or {}
            if isinstance(block.get("score"), int):
                packed[key] = block
            else:
                packed[key] = _unavailable_score(f"{key.upper()} could not be calculated.")
        return {
            "seo": packed["seo"].get("score"),
            "geo": packed["geo"].get("score"),
            "aeo": packed["aeo"].get("score"),
            "aio": packed["aio"].get("score"),
            "sxo": packed["sxo"].get("score"),
            "overall": int(report.get("overall") or 0),
            "confidence": confidence,
            "status": "ok",
            "reports": packed,
            "scores": packed,
        }
    except Exception as error:
        logger.warning("score_article failed for %s: %s", page.get("url"), error)
        scores = _heuristic_scores(
            keyword,
            title,
            article,
            int(page.get("word_count") or 0),
            int(page.get("h1_count") or 0),
            int(page.get("h2_count") or 0),
        )
        scores["overall"] = round(sum(scores[k] for k in ("seo", "geo", "aeo", "aio", "sxo")) / 5)
        scores["confidence"] = "low"
        scores["status"] = "ok"
        scores["reason"] = f"Checklist used a fallback scorer: {error}"
        scores["reports"] = {
            key: {"score": scores[key], "status": "ok", "reason": "Heuristic fallback", "factors": []}
            for key in ("seo", "geo", "aeo", "aio", "sxo")
        }
        scores["scores"] = scores["reports"]
        return scores


def _keyword_tokens(keyword: str) -> list[str]:
    skip = {
        "the", "and", "for", "with", "from", "best", "your", "our", "how",
        "complete", "guide", "blog", "news", "post", "create", "creating",
        "collections", "collection", "ultimate", "ideas", "idea", "setting",
    }
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", (keyword or "").lower())
        if 2 < len(token) < 12 and token not in skip
    ]
    return tokens[:5]


def _fold_match_blob(*parts: str) -> str:
    return " ".join(str(part or "") for part in parts).lower().replace("'", "").replace("’", "")


def _token_matches(token: str, blob: str) -> bool:
    variants = {token}
    if token.endswith("ies") and len(token) > 4:
        variants.add(token[:-3] + "y")
    if token.endswith("es") and len(token) > 4:
        variants.add(token[:-2])
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        variants.add(token[:-1])
    return any(variant in blob for variant in variants)


def _core_topic_terms(tokens: list[str]) -> set[str]:
    money = {"cost", "budget", "price", "prices", "pricing", "fee", "fees", "fare", "cheap"}
    product = {"tablecloth", "tablecloths", "linen", "linens", "bedding"}
    extra: set[str] = set()
    if any(token in money for token in tokens):
        extra |= money
    if any(token in product for token in tokens):
        extra |= product
    return extra


def _serp_relevance(keyword: str, title: str, url: str, snippet: str) -> int:
    tokens = _keyword_tokens(keyword)
    title_l = _fold_match_blob(title)
    url_l = _fold_match_blob(url)
    snip_l = _fold_match_blob(snippet)
    blob = f"{title_l} {url_l} {snip_l}"
    if not tokens:
        return 1
    host = urlparse(url).netloc.lower()
    if any(host == item or host.endswith("." + item) for item in (
        "wikipedia.org",
        "britannica.com",
        "wiktionary.org",
        "merriam-webster.com",
        "dictionary.cambridge.org",
    )):
        return -5
    hits = 0
    for token in tokens:
        if _token_matches(token, title_l):
            hits += 2
        elif _token_matches(token, url_l):
            hits += 2
        elif _token_matches(token, snip_l):
            hits += 1
    core = _core_topic_terms(tokens)
    if core and not any(_token_matches(term, blob) or term in blob for term in core):
        return -2
    path = urlparse(url).path.rstrip("/")
    if not path and hits < 3:
        hits -= 1
    return hits


TARGET_COMPETITORS = 5
SERP_CANDIDATE_LIMIT = 10


def _unique_token_hits(keyword: str, title: str, url: str, snippet: str) -> list[str]:
    tokens = _keyword_tokens(keyword)
    blob = _fold_match_blob(title, url, snippet)
    return [token for token in tokens if _token_matches(token, blob)]


def _serp_item_score(keyword: str, item: Any) -> int:
    return _serp_relevance(
        keyword,
        getattr(item, "title", "") or "",
        getattr(item, "url", "") or "",
        getattr(item, "snippet", "") or "",
    )


def _topic_threshold(keyword: str) -> int:
    return max(2, min(3, len(_keyword_tokens(keyword)) or 1))


def _leading_token_only_match(keyword: str, title: str, url: str, snippet: str) -> bool:
    tokens = _keyword_tokens(keyword)
    if len(tokens) < 3:
        return False
    hits = _unique_token_hits(keyword, title, url, snippet)
    return hits == [tokens[0]]


def _order_serp_results(keyword: str, results: list[Any]) -> list[Any]:
    """Prefer on-topic pages, then fill with the next-best organic results."""
    scored = [(_serp_item_score(keyword, item), item) for item in results]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    needed = _topic_threshold(keyword)
    strong: list[Any] = []
    rest: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for score, item in scored:
        url = getattr(item, "url", "") or ""
        title = getattr(item, "title", "") or ""
        snippet = getattr(item, "snippet", "") or ""
        key = _url_key(url)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        if score <= -3:
            continue
        if _leading_token_only_match(keyword, title, url, snippet):
            continue
        hits = _unique_token_hits(keyword, title, url, snippet)
        if score >= needed or len(hits) >= needed:
            strong.append(item)
        elif hits:
            rest.append(item)
    return strong + rest


def _competitor_serp_queries(keyword: str) -> list[str]:
    phrase = " ".join((keyword or "").split())
    tokens = re.findall(r"[A-Za-z0-9']+", phrase)
    skip = {"the", "and", "for", "with", "from", "how", "what", "a", "of", "to"}
    distinctive = [token for token in tokens if token.lower() not in skip]
    queries: list[str] = []
    if len(distinctive) >= 3:
        queries.append(" ".join(distinctive[-3:]))
        queries.append(" ".join(distinctive[:3]))
        queries.append(" ".join(distinctive[1:4]))
    elif len(tokens) >= 3:
        queries.append(" ".join(tokens[-3:]))
        queries.append(" ".join(tokens[2:]))
        queries.append(" ".join(tokens[1:4]))
    if phrase:
        queries.append(phrase)
        queries.append(f"{phrase} guide")
        queries.append(f"{phrase} blog")
    shorter = _shorten_query(phrase)
    if shorter:
        queries.append(shorter)
    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        key = query.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(query.strip())
    return out


def _filter_relevant_results(keyword: str, results: list[Any]) -> list[Any]:
    needed = _topic_threshold(keyword)
    ordered = _order_serp_results(keyword, results)
    return [
        item for item in ordered
        if _serp_item_score(keyword, item) >= needed
    ][:8]


def _page_topic_score(keyword: str, page: dict[str, Any], item: Any) -> int:
    text = (page.get("text") or "")[:2500]
    return _serp_relevance(
        keyword,
        page.get("title") or getattr(item, "title", "") or "",
        getattr(item, "url", "") or page.get("url") or "",
        f"{getattr(item, 'snippet', '') or ''} {text}",
    )


def _dedupe_serp(results: list[Any]) -> list[Any]:
    seen: set[tuple[str, str]] = set()
    out: list[Any] = []
    for item in results:
        url = getattr(item, "url", "") or ""
        parsed = urlparse(url)
        host = parsed.netloc.lower().removeprefix("www.")
        key = (host, parsed.path.rstrip("/").lower())
        if not url or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _pick_serp_results(keyword: str, initial: list[Any]) -> list[Any]:
    merged = _dedupe_serp(list(initial or []))
    picked = _order_serp_results(keyword, merged)
    needed = _topic_threshold(keyword)

    def strong_count(items: list[Any]) -> int:
        return sum(1 for item in items if _serp_item_score(keyword, item) >= needed)

    if strong_count(picked) < TARGET_COMPETITORS:
        extras = _competitor_serp_queries(keyword)
        already = {keyword.strip().lower()}
        for query in extras:
            if query.lower() in already:
                continue
            already.add(query.lower())
            try:
                more = search_serp(query, max_results=10)
            except Exception as error:
                logger.warning("Topic SERP retry failed for '%s': %s", query, error)
                more = []
            if not more:
                continue
            merged = _dedupe_serp(merged + more)
            picked = _order_serp_results(keyword, merged)
            if strong_count(picked) >= TARGET_COMPETITORS:
                break
    return picked[:SERP_CANDIDATE_LIMIT]


def _select_competitor_rows(
    pending: list[dict[str, Any]],
    *,
    target: int = TARGET_COMPETITORS,
    needed: int = 2,
) -> list[dict[str, Any]]:
    """Keep on-topic pasted URLs, then fill to `target` with the strongest SERP pages."""

    def off_topic_manual(item: dict[str, Any]) -> bool:
        if not item.get("is_manual"):
            return False
        if "topic_mismatch" in item:
            return bool(item.get("topic_mismatch"))
        return int(item.get("topic") or 0) < needed

    manuals = [item["row"] for item in pending if item.get("is_manual") and not off_topic_manual(item)]
    rest = [item for item in pending if not item.get("is_manual")]
    rest.sort(
        key=lambda item: (int(item.get("topic") or 0), 1 if item.get("extract_ok") else 0),
        reverse=True,
    )
    strong = [item["row"] for item in rest if int(item.get("topic") or 0) >= needed]
    weak = [item["row"] for item in rest if int(item.get("topic") or 0) < needed]
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in manuals + strong + weak:
        key = _url_key(str(row.get("url") or ""))
        if not key[0] or key in seen:
            continue
        seen.add(key)
        selected.append(row)
        if len(selected) >= target:
            break
    return selected


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
    return signals


def _scrape_url(url: str) -> Optional[dict[str, Any]]:
    try:
        html, headers = _fetch_html(url)
        return _page_stats(url, html, headers)
    except requests.HTTPError as error:
        status = getattr(error.response, "status_code", "?")
        logger.warning("Could not scrape %s: HTTP %s", url, status)
        return None
    except Exception as error:
        logger.warning("Could not scrape %s: %s", url, error)
        return None


def _fallback_page(url: str, title: str, snippet: str) -> dict[str, Any]:
    cleaned_title = " ".join((title or "").split())
    if re.match(r"^https?://", cleaned_title, flags=re.I):
        cleaned_title = ""
    snippet_text = " ".join((snippet or "").split())
    snippet_words = count_words(snippet_text)
    return {
        "url": url,
        "title": cleaned_title,
        "h1": cleaned_title,
        "h1_count": 1 if cleaned_title else 0,
        "h2_count": 0,
        "h1_headings": [cleaned_title] if cleaned_title else [],
        "h2_headings": [],
        "word_count": snippet_words or None,
        "text": snippet_text,
        "article_html": "",
        "source_markdown": "",
        "snippet": snippet_text,
        "extract_ok": False,
        "extract_error": "unavailable",
        "updated": "Unknown",
        "updated_at": None,
        "content_type": _content_type(cleaned_title, snippet_text) if cleaned_title or snippet_text else "Unknown",
        "authority": _authority(url),
        "favicon": _favicon(url),
        "domain": _host(url) or url,
    }


_GENERIC_SECTIONS = {
    "final thoughts", "conclusion", "introduction", "in conclusion",
    "frequently asked questions", "faq", "faqs", "table of contents",
    "related articles", "related posts", "key takeaways", "summary",
    "leave a comment", "share this", "about the author",
}


def _clean_section_label(text: str) -> Optional[str]:
    """Keep short section names; drop scraped list items, dates, and snippets."""
    heading = " ".join((text or "").split())
    if len(heading) < 8 or len(heading) > 70:
        return None
    if re.search(r"<[^>]+>", heading):
        return None
    if heading[-1] in ".!?":
        return None
    if re.match(r"^\d+[\.):]\s", heading):
        return None
    if "·" in heading or "|" in heading:
        return None
    if " - " in heading and len(heading.split()) >= 8:
        return None
    if re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b.*\d{4}",
        heading,
        flags=re.IGNORECASE,
    ):
        return None
    if heading.lower().startswith(("discover ", "shop ", "buy ", "subscribe")):
        return None
    if heading.lower().strip(" :") in _GENERIC_SECTIONS or is_closing_section(heading):
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


def _competitor_does_well(page: dict[str, Any], flags: dict[str, bool]) -> str:
    notes = []
    if flags.get("faq_answered"):
        notes.append("FAQ answers visible in HTML")
    if flags.get("headline_number"):
        notes.append("early extractable cost number")
    if flags.get("cost_table"):
        notes.append(f"{page.get('table_count') or 1} cost table(s)")
    if flags.get("day3"):
        notes.append("3-day cost coverage")
    if flags.get("origin_city"):
        notes.append("origin-city split")
    if flags.get("seasonal"):
        notes.append("seasonal price notes")
    tables = int(page.get("table_count") or 0)
    if tables and not any("table" in note.lower() for note in notes):
        notes.append(f"{tables} comparison table(s)")
    return "; ".join(notes[:4])


def analyze_competitors(
    blog_url: Optional[str] = None,
    keyword: Optional[str] = None,
    competitor_urls: Optional[list[str]] = None,
    on_progress: ProgressFn = None,
    country: Optional[str] = None,
    language: Optional[str] = None,
    client_analysis_id: Optional[str] = None,
    current_origin: Optional[str] = None,
    months: Optional[int] = None,
) -> dict[str, Any]:
    """
    Compare your page with the competitor URLs you supply, for the keyword you enter.
    Competitors are never discovered from live search.
    """
    analysis_id = str(uuid.uuid4())
    keyword = (keyword or "").strip() or None
    if not keyword:
        raise ValueError("Enter a target keyword.")
    url_check = validate_blog_url(blog_url, current_origin or "")
    if url_check["status"] == "invalid":
        raise ValueError(url_check["error"] or "Please enter a valid public article URL.")
    blog_url = url_check["url"] if url_check["ok"] else None
    keyword_source = "user"
    detected_keyword = ""
    detected_evidence: list[str] = []
    blog_url_status = url_check["status"]
    mode = analysis_mode(blog_url, keyword)
    manual_urls = _normalize_competitor_urls(list(competitor_urls or []))
    country = re.sub(r"[^a-z]", "", (country or "us").lower())[:8] or "us"
    language = re.sub(r"[^a-z-]", "", (language or "en").lower())[:8] or "en"
    window = diagnosis_window(months)
    target_n = len(manual_urls)
    logger.info(
        "analyze_competitors analysis_id=%s blog_url=%r keyword=%r competitor_urls=%s client_analysis_id=%s",
        analysis_id,
        blog_url,
        keyword,
        manual_urls,
        client_analysis_id,
    )
    if not blog_url and not manual_urls:
        raise ValueError("Enter a blog URL or at least one competitor URL.")

    your_page: Optional[dict[str, Any]] = None
    scraped_by_url: dict[str, dict[str, Any]] = {}
    if blog_url:
        _emit(on_progress, "fetch_page", "Fetching your page")
        your_page = _scrape_url(blog_url)
        if your_page is None:
            raise ValueError("The page could not be fetched.")
        your_page["full_text"] = page_full_text(your_page)
        blog_url_status = "extracted" if your_page.get("extract_ok") else "extract_failed"
        if not your_page.get("url"):
            your_page["url"] = blog_url

    gsc_diagnosis = unavailable_diagnosis("No blog URL submitted.", days=window["days"])
    if blog_url:
        _emit(on_progress, "fetch_page", f"Reading Search Console ({window['label'].lower()})")
        try:
            gsc_diagnosis = diagnose_page_visibility(
                blog_url,
                days=window["days"],
                page=your_page,
                target_keyword=keyword,
            )
        except Exception as error:
            logger.warning("GSC diagnosis skipped: %s", error)
            gsc_diagnosis = unavailable_diagnosis(
                str(error) or "Search Console lookup failed.",
                blog_url,
                days=window["days"],
            )
    gsc_diagnosis["period"] = {
        **(gsc_diagnosis.get("range") or {}),
        **(gsc_diagnosis.get("period") or {}),
        **window,
    }

    serp_query = keyword
    serp_query_source = "user"
    serp = SERPAnalysis(keyword=keyword)
    serp_warning = "" if manual_urls else "No competitor URLs added, so this is an audit of your page only."

    _emit(on_progress, "competitors", "Analyzing competitors")
    ranked: list[Any] = []
    ranked_keys: set[tuple[str, str]] = set()
    manual_keys: set[tuple[str, str]] = set()
    own_key = _url_key(blog_url) if blog_url else ("", "")
    for url in manual_urls:
        key = _url_key(url)
        if not key[0] or key in ranked_keys or key == own_key:
            continue
        ranked.append(SERPResult(title="", url=url, snippet=""))
        ranked_keys.add(key)
        manual_keys.add(key)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_scrape_url, item.url): item.url
            for item in ranked
            if item.url not in scraped_by_url
        }
        for future in as_completed(futures):
            original = futures[future]
            page = future.result()
            if page:
                scraped_by_url[original] = page
                scraped_by_url[page["url"]] = page

    _emit(on_progress, "scoring", "Scoring")
    pending: list[dict[str, Any]] = []
    needed = _topic_threshold(keyword)
    user_intent = article_intent(keyword, your_page)
    for item in ranked:
        page = scraped_by_url.get(item.url)
        if page is None:
            logger.warning("Scrape unavailable for %s; not inventing title, words, date, or scores", item.url)
            page = _fallback_page(item.url, item.title, item.snippet)
        page = {**page, "full_text": page_full_text(page)}
        is_manual = _url_key(item.url) in manual_keys
        topic = _page_topic_score(keyword, page, item)
        topic_mismatch = bool(is_manual and topic < needed)
        scores = (
            {
                "seo": None, "geo": None, "aeo": None, "aio": None, "sxo": None,
                "overall": None, "confidence": "unavailable", "status": "unavailable",
                "reason": "Off-topic competitor URL excluded.",
                "reports": {}, "scores": {},
            }
            if topic_mismatch else _score_page(keyword, page)
        )
        page_title = page.get("title") or item.title or ""
        if re.match(r"^https?://", str(page_title), flags=re.I):
            page_title = ""
        page_view = {
            **page,
            "snippet": item.snippet,
            "title": page_title,
        }
        does_well = _competitor_does_well(page_view, _page_flags(page_view)) if page.get("extract_ok") else ""
        well_signals = [
            {"kind": "positive", "label": part.strip()}
            for part in does_well.split(";")
            if part.strip() and not re.match(r"^https?://", part.strip(), flags=re.I)
        ][:4]
        if page.get("extract_ok") and not well_signals:
            well_signals = _opportunity_signals(page_view)
        page_intent = classify_page_intent({**page_view, "url": item.url})
        intent_mismatch = user_intent == "informational" and page_intent in {"transactional", "navigational"}
        if topic_mismatch:
            does_well = ""
            well_signals = [{"kind": "warn", "label": "Topic mismatch"}]
        elif intent_mismatch:
            does_well = ""
            well_signals = [{"kind": "warn", "label": "Intent mismatch"}]
        pending.append({
            "is_manual": is_manual,
            "topic": topic,
            "topic_mismatch": topic_mismatch,
            "extract_ok": bool(page.get("extract_ok")),
            "row": {
                "url": item.url,
                "domain": page["domain"],
                "favicon": page["favicon"],
                "title": page_title,
                "page_title": page_title,
                "page_title_signal": True,
                "search_intent": page_intent,
                "intent_mismatch": intent_mismatch,
                "topic_mismatch": topic_mismatch,
                "content_type": page["content_type"],
                "authority": page["authority"],
                "word_count": page.get("word_count"),
                "updated": page.get("updated") or "Unknown",
                "extract_ok": bool(page.get("extract_ok")),
                "h1_count": page["h1_count"],
                "h2_count": page["h2_count"],
                "h1_headings": page.get("h1_headings") or [],
                "h2_headings": page.get("h2_headings") or [],
                "scores": scores,
                "signals": well_signals,
                "does_well": does_well,
                "snippet": item.snippet,
                "text": page.get("full_text") or page.get("text") or item.snippet,
                "faq": page.get("faq") or {},
                "table_count": page.get("table_count") or 0,
                "schema_types": page.get("schema_types") or [],
                "author": page.get("author") or "",
                "has_lastmod": page.get("has_lastmod") or False,
                "first_number_at": page.get("first_number_at"),
                "image_count": page.get("image_count") or 0,
                "generic_alts": page.get("generic_alts") or 0,
                "meta_description": page.get("meta_description") or "",
                "internal_links": page.get("internal_links") or 0,
                "external_links": page.get("external_links") or 0,
                "robots": page.get("robots") or "",
                "canonical": page.get("canonical") or "",
                "updated_at": page.get("updated_at"),
            },
        })
    competitors = _select_competitor_rows(pending, target=target_n, needed=needed)
    for index, row in enumerate(competitors, start=1):
        row["rank"] = index

    excluded_manuals = [
        item["row"].get("url")
        for item in pending
        if item.get("is_manual") and item.get("topic_mismatch") and item["row"].get("url")
    ]
    used_manual_urls = [
        url for url in manual_urls
        if url not in set(excluded_manuals)
    ]
    if excluded_manuals:
        excluded_note = (
            "One or more competitor URLs you provided don't appear to match the "
            f"target keyword '{keyword}' and were excluded: "
            + ", ".join(excluded_manuals)
        )
        serp_warning = f"{serp_warning} {excluded_note}".strip() if serp_warning else excluded_note

    if ranked and not competitors and not serp_warning:
        serp_warning = "None of the competitor URLs you added could be analyzed."

    if your_page:
        blob = page_full_text(your_page)
        your_page = {
            **your_page,
            "full_text": blob,
            "text": blob or your_page.get("text") or "",
            "url": your_page.get("url") or blog_url,
        }
        missing_blog_reason = None
        if not your_page.get("extract_ok") or len(page_full_text(your_page).split()) < 40:
            missing_blog_reason = "Article text could not be extracted."
        your_scores = _score_page(keyword, your_page)
    elif mode == "keyword_only":
        missing_blog_reason = "No blog URL submitted."
        your_scores = {
            "seo": None, "geo": None, "aeo": None, "aio": None, "sxo": None,
            "overall": None, "confidence": "unavailable", "status": "unavailable",
            "reason": missing_blog_reason, "reports": {}, "scores": {},
        }
    else:
        missing_blog_reason = "The page could not be fetched."
        your_scores = {
            "seo": None, "geo": None, "aeo": None, "aio": None, "sxo": None,
            "overall": None, "confidence": "unavailable", "status": "unavailable",
            "reason": missing_blog_reason, "reports": {}, "scores": {},
        }

    source_article = ""
    source_title = ""
    source_extract_error = False
    full_text = page_full_text(your_page) if your_page else ""
    if your_page:
        extract_ok = bool(your_page.get("extract_ok")) and count_words(full_text) >= 40
        if extract_ok:
            source_article = full_text[:45000]
        else:
            source_extract_error = True
            source_article = ""
            blog_url_status = "extract_failed"
        source_title = your_page.get("h1") or your_page.get("title") or ""

    _emit(on_progress, "report", "Building report")
    keyword_report = compare_keywords(
        keyword,
        your_page,
        competitors,
        serp_phrases=list(serp.nlp_keywords or []),
    )
    keyword_report["status"] = "ok" if keyword_report.get("table") else "unavailable"
    if not keyword_report.get("table"):
        keyword_report["reason"] = missing_blog_reason or "No overlapping phrases were extracted from the available headings."
    keyword_report["focus"] = keyword_focus(
        keyword,
        keyword_report.get("table") or [],
        gsc_diagnosis,
        competitor_total=sum(1 for row in competitors if not row.get("intent_mismatch")),
        country=country,
    )
    gap_report = content_gaps(your_page, competitors, keyword)
    gap_report["status"] = "ok"
    if not gap_report.get("recommended_outline"):
        gap_report["recommended_outline"] = [
            "Introduction",
            f"What is {keyword}?" if keyword else "What this guide covers",
            "How to get started",
            "Examples and comparisons",
            "FAQ",
        ]
    citations = citation_opportunities(keyword, your_page, competitors)
    citations["status"] = "ok"
    readability = analyze_readability(full_text, language)
    human = humanization_report(full_text)
    original = originality_report({**(your_page or {}), "text": full_text}, competitors)
    image_report = image_alt_report(your_page, competitors, keyword)

    avg_scores = average_competitor_scores(competitors)
    diffs = {}
    for key in ("seo", "geo", "aeo", "aio", "sxo", "overall"):
        yours_val = your_scores.get(key)
        avg = avg_scores.get(key)
        if isinstance(yours_val, (int, float)) and isinstance(avg, (int, float)):
            diffs[key] = round(float(yours_val) - float(avg), 1)
        else:
            diffs[key] = None
    traffic = traffic_reasons(your_page, competitors, your_scores, avg_scores)
    plan = merge_gsc_actions(
        action_plan(your_page, your_scores, keyword_report, gap_report, readability, image_report),
        gsc_diagnosis,
    )
    targeting = gsc_diagnosis.get("keyword_targeting") or {}
    keyword_mismatch = None
    if targeting.get("mismatch") and targeting.get("primary_ranking_query"):
        keyword_mismatch = {
            "target_keyword": keyword,
            "search_console_query": targeting["primary_ranking_query"],
        }
        for item in plan:
            if item.get("category") in {"Keyword", "Content"}:
                item["depends_on_keyword"] = True
        keyword_report["depends_on_keyword"] = True
        gap_report["depends_on_keyword"] = True
    if not plan:
        plan_payload = {"items": [], "status": "unavailable", "reason": missing_blog_reason or "No prioritized actions were generated."}
    else:
        plan_payload = {"items": plan, "status": "ok", "reason": None}

    analyzed_at = datetime.now(timezone.utc).isoformat()
    slim_competitors = []
    for row in competitors:
        slim_competitors.append({
            "rank": row.get("rank"),
            "url": row.get("url"),
            "domain": row.get("domain"),
            "favicon": row.get("favicon"),
            "title": row.get("title") or UNAVAILABLE,
            "page_title": row.get("page_title") or row.get("title") or UNAVAILABLE,
            "page_title_signal": True,
            "search_intent": row.get("search_intent") or "informational",
            "intent_mismatch": bool(row.get("intent_mismatch")),
            "topic_mismatch": bool(row.get("topic_mismatch")),
            "meta_description": row.get("meta_description") or UNAVAILABLE,
            "content_type": row.get("content_type"),
            "authority": row.get("authority"),
            "word_count": row.get("word_count"),
            "updated": row.get("updated") or UNAVAILABLE,
            "updated_at": row.get("updated_at"),
            "extract_ok": bool(row.get("extract_ok")),
            "scores": _public_score_block(row.get("scores") or {}),
            "h1_count": row.get("h1_count"),
            "h2_count": row.get("h2_count"),
            "h1_headings": (row.get("h1_headings") or [])[:12],
            "h2_headings": (row.get("h2_headings") or [])[:16],
            "signals": row.get("signals") or [],
            "does_well": row.get("does_well") or "",
            "schema_types": row.get("schema_types") or [],
            "author": row.get("author") or UNAVAILABLE,
            "image_count": row.get("image_count") or 0,
            "generic_alts": row.get("generic_alts") or 0,
            "internal_links": row.get("internal_links") or 0,
            "external_links": row.get("external_links") or 0,
            "faq": row.get("faq") or {},
            "canonical": row.get("canonical") or UNAVAILABLE,
            "robots": row.get("robots") or UNAVAILABLE,
            "table_count": row.get("table_count") or 0,
            "domain_authority": UNAVAILABLE,
            "backlinks": UNAVAILABLE,
            "core_web_vitals": UNAVAILABLE,
        })
    serp_insights = []
    if user_intent == "informational" and any(row.get("intent_mismatch") for row in slim_competitors):
        serp_insights.append("This query contains mixed intent; shopping pages also appear.")
    word_vals = [int(row.get("word_count") or 0) for row in competitors if int(row.get("word_count") or 0) > 0]
    competitor_avg_words = (sum(word_vals) / len(word_vals)) if word_vals else None
    diagnosis_summary = build_diagnosis_summary(
        gsc_diagnosis,
        target_keyword=keyword or "",
        page=your_page,
        content_gaps=gap_report,
        competitor_avg_words=competitor_avg_words,
    )
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", full_text) if p.strip()][:40]
    your_page_out = None
    if your_page:
        your_page_out = {
            "url": your_page.get("url") or blog_url or "",
            "title": source_title or your_page.get("title") or UNAVAILABLE,
            "meta_description": your_page.get("meta_description") or UNAVAILABLE,
            "h1": your_page.get("h1") or "",
            "h2": (your_page.get("h2_headings") or [])[:24],
            "h1_count": your_page.get("h1_count") or 0,
            "h2_count": your_page.get("h2_count") or 0,
            "h1_headings": your_page.get("h1_headings") or [],
            "h2_headings": your_page.get("h2_headings") or [],
            "full_text": full_text[:4000],
            "paragraphs": paragraphs,
            "word_count": your_page.get("word_count"),
            "language": language,
            "author": your_page.get("author") or None,
            "published_date": None,
            "updated_date": your_page.get("updated_at") or your_page.get("updated"),
            "internal_links": your_page.get("internal_links") if isinstance(your_page.get("internal_links"), list) else [],
            "external_links": your_page.get("external_links") if isinstance(your_page.get("external_links"), list) else [],
            "internal_link_count": your_page.get("internal_links") if isinstance(your_page.get("internal_links"), int) else 0,
            "external_link_count": your_page.get("external_links") if isinstance(your_page.get("external_links"), int) else 0,
            "images": your_page.get("images") or [],
            "primary_keywords": [row["keyword"] for row in (keyword_report.get("table") or []) if row.get("type") == "primary"][:8],
            "secondary_keywords": [row["keyword"] for row in (keyword_report.get("table") or []) if row.get("type") == "secondary"][:12],
            "long_tail_keywords": [row["keyword"] for row in (keyword_report.get("table") or []) if row.get("type") == "long-tail"][:12],
            "entities": [],
            "schema_types": your_page.get("schema_types") or [],
            "extract_ok": bool(your_page.get("extract_ok")),
            "canonical": your_page.get("canonical") or UNAVAILABLE,
            "faq": your_page.get("faq") or {},
            "image_count": your_page.get("image_count") or 0,
        }
    return {
        "analysis_id": analysis_id,
        "client_analysis_id": client_analysis_id,
        "analysis_mode": mode,
        "blog_url_status": blog_url_status,
        "target_keyword_source": keyword_source,
        "serp_query": serp_query,
        "serp_query_source": serp_query_source,
        "detected_keyword": detected_keyword,
        "detected_keyword_evidence": detected_evidence,
        "blog_url": blog_url or "",
        "target_keyword": serp_query,
        "country": country,
        "language": language,
        "competitor_count": target_n,
        "competitor_urls": used_manual_urls,
        "excluded_competitor_urls": excluded_manuals,
        "analyzed_at": analyzed_at,
        "your_page": your_page_out,
        "source_article": source_article,
        "source_title": source_title,
        "source_extract_error": source_extract_error,
        "old_scores": your_scores,
        "your_scores": your_scores,
        "scores": your_scores.get("scores") or your_scores.get("reports") or {},
        "competitor_avg_scores": avg_scores,
        "score_diffs": diffs,
        "competitors": slim_competitors,
        "keywords": keyword_report,
        "keyword_gaps": keyword_report,
        "keyword_mismatch": keyword_mismatch,
        "content_gaps": gap_report,
        "citations": citations,
        "traffic": traffic,
        "readability": readability,
        "humanization": human,
        "originality": original,
        "images": image_report,
        "action_plan": plan,
        "action_plan_report": plan_payload,
        "gsc_diagnosis": gsc_diagnosis,
        "diagnosis_window": window,
        "diagnosis_summary": diagnosis_summary,
        "serp_warning": serp_warning,
        "serp_insights": serp_insights,
        "article_intent": user_intent,
        "serp": {
            "keyword": serp_query,
            "related_queries": serp.related_queries[:8],
            "common_headings": serp.common_headings[:8],
            "nlp_keywords": (serp.nlp_keywords or [])[:12],
        },
        "unavailable_metrics": [
            metric
            for metric in (
                "search volume",
                "keyword difficulty",
                "domain authority",
                "backlinks",
                "referring domains",
                "Core Web Vitals",
                "verified traffic",
            )
            if metric != "verified traffic" or gsc_diagnosis.get("status") != "ok"
        ],
    }
