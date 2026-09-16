"""
ACL Blog Agent - FastAPI application: lifespan and HTTP endpoints.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError

from acl_agent import knowledge_base
from acl_agent.auth import login_user, logout_user, signup_user, verify_token
from acl_agent.config import (
    ALLOWED_ORIGINS,
    CORS_ALLOW_CREDENTIALS,
    ROOT_DIR,
    logger,
)
from acl_agent.knowledge_base import load_knowledge_base
from acl_agent.models import ContentBrief, InternalLink, KeywordTarget, SEOAnalysis
from acl_agent.competitors import analyze_competitors
from acl_agent.pipeline_1click import generate_1click, generate_full_pipeline
from acl_agent.rewrite import rewrite_article


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_knowledge_base()
    yield


app = FastAPI(
    title="Blog Agent",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


FRONTEND_DIR = ROOT_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="assets",
    )


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(FRONTEND_DIR / "dashboard.html"))


@app.get("/writer", include_in_schema=False)
def writer_page():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/rewriter", include_in_schema=False)
def rewriter_page():
    return FileResponse(str(FRONTEND_DIR / "rewriter.html"))


@app.get("/competitors", include_in_schema=False)
def competitors_page():
    return FileResponse(str(FRONTEND_DIR / "competitors.html"))


@app.get("/editor", include_in_schema=False)
def editor_page():
    return FileResponse(str(FRONTEND_DIR / "editor.html"))


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(str(FRONTEND_DIR / "login.html"))


@app.get("/settings", include_in_schema=False)
def settings_page():
    return FileResponse(str(FRONTEND_DIR / "settings.html"))


@app.get("/health")
def health_endpoint():
    return {
        "status": "ok",
        "knowledge_base_loaded": (
            knowledge_base._faiss_index is not None
        ),
        "knowledge_chunks": len(
            knowledge_base._knowledge_chunks
        ),
    }


@app.post("/generate-full")
def generate_full_endpoint(
    brief: ContentBrief,
):
    request_id = str(uuid.uuid4())

    try:
        result = generate_full_pipeline(brief)
        result["request_id"] = request_id
        return result

    except ValidationError as error:
        logger.exception(
            "Validation error: %s",
            request_id,
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid model output.",
                "request_id": request_id,
            },
        ) from error

    except Exception as error:
        logger.exception(
            "Generation failed: %s",
            request_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Blog generation failed.",
                "request_id": request_id,
            },
        ) from error


class OneClickRequest(BaseModel):
    user_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional user identifier. Included in the result "
        "payload and SSE events for per-user tracking.",
    )
    keyword: str = Field(
        min_length=2,
        max_length=200,
        description="Main keyword or topic",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional custom title",
    )
    search_intent: str = Field(
        default="informational",
        description=(
            "Search intent: informational, commercial, "
            "transactional, or navigational"
        ),
    )
    size: str = Field(
        default="medium",
        description="Article size: x-small, small, medium, large, or x-large",
    )
    target_word_count: Optional[int] = Field(
        default=None,
        ge=300,
        le=8000,
        description="Exact target word count. Overrides size when provided.",
    )
    article_type: Optional[str] = Field(
        default=None,
        description="Article type: how-to, listicle, review, news, comparison, case-study, opinion, tutorial, roundup, qa",
    )
    tone: str = Field(
        default="friendly",
        description="Tone of voice",
    )
    point_of_view: Optional[str] = Field(
        default=None,
        description="Point of view: first-singular, first-plural, second, third",
    )
    readability: Optional[str] = Field(
        default=None,
        description="Text readability level",
    )
    language: str = Field(
        default="en-US",
        description="Language code",
    )
    brand_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Brand name override",
    )
    website: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Website URL override",
    )
    include_faq: bool = Field(
        default=True,
        description="Include FAQ section",
    )
    include_takeaways: bool = Field(
        default=True,
        description="Include key takeaways",
    )
    include_conclusion: bool = Field(
        default=True,
        description="Include conclusion",
    )
    include_tables: bool = Field(
        default=False,
        description="Include comparison tables",
    )
    include_h3: bool = Field(
        default=True,
        description="Use H3 subheadings",
    )
    include_lists: bool = Field(
        default=True,
        description="Include bulleted/numbered lists",
    )
    include_quotes: bool = Field(
        default=False,
        description="Include blockquotes",
    )
    include_italics: bool = Field(
        default=False,
        description="Use italics for emphasis",
    )
    include_bold: bool = Field(
        default=False,
        description="Use bold for emphasis",
    )
    additional_instructions: str = Field(
        default="",
        max_length=1000,
        description="Additional instructions (max 150 words)",
    )
    hook_type: str = Field(
        default="question",
        description="Hook type: question, statistic, fact, anecdote",
    )
    hook_brief: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Brief description of the hook for the opening sentence (max 30 words)",
    )
    brand_voice: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Brand voice description (max 100 words)",
    )
    audience: Optional[str] = Field(
        default=None,
        max_length=300,
        description="Target audience for the article (max 40 words)",
    )
    internal_links: list[InternalLink] = Field(
        default_factory=list,
        description=(
            "Internal pages to weave into the article. "
            "Each item needs url, plus optional anchor_text and reason."
        ),
    )

    @field_validator("search_intent")
    @classmethod
    def _valid_search_intent(cls, value: str) -> str:
        allowed = {
            "informational",
            "commercial",
            "transactional",
            "navigational",
        }
        normalized = (value or "").strip().lower()
        if normalized not in allowed:
            raise ValueError(
                "Search Intent must be informational, commercial, "
                "transactional, or navigational."
            )
        return normalized

    @field_validator("additional_instructions")
    @classmethod
    def _word_limit_instructions(cls, value: str) -> str:
        if len(value.split()) > 150:
            raise ValueError(
                "Additional Instructions must be 150 words or fewer "
                f"(got {len(value.split())})."
            )
        return value

    @field_validator("hook_brief")
    @classmethod
    def _word_limit_hook_brief(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value.split()) > 30:
            raise ValueError(
                "Hook Brief must be 30 words or fewer "
                f"(got {len(value.split())})."
            )
        return value

    @field_validator("brand_voice")
    @classmethod
    def _word_limit_brand_voice(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value.split()) > 100:
            raise ValueError(
                "Brand Voice must be 100 words or fewer "
                f"(got {len(value.split())})."
            )
        return value

    @field_validator("audience")
    @classmethod
    def _word_limit_audience(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value.split()) > 40:
            raise ValueError(
                "Target Audience must be 40 words or fewer "
                f"(got {len(value.split())})."
            )
        return value

    @field_validator("internal_links")
    @classmethod
    def _limit_internal_links(
        cls,
        value: list[InternalLink],
    ) -> list[InternalLink]:
        if len(value) > 12:
            raise ValueError("Internal Links limited to 12 URLs.")
        return value


class RewriteRequest(BaseModel):
    source_article: str = Field(
        min_length=200,
        max_length=50000,
        description="Existing article to rewrite (HTML or plain text).",
    )
    keyword: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional primary keyword for the rewritten piece.",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional title for the rewritten article.",
    )
    tone: str = Field(default="friendly")
    target_word_count: Optional[int] = Field(
        default=None,
        ge=300,
        le=8000,
    )
    point_of_view: Optional[str] = Field(default=None)
    readability: Optional[str] = Field(default=None)
    language: str = Field(default="en-US")
    brand_name: Optional[str] = Field(default=None, max_length=200)
    website: Optional[str] = Field(default=None, max_length=300)
    brand_voice: Optional[str] = Field(default=None, max_length=500)
    audience: Optional[str] = Field(default=None, max_length=300)
    additional_instructions: str = Field(default="", max_length=1000)
    include_faq: bool = True
    include_takeaways: bool = True
    include_conclusion: bool = True
    include_tables: bool = False
    include_h3: bool = True
    include_lists: bool = True
    include_quotes: bool = False

    @field_validator("keyword")
    @classmethod
    def _empty_keyword(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("additional_instructions")
    @classmethod
    def _rewrite_word_limit_instructions(cls, value: str) -> str:
        if len(value.split()) > 150:
            raise ValueError(
                "Additional Instructions must be 150 words or fewer "
                f"(got {len(value.split())})."
            )
        return value

    @field_validator("audience")
    @classmethod
    def _rewrite_word_limit_audience(cls, value: Optional[str]) -> Optional[str]:
        if value and len(value.split()) > 40:
            raise ValueError(
                "Target Audience must be 40 words or fewer "
                f"(got {len(value.split())})."
            )
        return value


class CompetitorAnalyzeRequest(BaseModel):
    blog_url: Optional[str] = Field(default=None, max_length=500)
    keyword: Optional[str] = Field(default=None, max_length=200)

    @field_validator("blog_url")
    @classmethod
    def _clean_blog_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not re.match(r"^https?://", stripped, flags=re.IGNORECASE):
            raise ValueError("Blog URL must start with http:// or https://")
        return stripped

    @field_validator("keyword")
    @classmethod
    def _clean_keyword(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ScoreArticleRequest(BaseModel):
    article: str = Field(min_length=20, max_length=80000)
    keyword: Optional[str] = Field(default=None, max_length=200)
    title: Optional[str] = Field(default=None, max_length=200)
    meta_title: Optional[str] = Field(default=None, max_length=200)
    meta_description: Optional[str] = Field(default=None, max_length=500)
    target_word_count: Optional[int] = Field(default=None, ge=300, le=8000)
    secondary_keywords: list[str] = Field(default_factory=list)


class AuthRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=100,
        description="User name",
    )
    password: str = Field(
        min_length=4,
        max_length=200,
        description="Password",
    )


def require_auth(
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """FastAPI dependency: validates the bearer token and returns the user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail={"message": "Missing or invalid Authorization header"},
        )
    user = verify_token(authorization[len("Bearer "):].strip())
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"message": "Invalid or expired token - please log in"},
        )
    return user


