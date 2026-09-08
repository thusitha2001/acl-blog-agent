# Memory / Session Log — ACL Blog Agent

This file captures the full state, decisions, and history of the ACL Blog Agent
project. It is the single source of truth for the current state of the codebase,
the work completed, known issues, and next steps.

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
- Backend model: `meta-llama/Llama-3.1-8B-Instruct` on HuggingFace free
  inference API (fallback: same model if primary fails).
- Deployed publicly via **ngrok**.
- Hosted on **GitHub** (private repo — see section 8).

---

## 2. Features

1. **One-click generation** from a keyword (or full custom brief).
2. **No auth required** — generation endpoints are open (auth endpoints
   exist but are unused by the frontend).
3. **Custom target word count** (300–8000) that overrides preset sizes.
4. **Word limits** on Additional Instructions (150), Hook Brief (30), and
   Brand Voice (100), with live UI counters.
5. **Request-time scraping** of a user-provided website (in-memory only).
6. **SSE streaming** with 15-second keepalives (survives proxies like ngrok).
7. **"How Blog Agent Works" guide** modal.
8. **Dynamic progress tracker** — shows 5 stages normally, 6 when website
   URL is provided (adds "Scrape" stage).
9. **Custom brand voice** editor (tone, vocabulary, style notes, avoid list).
10. **Structure toggle chips** — tables, H3, lists, quotes, italics, bold.
11. Built-in **fact verification**, **heading-hierarchy** control, **Markdown**
    correctness, and **repetition** checks.

---

## 3. Recent Changes (this session)

### Frontend redesign
- Complete UI overhaul: new `app-shell` → `header` → `layout-grid` (input
  panel | resizable divider | output panel) → `footer`.
- Form organized into labeled sections: Content, Writing Settings, Structure,
  Hook, Brand, Additional Instructions.
- New toggle chip buttons for formatting options (Tables, H3, Lists, Quotes,
  Italics, Bold).
- Switch toggles for FAQ, Takeaways, Conclusion.
- Brand voice editor with tone, vocabulary, style notes, and avoid fields.
- Guide modal explaining the 6-step pipeline.
- Dynamic progress tracker (5 or 6 stages based on website URL).
- Resizable input/output panels via drag divider.
- Fonts: Space Grotesk (display), DM Sans (body), JetBrains Mono (mono).
- Warm ivory + teal/rust/amber color palette with gradient backgrounds.

### Auth removal
- Removed `Depends(require_auth)` from `/generate-1click` and
  `/generate-1click-stream` in `api.py`.
- Removed `user_id` from generation payloads (set to `None`).
- Auth endpoints (`/auth/signup`, `/auth/login`, `/auth/me`) still exist
  but are unused by the frontend.
- Removed all auth UI, token handling, and login/signup logic from frontend.

### Model switch
- `.env` `MODEL` changed from `zai-org/GLM-4.6` to
  `meta-llama/Llama-3.1-8B-Instruct`.
- Reason: smaller model = faster generation on HF free tier.

### Generation reliability fixes
- `llm.py` `parse_json_object()`: all `json.loads()` calls now use
  `strict=False` to accept literal newlines in JSON strings (model outputs
  real `\n` instead of escaped `\\n`).
- `generation.py`: `max_tokens` increased from 9000 → 16000 to ensure full
  article + JSON fits without truncation.
- `generation.py`: `schema_retries` increased from 0 → 1 so the model gets
  a second chance when validation fails (self-correction via feedback loop).

---

## 4. Architecture

### Directory layout
```
backend/
  app.py                  # entry point (python app.py <cmd> | uvicorn app:app)
  requirements.txt
  acl_agent/
    api.py                # FastAPI app: SSE endpoints, keepalive (no auth on gen)
    auth.py               # user accounts (signup/login/token) — unused by frontend
    auto_brief.py         # SERP analysis + brief generation (SIZE_MAP)
    cli.py                # ingest / generate / quick / validate / server
    config.py             # env vars, paths, constants
    generation.py         # single-call prompt, generate_single_call_article, extra_validate
    knowledge_base.py     # FAISS + BM25 + reranker hybrid retrieval
    llm.py                # model clients, JSON parsing/repair, retry logic
    models.py             # ContentBrief, SingleCallArticle, SEOAnalysis, etc.
    pipeline_1click.py    # generate_1click / generate_full_pipeline orchestration
    scraping.py           # fetch_url, scrape_blog_list/content, scrape_url_for_request, chunk_text
    validation.py         # word_count, count_h1, keyword_count, validate_internal_links, etc.
frontend/
  index.html              # redesigned form + guide modal (no auth UI)
  app.js                  # SSE reader, word counters, guide, dynamic tracker
  styles.css              # full CSS matching new HTML class names
.env                      # gitignored (HF_API_KEY, MODEL, etc.)
.gitignore
memory.md                 # this file
```

### Flow — `generate-1click-stream`
1. SSE stream starts; `stage` events emitted progressively.
2. `analyze_serp` → competitor data.
3. `auto_generate_brief` → `ContentBrief`.
4. Request-time scrape of user Website (if provided) → extra context.
5. `generate_single_call_article` → article Markdown + SEO metadata
   (single model call with 1 retry; validation via `extra_validate`).
6. `result` event with article + SEO + validation; keepalives each 15 s.

---

## 5. git / GitHub

- **Repo:** `https://github.com/thusitha2001/acl-blog-agent` (PRIVATE, branch
  `main`).
- Protected by `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `*.pyc`,
  `data/`, `backend/data/`, `output/`, `backend/output/`.
- The HF API key in `.env` is gitignored and has NOT been pushed.

### Recent commits
```
72f8866  Redesign frontend, remove auth, fix generation reliability
20fe...  Word limits + target words + guide
20cefb9  Simple user accounts (auth)
f4c9995  Fix validation bugs
88307c0  Request-time auto-scrape
```

---

## 6. Running / Verification

### Start the backend
```powershell
# From backend/
& "..\.venv\Scripts\python.exe" app.py server
```
Health check: `GET http://localhost:8001/health`
→ `{"status":"ok","knowledge_base_loaded":true,"knowledge_chunks":202}`.

### Verified
- Backend healthy on :8001 (202 KB chunks).
- Frontend serves at `http://localhost:8001` (no login required).
- Streaming (`/generate-1click-stream`) accepts requests without auth.
- SSE events flow correctly through SERP → Brief → Draft → SEO → Validate.
- CSS, JS, HTML all serve with correct content types.

---

## 7. Known Issues / Limitations

- **HF free API** rate limits (~1–2 req/min per IP) → only ~1 user can
  generate at a time; this is the barrier to true concurrent/multi-user use.
- **Llama-3.1-8B** on HF free may occasionally produce invalid JSON
  (mitigated by `schema_retries=1` and `strict=False` parsing).
- **Biggest recommended fix:** switch to a parallel-capable provider
  (**Groq / OpenAI / Gemini**) — would cut generation time to ~30–60 s and
  enable multi-user. Requires a provider API key (not yet obtained).

---

## 8. Next Steps

- [ ] Switch generation to Groq/OpenAI/Gemini (needs user API key) for
      speed + reliability + true multi-user.
- [ ] Rotate the ngrok authtoken (was shared in chat).
- [ ] Optionally add a custom "target words" override to the CLI `quick`
      command (frontend + API already support it).

---

## 9. Environment Notes

- Developer environment is **Windows** (PowerShell 5.1, `win32`).
- Terminal quirks: PowerShell does not support `&&`; use `;` / `if ($?)`.
- Paths with spaces or parentheses require the call operator
  `& "path with spaces"`.
