# Memory / Session Log — ACL Blog Agent

This file captures the full state, decisions, and history of the ACL Blog Agent
project as of this session. It is the single source of truth for the current
state of the codebase, the work completed, known issues, and next steps.

---

## 1. Project Summary

A SEO blog article generator ("ACL Blog Agent") built with FastAPI:

- **SERP analysis** → auto content-brief → **request-time scraping** →
  **single-call article generation** (ML model) → **SEO metadata** →
  **quality validation**.
- Output is a full Markdown article plus meta title, meta description, FAQs,
  and image alt text, streamed progressively to the browser over SSE.

### Key facts
- Working project path: `E:\acl2\acl-blog-agent (3)\acl-blog-agent`
- Virtualenv built with **Python 3.12.10**; venv python:
  `E:\acl2\acl-blog-agent (3)\acl-blog-agent\.venv\Scripts\python.exe`
- Structure: root holds `.env`, `frontend/`, `backend/`. Backend serves the
  frontend and the API on a single port **8001**.
- `frontend/app.js` uses `API_BASE = ""` (relative paths) → ngrok-friendly.
- Backend model: `zai-org/GLM-4.6` on the Hugging Face free inference API
  (fallback: `meta-llama/Llama-3.1-8B-Instruct`).
- Deployed publicly via **ngrok**.
- Hosted on **GitHub** (private repo — see section 8).

---

## 2. FAQ / Direct Answers (this session)

### Does a new URL trigger a fresh web scrape each time? Where is it stored?
- **Previously:** No. Scraping only happened via the manual `ingest` command;
  generation just read the pre-built index.
- **Now (implemented):** Yes — if a user submits a URL in the **Website**
  field on a generation request, it is scraped fresh at request time.
- **Persistent knowledge base:** lives in `backend/data/`
  (`knowledge.index`, `bm25_index.pkl`, `knowledge_chunks.json`,
  `ingestion_manifest.json`) — built once via `ingest`, reused for all
  requests.
- **Request-time scrapes:** go only to **memory for that single request** —
  never written to `data/`, never merged into the global index.
- **Storage summary:** pre-ingested content is **permanent**; user-submitted
  URLs are **temporary** (used for that one article, then discarded).

### Why is the login not showing?
- There was **no login feature** originally — the app went straight to the
  generation form. Simple user accounts (signup/login) were subsequently
  implemented (feature below).

---

## 3. Features Added in This Session (in order)

1. **5 quality-improvement fixes** (see section 4).
2. **SSE keepalive** — ping every 15 s of silence to prevent ngrok/browser
   connection drops.
3. **Request-time auto-scrape** — scrape user-provided URLs fresh per request
   (in-memory only).
4. **`user_id` tracking** — optional user identifier on every request.
5. **Simple user accounts** (signup/login), protecting the API.
6. **Word limits** on Additional Instructions / Hook Brief / Brand Voice.
7. **Custom target words** (300–8000) overriding preset article sizes.
8. **"How Blog Agent Works" guide** modal.

---

## 4. The 5 Quality FIXES Implemented

| # | Fix | Where | What it does |
|---|-----|-------|--------------|
| 1 | **Prevent hallucinated internal links** | `auto_brief.py` prompt | Only use URLs from the brand website (`BRAND_SITE`); return `[]` if none found. |
| 2 | **Fix Markdown rendering** | `generation.py` system prompt + `extra_validate` | Lists MUST use `-`/`*`, tables MUST use `\|` pipe syntax. HTML tags rejected. |
| 3 | **Heading hierarchy** | `generation.py` system prompt + `extra_validate` | H3 (`###`) forbidden unless H3 is explicitly requested in `additional_instructions`. |
| 4 | **Fact verification** | `generation.py` system prompt + `extra_validate` | Blocks unsupported historical/pricing/rarity/mining claims; only facts in VERIFIED FACTS/product_facts allowed. |
| 5 | **Reduce repetition** | `generation.py` `extra_validate` | Flags keyword appearing too often in a single section (limit = 3 + 1 per 40 section words). |

