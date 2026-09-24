"""Validate competitor-analysis inputs and derive SERP query + averages."""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
APP_PATHS = {
    "",
    "/",
    "/competitors",
    "/writer",
    "/rewriter",
    "/editor",
    "/login",
    "/settings",
    "/dashboard",
    "/health",
}
INVALID_BLOG_URL_MESSAGE = (
    "Please enter a valid public article URL. "
    "The current value is the local Competitor Analysis page, not an article URL."
)
_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "your", "our",
    "are", "was", "were", "a", "an", "of", "to", "in", "on", "best",
    "how", "complete", "guide", "blog", "news", "post",
}


def _norm_path(path: str) -> str:
    cleaned = (path or "/").rstrip("/") or "/"
    return cleaned.lower()


def is_local_app_url(url: str, current_origin: str = "") -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    try:
        parsed = urlparse(raw if re.match(r"^https?://", raw, re.I) else "http://" + raw)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    path = _norm_path(parsed.path)
    if path in APP_PATHS and (host in LOCAL_HOSTS or not host):
        return True
    if current_origin:
        try:
            origin = urlparse(current_origin)
            if (parsed.hostname or "").lower() == (origin.hostname or "").lower() and path in APP_PATHS:
                return True
        except Exception:
            pass
    return False


def validate_blog_url(
    url: Optional[str],
    current_origin: str = "",
) -> dict[str, Any]:
    raw = (url or "").strip()
    if not raw:
        return {"ok": False, "status": "missing", "url": None, "error": None}
    if raw in {"#", "/competitors", "/competitors#"} or raw.endswith("/competitors#"):
        return {
            "ok": False,
            "status": "invalid",
            "url": raw,
            "error": INVALID_BLOG_URL_MESSAGE,
        }
    if not re.match(r"^https?://", raw, flags=re.I):
        return {
            "ok": False,
            "status": "invalid",
            "url": raw,
            "error": INVALID_BLOG_URL_MESSAGE,
        }
    try:
        parsed = urlparse(raw)
    except Exception:
        return {
            "ok": False,
            "status": "invalid",
            "url": raw,
            "error": INVALID_BLOG_URL_MESSAGE,
        }
    host = (parsed.hostname or "").strip()
    path = _norm_path(parsed.path)
    if not host or "." not in host and host not in LOCAL_HOSTS:
        return {
            "ok": False,
            "status": "invalid",
            "url": raw,
            "error": INVALID_BLOG_URL_MESSAGE,
        }
    if is_local_app_url(raw, current_origin):
        return {
            "ok": False,
            "status": "invalid",
            "url": raw,
            "error": INVALID_BLOG_URL_MESSAGE,
        }
    if path == "/" and (not parsed.fragment) and raw.rstrip("#").count("/") <= 2:
        # root homepage can still be an article hub; allow it
        pass
    if raw.rstrip("/").endswith("#") and path in APP_PATHS:
        return {
            "ok": False,
            "status": "invalid",
            "url": raw,
            "error": INVALID_BLOG_URL_MESSAGE,
        }
    return {"ok": True, "status": "valid", "url": raw, "error": None}


def analysis_mode(blog_url: Optional[str], keyword: Optional[str]) -> str:
    has_blog = bool((blog_url or "").strip())
    has_kw = bool((keyword or "").strip())
    if has_blog and has_kw:
        return "blog_and_keyword"
    if has_blog:
        return "blog_auto_detected"
    return "keyword_only"


def _slug_phrase(url: str) -> str:
    path = urlparse(url or "").path.rstrip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", path)
    tokens = [
        token.lower()
        for token in re.findall(r"[a-z0-9]+", slug)
        if len(token) > 2 and token.lower() not in _STOP
    ]
    if len(tokens) >= 2:
        return " ".join(tokens[:6])
    return ""


