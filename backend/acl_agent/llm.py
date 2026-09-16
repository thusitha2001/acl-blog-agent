"""
ACL Blog Agent - model call helpers.

Wraps the configured chat client (OpenAI or Hugging Face) with retry
logic, JSON parsing/repair, and schema+content validation retries.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Optional, TypeVar

from pydantic import BaseModel, ValidationError

from acl_agent.config import LLM_PROVIDER, MODEL, client, logger

T = TypeVar("T", bound=BaseModel)

FALLBACK_MODEL = (
    "gpt-4o-mini"
    if LLM_PROVIDER == "openai"
    else "meta-llama/Llama-3.1-8B-Instruct"
)


def _repair_json(text: str) -> str:
    """Best-effort repair of common model JSON mistakes."""
    fixed = text
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    fixed = fixed.replace('\t', '\\t')
    return fixed


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        cleaned,
        flags=re.DOTALL,
    )

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    try:
        return json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError(
            "Model did not return a valid JSON object."
        )

    candidate = cleaned[start:end + 1]

    try:
        return json.loads(candidate, strict=False)
    except json.JSONDecodeError:
        pass

    repaired = _repair_json(candidate)
    try:
        return json.loads(repaired, strict=False)
    except json.JSONDecodeError:
        pass

    for i in range(len(repaired) - 1, 0, -1):
        if repaired[i] == "}":
            try:
                return json.loads(repaired[:i + 1], strict=False)
            except json.JSONDecodeError:
                continue

    raise ValueError(
        "Model did not return a valid JSON object."
    )


def parse_model_json(
    text: str,
    model_type: type[T],
) -> T:
    payload = parse_json_object(text)
    return model_type.model_validate(payload)


def call_model_for_json(
    system_prompt: str,
    user_prompt: str,
    model_type: type[T],
    temperature: float = 0.5,
    max_tokens: int = 2500,
    schema_retries: int = 2,
    extra_validate: Optional[Callable[[T], Optional[str]]] = None,
) -> T:
    """
    Calls the model and validates the JSON response against model_type.

    If the response doesn't match the schema (wrong field names, missing
    keys, extra wrapper object, etc.), feeds the validation error back to
    the model and asks it to correct itself, up to schema_retries times.

    extra_validate, if given, is called with the parsed object after
    schema validation succeeds. It should return None if the object is
    acceptable, or a short string describing what's wrong (e.g. "the
    article is only 640 words; expand it to at least 900") to trigger
    another retry with that feedback appended to the prompt.
    """
    current_user_prompt = user_prompt
    last_error: Optional[Exception] = None

    for attempt in range(schema_retries + 1):
        raw = call_model(
            system_prompt,
            current_user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            parsed = parse_model_json(raw, model_type)
        except (ValueError, ValidationError) as error:
            last_error = error

            logger.warning(
                "Schema validation failed (attempt %s/%s): %s",
                attempt + 1,
                schema_retries + 1,
                error,
            )

            current_user_prompt = (
                user_prompt
                + "\n\n--- YOUR PREVIOUS RESPONSE (START) ---\n"
                + raw
                + "\n--- YOUR PREVIOUS RESPONSE (END) ---\n\n"
                "That response did not match the required JSON "
                "schema. Here are the validation errors:\n"
                f"{error}\n\n"
                "Fix that draft's structure - keep its content, "
                "correct only the schema problems. Return ONLY "
                "corrected valid JSON matching the exact field names "
                "shown in the example above. Do not wrap it in an "
                "outer key. Do not add commentary, markdown fences, "
                "or explanation - JSON only."
            )
            continue

        if extra_validate is not None:
            issue = extra_validate(parsed)

            if issue:
                last_error = RuntimeError(issue)

                logger.warning(
                    "Content check failed (attempt %s/%s): %s",
                    attempt + 1,
                    schema_retries + 1,
                    issue,
                )

                current_user_prompt = (
                    user_prompt
                    + "\n\n--- YOUR PREVIOUS RESPONSE (START) ---\n"
                    + raw
                    + "\n--- YOUR PREVIOUS RESPONSE (END) ---\n\n"
                    f"That response had an issue: {issue}\n\n"
                    "Revise THAT draft to fix the issue - expand, "
                    "trim, or add the missing elements directly into "
                    "the existing sections - while keeping everything "
                    "that was already correct about it. Do not start "
                    "over from scratch. Return the complete corrected "
                    "JSON, in the same schema as before. JSON only, "
                    "no commentary."
                )
                continue

        return parsed

    raise RuntimeError(
        f"Model did not return an acceptable response after "
        f"{schema_retries + 1} attempts: {last_error}"
    )


def is_retryable_error(error: Exception) -> bool:
    error_text = str(error).lower()

    retry_markers = [
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "rate limit",
        "empty content",
        "no choices",
        "429",
        "503",
        "502",
        "504",
    ]

    if LLM_PROVIDER == "huggingface":
        # HF Inference Providers can return a bare, detail-free 400
        # when the router lands a request on a provider that's at
        # capacity rather than a clean 429.
        retry_markers.extend(["bad request", "400"])

    return any(
        marker in error_text
        for marker in retry_markers
    )


def call_model(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.6,
    max_tokens: int = 3000,
    retries: int = 3,
) -> str:
    last_error: Optional[Exception] = None
    models_to_try = [MODEL]
    if FALLBACK_MODEL != MODEL:
        models_to_try.append(FALLBACK_MODEL)

    for model_name in models_to_try:
        for attempt in range(retries):
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt,
                        },
                        {
                            "role": "user",
                            "content": user_prompt,
                        },
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                if not response.choices:
                    raise RuntimeError(
                        "Model returned no choices."
                    )

                content = response.choices[0].message.content

                if not content:
                    raise RuntimeError(
                        "Model returned empty content."
                    )

                content = re.sub(
                    r"<think>.*?</think>",
                    "",
                    content,
                    flags=re.DOTALL,
                ).strip()

                if not content:
                    raise RuntimeError(
                        "Model returned empty content after stripping thinking tags."
                    )

                return content

            except Exception as error:
                last_error = error

                logger.warning(
                    "Model %s attempt %s failed: %s",
                    model_name,
                    attempt + 1,
                    error,
                )

                if (
                    attempt >= retries - 1
                    or not is_retryable_error(error)
                ):
                    break

                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"Model call failed after all models: {last_error}"
    )