Plus an **SSE keepalive** in `api.py`: sends `: keepalive\n\n` every 15 s of
silence to keep long generations from dropping through ngrok.

---

## 5. Request-Time Auto-Scrape (feature)

| File | Change |
|------|--------|
| `scraping.py` | New `scrape_url_for_request(url)`: fresh in-memory scrape of the user URL; follows up to 2 `/blogs/` links; returns concatenated content or `""`. |
| `pipeline_1click.py` | `generate_full_pipeline()` accepts `extra_style_context` / `extra_fact_context` (prepended to KB retrieval). `generate_1click()` scrapes when `website` is explicitly provided. |
| `frontend/app.js` | Added a `Scrape` step to the progress tracker. |

Design decision: scraping fires **only** when the user fills the **Website**
field, **not** when it just falls back to `BRAND_SITE` from `.env`.

---

## 6. User Accounts / Auth (feature)

- New module `backend/acl_agent/auth.py`:
  - Users stored in `backend/data/users.json` (gitignored).
  - Passwords hashed with **PBKDF2** (salt + hash), never plaintext.
  - Opaque bearer tokens per session.
- Endpoints:
  - `POST /auth/signup`
  - `POST /auth/login`
  - `GET /auth/me`
- Generation endpoints now require `Authorization: Bearer <token>`; 401
  without it.
- `user_id` in generation comes from the authenticated session (server-side),
  not the request body.
- Frontend: login/signup panel gate, token in `localStorage`, auto-fills the
  User ID field, session-expiry handling (returns to login on 401).
- Test account currently in `users.json`: **Alice / secret123**.
  To reset, delete `backend\data\users.json`.

---

## 7. Word Limits + Target Words + Guide (feature)

### Word limits (validated server-side → 422, plus live UI counters)
- **Additional Instructions** → 150 words (UI: `0/150 words`)
- **Opening Hook Brief** → 30 words (UI: `0/30 words`)
- **Brand Voice / Style Notes** → 100 words overall, 60 for type notes
  (UI counters)

### Custom target words
- New **Target Words** number input (min 300, max 8000) that **overrides**
  the preset Article Size when filled.
- Sent as `target_word_count`; threaded `api → generate_1click →
  auto_generate_brief`; clamped server-side to `300–8000`.
- `SIZE_MAP` in `auto_brief.py`: `x-small=600, small=900, medium=1750,
  large=2400, x-large=3600`.

### "How Blog Agent Works" guide
- `? How Blog Agent Works` button in the masthead opens a modal.
- Explains the 6-step pipeline: keyword → SERP analysis → auto brief →
  research grounding → single-call generation → validation.
- Closes via ✕, backdrop click, or Escape.

---

## 8. git / GitHub

- **Repo:** `https://github.com/thusitha2001/acl-blog-agent` (PRIVATE, branch
  `main`).
- Protected by `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `*.pyc`,
  `data/`, `backend/data/`, `output/`, `backend/output/`.
- The HF API key in `.env` is gitignored and has NOT been pushed.

### Recent commit history (this session)
```
20fe... (8a4cf67) Word limits + target words + guide
20cefb9            Simple user accounts (auth)
f4c9995            Fix validation bugs
88307c0            Request-time auto-scrape
...                (earlier quality fixes + initial commit c00ded6)
```

### Manual push reminder
If changes are made locally after this session, they need:
```
git add <files>
git commit -m "..."
git push origin main
```

---

## 9. ngrok

- Installed v3.39.9-msix-stable.
- Active public URL (while running): `https://speech-family-rise.ngrok-free.dev`
  → `http://localhost:8001`.
- ⚠️ **Security note:** the ngrok authtoken was shared in chat. Recommended to
  rotate it in the ngrok dashboard.

---

## 10. Running / Verification