def _phrase(text: str) -> str:
    raw = re.split(r"\s*[:|\u2013\u2014]\s*", (text or "").strip())[0]
    raw = re.sub(
        r"^(how to|the complete|ultimate|a complete|complete|best)\s+",
        "",
        raw,
        flags=re.I,
    )
    words = [w for w in re.findall(r"[A-Za-z0-9']+", raw) if w.lower() not in _STOP]
    if len(words) >= 2:
        return " ".join(words[:7]).lower()
    return ""


def _repeated_phrases(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9']{3,}", (text or "").lower()) if w not in _STOP]
    counts: dict[str, int] = {}
    for size in (2, 3):
        for index in range(len(words) - size + 1):
            phrase = " ".join(words[index:index + size])
            counts[phrase] = counts.get(phrase, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], -len(item[0].split()), item[0]))
    for phrase, freq in ranked:
        if freq >= 3 and len(phrase) >= 8:
            return phrase
    return ""


def detect_keyword_from_article(page: dict[str, Any]) -> dict[str, Any]:
    title = (page.get("title") or "").strip()
    h1 = (page.get("h1") or "").strip()
    meta = (page.get("meta_description") or "").strip()
    h2s = page.get("h2_headings") or []
    text = page.get("full_text") or page.get("text") or page.get("source_markdown") or ""
    opening = " ".join((text or "").split())[:600]
    url = page.get("url") or ""
    evidence: list[str] = []
    title_tokens = set(re.findall(r"[a-z0-9]+", f"{title} {h1} {meta}".lower()))
    slug = _slug_phrase(url)
    slug_tokens = set(slug.split())
    if slug and len(slug_tokens & title_tokens) >= 2:
        evidence.append(f"URL slug overlaps title/H1: {slug}")
        return {"keyword": slug[:80], "evidence": evidence}
    for source, label in ((h1, "H1"), (title, "title"), (meta, "meta description")):
        phrase = _phrase(source)
        if phrase:
            evidence.append(f"{label}: {phrase}")
            return {"keyword": phrase[:80], "evidence": evidence}
    for heading in h2s[:8]:
        phrase = _phrase(heading)
        if phrase:
            evidence.append(f"H2: {phrase}")
            return {"keyword": phrase[:80], "evidence": evidence}
    repeated = _repeated_phrases(f"{title} {h1} {opening}")
    if repeated:
        evidence.append(f"repeated phrase in opening: {repeated}")
        return {"keyword": repeated[:80], "evidence": evidence}
    fallback = _phrase(title or h1 or opening) or "blog article"
    evidence.append("fallback from title/opening")
    return {"keyword": fallback[:80], "evidence": evidence}


def _numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def average_competitor_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("seo", "geo", "aeo", "aio", "sxo", "overall")
    counted: dict[str, int] = {}
    avgs: dict[str, Any] = {}
    reasons: dict[str, Optional[str]] = {}
    total = len(rows or [])
    for key in keys:
        vals = []
        for row in rows or []:
            num = _numeric((row.get("scores") or {}).get(key))
            if num is not None:
                vals.append(num)
        counted[key] = len(vals)
        if vals:
            avgs[key] = round(sum(vals) / len(vals), 1)
            reasons[key] = None
        else:
            avgs[key] = None
            reasons[key] = f"Data unavailable — no {key.upper()} values returned"
    scored = max((counted.get(key, 0) for key in ("seo", "geo", "aeo")), default=0)
    return {
        **avgs,
        "counted": counted,
        "reasons": reasons,
        "sample_size": total,
        "sample_note": (
            f"Based on {scored} of {total} competitors" if total else "No competitors"
        ),
    }


def empty_section(reason: str) -> dict[str, Any]:
    return {"items": [], "table": [], "status": "unavailable", "reason": reason}


def page_full_text(page: Optional[dict[str, Any]]) -> str:
    if not page:
        return ""
    return (
        (page.get("full_text") or "")
        or (page.get("source_markdown") or "")
        or (page.get("text") or "")
        or (page.get("article_html") or "")
    ).strip()