@app.post("/auth/signup")
def auth_signup(request: AuthRequest):
    try:
        user = signup_user(request.name, request.password)
    except ValueError as error:
        raise HTTPException(
            status_code=409,
            detail={"message": str(error)},
        ) from error
    return user


@app.post("/auth/login")
def auth_login(request: AuthRequest):
    user = login_user(request.name, request.password)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Invalid name or password - please try again",
            },
        )
    return user


@app.get("/auth/me")
def auth_me(user: dict = Depends(require_auth)):
    return user


@app.post("/auth/logout")
def auth_logout(user: dict = Depends(require_auth)):
    logout_user(user["token"])
    return {"ok": True}


@app.post("/generate-1click")
def generate_1click_endpoint(
    request: OneClickRequest,
    _user: dict = Depends(require_auth),
):
    request_id = str(uuid.uuid4())

    try:
        result = generate_1click(
            keyword=request.keyword,
            title=request.title,
            search_intent=request.search_intent,
            size=request.size,
            target_word_count=request.target_word_count,
            article_type=request.article_type,
            tone=request.tone,
            point_of_view=request.point_of_view,
            readability=request.readability,
            brand_voice=request.brand_voice,
            language=request.language,
            brand_name=request.brand_name,
            website=request.website,
            user_id=None,
            include_faq=request.include_faq,
            include_takeaways=request.include_takeaways,
            include_conclusion=request.include_conclusion,
            include_tables=request.include_tables,
            include_h3=request.include_h3,
            include_lists=request.include_lists,
            include_quotes=request.include_quotes,
            include_italics=request.include_italics,
            include_bold=request.include_bold,
            hook_type=request.hook_type,
            hook_brief=request.hook_brief,
            additional_instructions=(
                request.additional_instructions
            ),
            audience=request.audience,
            internal_links=request.internal_links or None,
        )

        result["request_id"] = request_id
        return result

    except Exception as error:
        logger.exception(
            "1-click generation failed: %s",
            request_id,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "message": str(error),
                "request_id": request_id,
            },
        ) from error


