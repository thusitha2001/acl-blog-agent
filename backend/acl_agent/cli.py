"""
ACL Blog Agent - command-line interface: ingest, generate,
quick, example, validate, and server subcommands.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Optional

import uvicorn

from acl_agent.config import OUTPUT_DIR, logger
from acl_agent.knowledge_base import build_knowledge_base
from acl_agent.models import ContentBrief, SEOAnalysis
from acl_agent.pipeline_1click import generate_1click, generate_full_pipeline
from acl_agent.scraping import load_urls_from_csv
from acl_agent.validation import validate_article


def command_ingest(
    urls_csv: Optional[str] = None,
    url_column: str = "URL",
    human_written_column: str = "Human Written",
):
    urls = None

    if urls_csv:
        urls = load_urls_from_csv(
            urls_csv,
            url_column=url_column,
            human_written_column=human_written_column,
        )

        style_count = sum(
            1 for _, source_type in urls
            if source_type == "style"
        )

        logger.info(
            "Loaded %s URLs from %s (%s tagged as "
            "human-written style references)",
            len(urls),
            urls_csv,
            style_count,
        )

    result = build_knowledge_base(urls=urls)

    print(
        json.dumps(
            result,
            indent=2,
        )
    )


def command_generate(input_path: str):
    payload = json.loads(
        Path(input_path).read_text(
            encoding="utf-8"
        )
    )

    brief = ContentBrief.model_validate(payload)

    result = generate_full_pipeline(brief)

    output_path = (
        OUTPUT_DIR
        / f"blog-{int(time.time())}.json"
    )

    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    article_path = (
        OUTPUT_DIR
        / f"article-{int(time.time())}.md"
    )

    article_path.write_text(
        result["article"],
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "json_output": str(output_path),
                "markdown_output": str(article_path),
                "validation": result["validation"],
            },
            indent=2,
        )
    )


def command_quick(
    keyword: str,
    title: Optional[str] = None,
    size: str = "medium",
    tone: str = "friendly",
    language: str = "en-US",
    include_faq: bool = True,
    include_takeaways: bool = True,
    hook_type: str = "question",
    additional_instructions: str = "",
):
    """1-click blog post generation from a keyword."""
    logger.info(
        "1-click generation: '%s' (size=%s, tone=%s)",
        keyword,
        size,
        tone,
    )

    result = generate_1click(
        keyword=keyword,
        title=title,
        size=size,
        tone=tone,
        language=language,
        include_faq=include_faq,
        include_takeaways=include_takeaways,
        hook_type=hook_type,
        additional_instructions=additional_instructions,
    )

    # Save outputs
    timestamp = int(time.time())

    json_path = OUTPUT_DIR / f"quick-{timestamp}.json"
    json_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    article_path = (
        OUTPUT_DIR / f"article-{timestamp}.md"
    )
    article_path.write_text(
        result["article"],
        encoding="utf-8",
    )

    # Print summary
    validation = result.get("validation", {})
    seo = result.get("seo", {})
    serp = result.get("serp", {})

    output = {
        "title": seo.get("meta_title", ""),
        "word_count": validation.get("word_count", 0),
        "validation_passed": validation.get(
            "passed", False
        ),
        "errors": len(validation.get("errors", [])),
        "warnings": len(validation.get("warnings", [])),
        "nlp_keywords_found": len(
            serp.get("nlp_keywords", [])
        ),
        "secondary_keywords": len(
            seo.get("secondary_keywords", [])
        ),
        "json_output": str(json_path),
        "markdown_output": str(article_path),
    }

    print(json.dumps(output, indent=2))


def command_validate(input_path: str):
    payload = json.loads(
        Path(input_path).read_text(
            encoding="utf-8"
        )
    )

    brief = ContentBrief.model_validate(
        payload["brief"]
    )

    seo = SEOAnalysis.model_validate(
        payload["seo"]
    )

    validation = validate_article(
        article=payload["article"],
        brief=brief,
        meta_title=seo.meta_title,
        meta_description=seo.meta_description,
        internal_links=seo.internal_links,
    )

    print(
        json.dumps(
            validation,
            indent=2,
        )
    )


def command_server(host: str, port: int, reload: bool):
    host = os.getenv("HOST", host)
    port = int(os.getenv("PORT", port))
    reload = os.getenv("RELOAD", str(reload)).lower() in ("1", "true", "yes")
    uvicorn.run(
        "acl_agent.api:app",
        host=host,
        port=port,
        reload=reload,
    )


def main():
    parser = argparse.ArgumentParser(
        description="ACL Blog Agent"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # ingest
    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Scrape blogs and build FAISS index",
    )

    ingest_parser.add_argument(
        "--urls-csv",
        default=None,
        help="Path to CSV with URL column",
    )

    ingest_parser.add_argument(
        "--url-column",
        default="URL",
        help="Column name for URLs",
    )

    ingest_parser.add_argument(
        "--human-written-column",
        default="Human Written",
        help="Column flagging human-written blogs",
    )

    # generate
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate article from JSON brief",
    )

    generate_parser.add_argument(
        "input",
        help="Path to content brief JSON",
    )

    # quick (1-click)
    quick_parser = subparsers.add_parser(
        "quick",
        help=(
            "1-click: generate article from just a keyword"
        ),
    )

    quick_parser.add_argument(
        "keyword",
        help="Main keyword or topic",
    )

    quick_parser.add_argument(
        "--title",
        default=None,
        help="Optional custom title",
    )

    quick_parser.add_argument(
        "--size",
        choices=["x-small", "small", "medium", "large", "x-large"],
        default="medium",
        help="Article size (default: medium)",
    )

    quick_parser.add_argument(
        "--tone",
        choices=[
            "friendly",
            "professional",
            "informational",
            "transactional",
            "inspirational",
            "neutral",
            "witty",
            "casual",
            "authoritative",
            "encouraging",
            "persuasive",
            "poetic",
        ],
        default="friendly",
        help="Tone of voice (default: friendly)",
    )

    quick_parser.add_argument(
        "--language",
        default="en-US",
        help="Language (default: en-US)",
    )

    quick_parser.add_argument(
        "--no-faq",
        action="store_true",
        help="Exclude FAQ section",
    )

    quick_parser.add_argument(
        "--no-takeaways",
        action="store_true",
        help="Exclude key takeaways",
    )

    quick_parser.add_argument(
        "--hook",
        choices=[
            "question",
            "statistic",
            "fact",
            "anecdote",
        ],
        default="question",
        help="Opening hook type (default: question)",
    )

    quick_parser.add_argument(
        "--instructions",
        default="",
        help="Additional instructions",
    )

    # example
    # validate
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a saved pipeline result",
    )

    validate_parser.add_argument(
        "input",
        help="Path to pipeline result JSON",
    )

    # server
    server_parser = subparsers.add_parser(
        "server",
        help="Start FastAPI server",
    )

    server_parser.add_argument(
        "--host",
        default=os.getenv("HOST", "127.0.0.1"),
    )

    server_parser.add_argument(
        "--port",
        default=int(os.getenv("PORT", "8001")),
        type=int,
    )

    server_parser.add_argument(
        "--reload",
        action="store_true",
        default=False,
        help="Enable auto-reload (use for local dev only)",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        command_ingest(
            urls_csv=args.urls_csv,
            url_column=args.url_column,
            human_written_column=(
                args.human_written_column
            ),
        )

    elif args.command == "generate":
        command_generate(args.input)

    elif args.command == "quick":
        command_quick(
            keyword=args.keyword,
            title=args.title,
            size=args.size,
            tone=args.tone,
            language=args.language,
            include_faq=not args.no_faq,
            include_takeaways=not args.no_takeaways,
            hook_type=args.hook,
            additional_instructions=args.instructions,
        )

    elif args.command == "validate":
        command_validate(args.input)

    elif args.command == "server":
        command_server(
            host=args.host,
            port=args.port,
            reload=args.reload,
        )


if __name__ == "__main__":
    main()
