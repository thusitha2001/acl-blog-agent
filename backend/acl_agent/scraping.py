"""
ACL Blog Agent - HTTP fetching, scraping, chunking, and CSV
URL-list loading.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from acl_agent.config import BLOG_URL, BRAND_SITE, logger

def fetch_url(url: str) -> str:
    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; ACLBlogAgent/1.0)"
            )
        },
    )

    response.raise_for_status()
    return response.text


def clean_text(text: str) -> str:
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def is_valid_sample(content: str) -> bool:
    content_lower = content.lower()

    invalid_markers = [
        "paste one of your best",
        "paste another representative",
        "curated acl sample blog",
    ]

    return bool(content.strip()) and not any(
        marker in content_lower
        for marker in invalid_markers
    )


def scrape_blog_list(
    url: str,
    limit: int,
) -> list[str]:
    links: list[str] = []
    page = 1

    while len(links) < limit and page <= 20:
        page_url = (
            url
            if page == 1
            else f"{url}?page={page}"
        )

        try:
            html = fetch_url(page_url)
        except Exception as error:
            logger.warning(
                "Could not fetch blog page %s: %s",
                page,
                error,
            )
            break

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        new_on_page = 0

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            href = anchor["href"].strip()

            if "/blogs/news/" not in href:
                continue

            if href.startswith("/"):
                full_url = BRAND_SITE + href
            else:
                full_url = href

            full_url = (
                full_url
                .split("?")[0]
                .split("#")[0]
                .rstrip("/")
            )

            if full_url == BLOG_URL.rstrip("/"):
                continue

            if full_url not in links:
                links.append(full_url)
                new_on_page += 1

            if len(links) >= limit:
                break

        logger.info(
            "Blog page %s: %s new URLs",
            page,
            new_on_page,
        )

        if new_on_page == 0:
            break

        page += 1

    return links[:limit]


def load_urls_from_csv(
    path: str,
    url_column: str = "URL",
    human_written_column: Optional[str] = "Human Written",
) -> list[tuple[str, str]]:
    """
    Reads a CSV file (e.g. exported from a Google Sheet via
    File > Download > Comma Separated Values) and returns a list of
    (url, source_type) pairs.

    source_type is "style" for rows flagged as human-written, and
    "article" for everything else (still used for facts/links, just
    excluded from style retrieval).

    A row counts as human-written if human_written_column's value
    (case-insensitively) is one of: yes, y, true, 1, human.

    If human_written_column is None or not present in the CSV, every
    row is treated as source_type="article" (existing behavior).

    The url_column name is matched case-insensitively and with
    surrounding whitespace stripped, so "URL", "url", " URL " all
    match.
    """
    import csv as csv_module

    HUMAN_TRUE_VALUES = {"yes", "y", "true", "1", "human"}

    csv_path = Path(path)

    if not csv_path.exists():
        raise FileNotFoundError(
            f"URL list CSV not found: {path}"
        )

    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    with csv_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv_module.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(
                f"CSV file has no header row: {path}"
            )

        normalized_fields = {
            (name or "").strip().lower(): name
            for name in reader.fieldnames
        }

        target_key = url_column.strip().lower()

        if target_key not in normalized_fields:
            raise ValueError(
                f"Column '{url_column}' not found in CSV. "
                f"Available columns: {list(reader.fieldnames)}"
            )

        actual_url_column = normalized_fields[target_key]

        actual_human_column = None

        if human_written_column:
            human_key = human_written_column.strip().lower()
            actual_human_column = normalized_fields.get(human_key)

            if actual_human_column is None:
                logger.warning(
                    "Column '%s' not found in CSV; treating all "
                    "rows as source_type='article'. Available "
                    "columns: %s",
                    human_written_column,
                    list(reader.fieldnames),
                )

        for row in reader:
            raw_value = (row.get(actual_url_column) or "").strip()

            if not raw_value:
                continue

            if not raw_value.lower().startswith("http"):
                continue

            cleaned = raw_value.split("#")[0].rstrip("/")

            if cleaned in seen:
                continue

            seen.add(cleaned)

            is_human = False

            if actual_human_column:
                flag_value = (
                    row.get(actual_human_column) or ""
                ).strip().lower()

                is_human = flag_value in HUMAN_TRUE_VALUES

            source_type = "style" if is_human else "article"
            results.append((cleaned, source_type))

    return results


def scrape_url_for_request(url: str) -> str:
    """
    Fresh, in-memory-only scrape of a user-provided URL for a single
    generation request.

    If the URL looks like a blog listing (its page links to
    /blogs/... articles), the first few article links are also
    scraped. Content is combined into one context string with
    - URL - headers per source.

    Returns an empty string if nothing could be scraped. The result
    is NEVER written to the persistent knowledge base or data/ files.
    """
    try:
        html = fetch_url(url)
    except Exception as error:
        logger.warning(
            "Could not fetch request URL %s: %s",
            url,
            error,
        )
        return ""

    soup = BeautifulSoup(html, "html.parser")

    article_links: list[str] = []
    already_seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if "/blogs/" not in href:
            continue
        if href.startswith("/"):
            href = url.rstrip("/") + href
        href = href.split("?")[0].split("#")[0].rstrip("/")
        if href and href not in already_seen:
            already_seen.add(href)
            article_links.append(href)

    targets = [url]
    targets.extend(
        article_links[:2]
    )

    sections: list[str] = []

    for target in targets[:3]:
        try:
            page = scrape_blog_content(target)
            text = page["content"]
        except Exception as error:
            logger.warning(
                "Could not scrape %s: %s",
                target,
                error,
            )
            continue

        if not text:
            continue

        sections.append(
            "\n".join(
                [
                    f"- URL -",
                    page["title"] or url,
                    target,
                    "----------",
                    text,
                ]
            )
        )

    return "\n\n".join(sections)


def scrape_blog_content(url: str) -> dict[str, str]:
    html = fetch_url(url)

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "aside",
        ]
    ):
        tag.decompose()

    title_tag = soup.find("h1")

    title = (
        title_tag.get_text(
            " ",
            strip=True,
        )
        if title_tag
        else url
    )

    article = (
        soup.find("article")
        or soup.find(
            "main"
        )
        or soup.body
    )

    text = (
        article.get_text(
            " ",
            strip=True,
        )
        if article
        else soup.get_text(
            " ",
            strip=True,
        )
    )

    return {
        "url": url,
        "title": clean_text(title),
        "content": clean_text(text),
    }


def chunk_text(
    text: str,
    max_words: int = 500,
    overlap: int = 75,
) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    start = 0

    while start < len(words):
        end = min(
            start + max_words,
            len(words),
        )

        chunk = " ".join(
            words[start:end]
        ).strip()

        if chunk:
            chunks.append(chunk)

        if end == len(words):
            break

        start = max(
            0,
            end - overlap,
        )

    return chunks