@app.post("/generate-1click-stream")
async def generate_1click_stream_endpoint(
    request: OneClickRequest,
    _user: dict = Depends(require_auth),
):
    request_id = str(uuid.uuid4())
    queue: "asyncio.Queue[tuple[str, dict]]" = asyncio.Queue()
    worker_loop: "asyncio.AbstractEventLoop | None" = None
    loop_lock = asyncio.Lock()

    async def event_stream():
        nonlocal worker_loop

        def emit(event_type: str, data: dict) -> None:
            data["request_id"] = request_id
            asyncio.run_coroutine_threadsafe(
                queue.put((event_type, data)),
                worker_loop,
            )

        async def runner():
            nonlocal worker_loop
            worker_loop = asyncio.get_running_loop()
            try:
                import functools
                run_func = functools.partial(
                    generate_1click,
                    keyword=request.keyword,
                    title=request.title,
                    search_intent=request.search_intent,
                    size=request.size,
                    target_word_count=request.target_word_count,
                    article_type=request.article_type,
                    tone=request.tone,
                    point_of_view=request.point_of_view,
                    readability=request.readability,
                    brand_voice=request.brand_voice,
                    language=request.language,
                    brand_name=request.brand_name,
                    website=request.website,
                    user_id=None,
                    include_faq=request.include_faq,
                    include_takeaways=request.include_takeaways,
                    include_conclusion=request.include_conclusion,
                    include_tables=request.include_tables,
                    include_h3=request.include_h3,
                    include_lists=request.include_lists,
                    include_quotes=request.include_quotes,
                    include_italics=request.include_italics,
                    include_bold=request.include_bold,
                    hook_type=request.hook_type,
                    hook_brief=request.hook_brief,
                    additional_instructions=(
                        request.additional_instructions
                    ),
                    audience=request.audience,
                    internal_links=request.internal_links or None,
                    on_event=lambda evt, data: emit(evt, data),
                )
                try:
                    result = await asyncio.to_thread(run_func)
                except Exception as error:
                    logger.exception("stream generation failed")
                    await queue.put(("error", {
                        "message": str(error),
                        "request_id": request_id,
                    }))
                else:
                    await queue.put(("result", result))
            finally:
                await queue.put(("__done__", {"request_id": request_id}))

        task = asyncio.create_task(runner())

        # Keep-alive interval (seconds). Proxies like ngrok drop idle
        # connections, so during long model calls we send an SSE
        # comment line to keep the tunnel/browser connection alive.
        KEEPALIVE_INTERVAL = 15.0
        last_keepalive = time.monotonic()

        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    if (
                        time.monotonic() - last_keepalive
                        >= KEEPALIVE_INTERVAL
                    ):
                        last_keepalive = time.monotonic()
                        yield ": keepalive\n\n"
                    continue

                if event_type == "__done__":
                    break

                event_data = json.dumps(data, default=str)
                yield f"event: {event_type}\ndata: {event_data}\n\n"
                last_keepalive = time.monotonic()

                if event_type == "result":
                    break
                if event_type == "error":
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/rewrite-stream")
async def rewrite_stream_endpoint(
    request: RewriteRequest,
    _user: dict = Depends(require_auth),
):
    request_id = str(uuid.uuid4())
    queue: "asyncio.Queue[tuple[str, dict]]" = asyncio.Queue()
    worker_loop: "asyncio.AbstractEventLoop | None" = None

    async def event_stream():
        nonlocal worker_loop

        def emit(event_type: str, data: dict) -> None:
            data["request_id"] = request_id
            asyncio.run_coroutine_threadsafe(
                queue.put((event_type, data)),
                worker_loop,
            )

        async def runner():
            nonlocal worker_loop
            worker_loop = asyncio.get_running_loop()
            try:
                import functools
                run_func = functools.partial(
                    rewrite_article,
                    source_article=request.source_article,
                    keyword=request.keyword,
                    title=request.title,
                    tone=request.tone,
                    target_word_count=request.target_word_count,
                    point_of_view=request.point_of_view,
                    readability=request.readability,
                    brand_voice=request.brand_voice,
                    language=request.language,
                    brand_name=request.brand_name,
                    website=request.website,
                    audience=request.audience,
                    additional_instructions=(
                        request.additional_instructions
                    ),
                    include_faq=request.include_faq,
                    include_takeaways=request.include_takeaways,
                    include_conclusion=request.include_conclusion,
                    include_tables=request.include_tables,
                    include_h3=request.include_h3,
                    include_lists=request.include_lists,
                    include_quotes=request.include_quotes,
                    on_event=lambda evt, data: emit(evt, data),
                )
                try:
                    result = await asyncio.to_thread(run_func)
                except Exception as error:
                    logger.exception("stream rewrite failed")
                    await queue.put(("error", {
                        "message": str(error),
                        "request_id": request_id,
                    }))
                else:
                    await queue.put(("result", result))
            finally:
                await queue.put(("__done__", {"request_id": request_id}))

        task = asyncio.create_task(runner())
        KEEPALIVE_INTERVAL = 15.0
        last_keepalive = time.monotonic()

        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    if (
                        time.monotonic() - last_keepalive
                        >= KEEPALIVE_INTERVAL
                    ):
                        last_keepalive = time.monotonic()
                        yield ": keepalive\n\n"
                    continue

                if event_type == "__done__":
                    break

                event_data = json.dumps(data, default=str)
                yield f"event: {event_type}\ndata: {event_data}\n\n"
                last_keepalive = time.monotonic()

                if event_type in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/analyze-competitors-stream")
