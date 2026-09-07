"""
ACL Blog Agent - FastAPI application: lifespan and HTTP endpoints.
"""
from __future__ import annotations

import asyncio
import json
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
from acl_agent.auth import login_user, signup_user, verify_token
from acl_agent.config import (
    ALLOWED_ORIGINS,
    CORS_ALLOW_CREDENTIALS,
    ROOT_DIR,
    logger,
)
from acl_agent.knowledge_base import load_knowledge_base
from acl_agent.models import ContentBrief
from acl_agent.pipeline_1click import generate_1click, generate_full_pipeline


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
    return FileResponse(str(FRONTEND_DIR / "index.html"))


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
        default=True,
        description="Use bold for emphasis",
    )
    additional_instructions: str = Field(
        default="",
        max_length=1000,
        description="Additional instructions (max 150 words)",
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


@app.post("/generate-1click")
def generate_1click_endpoint(
    request: OneClickRequest,
    user: dict = Depends(require_auth),
):
    request_id = str(uuid.uuid4())

    try:
        result = generate_1click(
            keyword=request.keyword,
            title=request.title,
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
            user_id=user["user_id"],
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
        )

        result["request_id"] = request_id
        result["user_id"] = user["user_id"]
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
    user: dict = Depends(require_auth),
):
    request_id = str(uuid.uuid4())
    queue: "asyncio.Queue[tuple[str, dict]]" = asyncio.Queue()
    worker_loop: "asyncio.AbstractEventLoop | None" = None
    loop_lock = asyncio.Lock()

    async def event_stream():
        nonlocal worker_loop

        def emit(event_type: str, data: dict) -> None:
            data["request_id"] = request_id
            data["user_id"] = user["user_id"]
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
                    user_id=user["user_id"],
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
                    on_event=lambda evt, data: emit(evt, data),
                )
                try:
                    result = await asyncio.to_thread(run_func)
                except Exception as error:
                    logger.exception("stream generation failed")
                    await queue.put(("error", {
                        "message": str(error),
                        "request_id": request_id,
                        "user_id": user["user_id"],
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