### Start the backend
```
& "E:\acl2\acl-blog-agent (3)\acl-blog-agent\.venv\Scripts\python.exe" app.py server
```
(working directory: `backend`). Health check: `GET http://localhost:8001/health`
→ `{"status":"ok","knowledge_base_loaded":true,"knowledge_chunks":202}`.

### Verified in this session
- Backend healthy on :8001 (202 KB chunks).
- ngrok tunnel active → public URL forwards.
- Streaming (`/generate-1click-stream`) sends ordered SSE chunks with
  keepalives every 15 s and completes with a `result` event.
- Auth: signup / login / wrong-password(401) / duplicate(409) /
  no-token(401) all correct, including via the public ngrok URL.
- Word limits: oversized fields → 422.
- Target word clamp: `100→300`, `9000→8000`; out-of-range → 422.

---

## 11. Architecture (for reference)

### Directory layout
```
backend/
  app.py                  # entry point (python app.py <cmd> | uvicorn app:app)
  requirements.txt
  acl_agent/
    api.py               # FastAPI app: SWEENT auth + SSE endpoints, keepalive
    auth.py              # signup/login/verify
    auto_brief.py        # SERP analysis + brief generation (SIZE_MAP)
    cli.py               # ingest / generate / quick / validate / server
    config.py            # env vars, paths, constants
    generation.py        # single-call system prompt, generate_single_call_article, extra_validate
    knowledge_base.py    # FAISS + BM25 + reranker hybrid retrieval
    llm.py               # model clients (HF fallback)
    models.py            # ContentBrief, SingleCallArticle, SEOAnalysis, etc.
    pipeline_1click.py   # generate_1click / generate_full_pipeline orchestration
    scraping.py          # fetch_url, scrape_blog_list/content, scrape_url_for_request, chunk_text
    validation.py        # word_count, count_h1, keyword_count, validate_internal_links, etc.
frontend/
  index.html             # form + auth panel + guide modal
  app.js                  # SSE reader, auth, word counters, guide, tracker
  styles.css
.env                      # gitignored (HF_API_KEY, MODEL, etc.)
.gitignore
```

### Flow — `generate-1click-stream`
1. Auth gate (Bearer token).
2. SSE stream starts; `stage` events emitted progressively.
3. `analyze_serp` → competitor data.
4. `auto_generate_brief` → `ContentBrief`.
5. Request-time scrape of user Website (if provided) → extra context.
6. `generate_single_call_article` → article Markdown + SEO metadata
   (single model call; retries, validation via `extra_validate`).
7. `result` event with article + SEO + validation; keepalives each 15 s.

---

## 12. Known Issues / Limitations

- **HF free API** rate limits (~1–2 req/min per IP) → only ~1 user can
  generate at a time; this is the barrier to true concurrent/multi-user use.
- **GLM-4.6** often returns empty/invalid JSON → sporadic `500`s on
  generation (validation passes, model itself errors).
- **Biggest recommended fix:** switch to a parallel-capable provider
  (**Groq / OpenAI / Gemini**) — would cut generation time to ~30–60 s and
  enable multi-user. Requires a provider API key (not yet obtained).

---

## 13. Next Steps / Open Items

- [ ] Switch generation to Groq/OpenAI/Gemini (needs user API key) for
      speed + reliability + true multi-user.
- [ ] Rotate the ngrok authtoken (was shared in chat).
- [ ] Optionally add a custom "target words" override to the CLI `quick`
      command (frontend + API already support it).
- [ ] Reset/remove the demo `Alice` test account before real deployment.

---

## 14. Conversation Context Notes

- User is Tamil-speaking; some of the conversation was answered in Tamil.
- Developer environment is **Windows** (PowerShell 5.1, `win32`).
- Terminal quirks: PowerShell does not support `&&`; use `;` / `if ($?)`.
- Paths with spaces or parentheses require the call operator
  `& "path with spaces"`.