async def analyze_competitors_stream_endpoint(
    request: CompetitorAnalyzeRequest,
    _user: dict = Depends(require_auth),
):
    if not request.blog_url and not request.keyword:
        raise HTTPException(
            status_code=400,
            detail={"message": "Enter a blog URL or a target keyword."},
        )

    request_id = str(uuid.uuid4())
    queue: "asyncio.Queue[tuple[str, dict]]" = asyncio.Queue()
    worker_loop: "asyncio.AbstractEventLoop | None" = None

    async def event_stream():
        nonlocal worker_loop

        def emit(event_type: str, data: dict) -> None:
            data["request_id"] = request_id
            asyncio.run_coroutine_threadsafe(
                queue.put((event_type, data)),
                worker_loop,
            )

        async def runner():
            nonlocal worker_loop
            worker_loop = asyncio.get_running_loop()
            try:
                import functools

                run_func = functools.partial(
                    analyze_competitors,
                    blog_url=request.blog_url,
                    keyword=request.keyword,
                    on_progress=lambda stage, message: emit(
                        "stage",
                        {
                            "stage": stage,
                            "message": message,
                            "status": "active",
                        },
                    ),
                )
                try:
                    result = await asyncio.to_thread(run_func)
                except ValueError as error:
                    await queue.put(("error", {
                        "message": str(error),
                        "request_id": request_id,
                    }))
                except Exception as error:
                    logger.exception("competitor analysis failed")
                    await queue.put(("error", {
                        "message": str(error),
                        "request_id": request_id,
                    }))
                else:
                    await queue.put(("result", result))
            finally:
                await queue.put(("__done__", {"request_id": request_id}))

        task = asyncio.create_task(runner())
        keepalive_interval = 15.0
        last_keepalive = time.monotonic()

        try:
            while True:
                try:
                    event_type, data = await asyncio.wait_for(
                        queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    if time.monotonic() - last_keepalive >= keepalive_interval:
                        last_keepalive = time.monotonic()
                        yield ": keepalive\n\n"
                    continue

                if event_type == "__done__":
                    break

                event_data = json.dumps(data, default=str)
                yield f"event: {event_type}\ndata: {event_data}\n\n"
                last_keepalive = time.monotonic()

                if event_type in ("result", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/score-article")
def score_article_endpoint(
    request: ScoreArticleRequest,
    _user: dict = Depends(require_auth),
):
    from acl_agent.scoring import score_article
    from acl_agent.validation import count_h1, keyword_count, word_count

    article = request.article.strip()
    title = (request.title or request.keyword or "Untitled article").strip()
    if len(title) < 5:
        title = (title + " draft")[:200]
    keyword = (request.keyword or title).strip()[:200] or "article"
    if len(keyword) < 2:
        keyword = "article"
    words = word_count(article)
    brief = ContentBrief(
        primary_keyword=keyword[:200],
        title=title[:200],
        article_angle="Editor scoring of the current draft.",
        target_word_count=request.target_word_count
        or max(300, min(8000, words or 1500)),
        secondary_keywords=[
            KeywordTarget(phrase=item.strip()[:200], priority="secondary")
            for item in request.secondary_keywords
            if item and item.strip()
        ][:12],
    )
    meta_title = (request.meta_title or title)[:70]
    meta_description = (request.meta_description or "")[:320]
    if not meta_description:
        meta_description = re.sub(r"<[^>]+>", " ", article)[:160].strip()
    seo = SEOAnalysis(
        primary_keyword=brief.primary_keyword,
        meta_title=meta_title or title[:70],
        meta_description=meta_description or title,
        secondary_keywords=[
            item.strip() for item in request.secondary_keywords if item.strip()
        ][:12],
    )
    try:
        scores = score_article(article, brief, seo)
    except Exception as error:
        logger.exception("editor scoring failed")
        raise HTTPException(
            status_code=500,
            detail={"message": str(error)},
        ) from error
    return {
        "scores": scores,
        "stats": {
            "word_count": words,
            "h1_count": count_h1(article),
            "keyword_count": keyword_count(article, brief.primary_keyword),
        },
    }

