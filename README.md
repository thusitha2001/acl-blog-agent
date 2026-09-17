# ACL Blog Agent

An SEO blog article generator. Enter one keyword and it produces a complete,
publish-ready article with SEO metadata — automatically:

1. **SERP analysis** of the keyword's real search results (competitor topics,
   headings, related queries).
2. **Auto content brief** (title, target words, topics, secondary keywords,
   formatting choices).
3. **Request-time research grounding** — optionally scrapes a user-supplied
   brand website for that article only.
4. **Single-call article generation** in Markdown, plus meta title, meta
   description, FAQs, and image alt text.
5. **Quality validation** (word count, headings, Markdown, facts, repetition,
   originality).

Output streams progressively to the browser over SSE so you watch it happen.

---

## Features

- **One-click generation** from just a keyword (or full custom brief).
- **No auth required** — open generation endpoints.
- **Custom target word count** (300–8000) that overrides preset sizes.
- **Word limits** on Additional Instructions (150), Hook Brief (30), and
  Brand Voice (100), with live UI counters.
- **Request-time scraping** of a user-provided website (in-memory only).
- **SSE streaming** with 15-second keepalives (survives proxies like ngrok).
- **"How Blog Agent Works" guide** — in-app modal explaining the pipeline.
- **Dynamic progress tracker** — shows 5 or 6 stages based on whether a
  website URL is provided.
- **Custom brand voice** editor (tone, vocabulary, style notes, avoid list).
- **Structure toggle chips** — tables, H3, lists, quotes, italics, bold.
- Built-in **fact verification**, **heading-hierarchy** control, **Markdown**
  correctness, and **repetition** checks.

---

## Tech Stack

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, Uvicorn
- **Generation / retrieval:** Hugging Face free inference API (Llama-3.1-8B),
  Sentence Transformers, FAISS + BM25 hybrid search with a cross-encoder
  reranker
- **Scraping:** BeautifulSoup (`bs4`) + requests
- **Frontend:** vanilla HTML/CSS/JS (no build step), SSE consumption

---

## Requirements

- Python **3.12.x** (the venv used here was built with 3.12.10)
- A Hugging Face API key
- See `backend/requirements.txt` for full package list.

---

## Setup

1. **Create and activate a virtualenv** (from the project root, where
   `backend/` and `frontend/` live):

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1      # PowerShell
   ```

2. **Install dependencies:**

   ```powershell
   pip install -r backend\requirements.txt
   ```

3. **Create `.env`** in the project root (copy the keys, fill in values).
   See [Environment variables](#environment-variables) below.

4. **(Optional) Build the knowledge base** from your blog URLs so articles
   are grounded on your own content:

   ```powershell
   .\.venv\Scripts\python.exe app.py ingest --blog-url <BLOG_URL>
   ```
   (working directory: `backend`)

---

## Running the app

### Start the web server (serves frontend + API on port 8001)

```powershell
# from backend/
& "..\.venv\Scripts\python.exe" app.py server
```

Then open http://localhost:8001 in a browser. Enter a keyword and click
Generate — no login required.

Health check:

```
GET http://localhost:8001/health
# {"status":"ok","knowledge_base_loaded":true,"knowledge_chunks":202}
```

### Expose publicly with ngrok

```powershell
ngrok http 8001
```

---

## CLI commands

From the `backend/` directory:

| Command | Description |
|---------|-------------|
| `python app.py ingest` | Build/rebuild the knowledge base from `BLOG_URL` or a CSV of URLs. |
| `python app.py generate <brief.json>` | Generate an article from a full `ContentBrief` JSON file. |
| `python app.py quick "<keyword>"` | One-click generation from a keyword. |
| `python app.py validate <article.json>` | Validate an existing article JSON. |
| `python app.py server` | Start the FastAPI server (frontend + API). |

Server startup honors `HOST`, `PORT`, and `RELOAD` env vars, plus a
`--reload` flag.

Example `quick`:

```powershell
python app.py quick "how to choose linen table runners" --size medium
```

---

## API endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/generate-1click` | – | Non-streaming full generation. |
| POST | `/generate-1click-stream` | – | SSE-streamed generation (recommended). |
| GET | `/health` | – | Health / KB status. |
| POST | `/auth/signup` | – | Create an account (unused by frontend). |
| POST | `/auth/login` | – | Log in (unused by frontend). |
| GET | `/auth/me` | Bearer | Return the current user (unused by frontend). |

### `OneClickRequest` main fields

| Field | Notes |
|-------|-------|
| `keyword` | Required (2–200 chars). |
| `title` | Optional (auto-generated from SERP if empty). |
| `size` | `x-small/small/medium/large/x-large`. |
| `target_word_count` | Optional exact word count (300–8000), overrides `size`. |
| `article_type` | `how-to, listicle, review, news, comparison, ...` |
| `tone` | `friendly, professional, informational, ...` |
| `point_of_view` | `first-singular, first-plural, second, third`. |
| `readability` | `5th, 6th, 7th, 8th-9th, college, ...` |
| `brand_name` / `website` | Brand override + website to scrape at request time. |
| `brand_voice` | Max **100 words**. |
| `hook_type` | `question, statistic, fact, anecdote`. |
| `hook_brief` | Max **30 words**. |
| `additional_instructions` | Max **500 words** (and 4000 chars). |
| `include_faq/_takeaways/_conclusion` | Toggle sections on/off. |
| `include_tables/_h3/_lists/_quotes/_italics/_bold` | Structure toggles. |

---

## Environment variables

Create a `.env` in the project root. Key variables:

| Variable | Purpose |
|----------|---------|
| `HF_API_KEY` | Hugging Face API key for model inference. **Do not commit.** |
| `MODEL` | Generation model (default: `meta-llama/Llama-3.1-8B-Instruct`). |
| `BRAND_NAME` | Default brand name. |
| `BRAND_SITE` | Default brand website (used for internal-link grounding). |
| `BLOG_URL` | Blog listing URL used by `ingest`. |
| `BLOG_KB_LIMIT` | Max blog URLs to ingest (default 50). |
| `EMBEDDING_MODEL` | Sentence-Transformer model for retrieval. |
| `GENERATION_MODE` | Single-call generation mode. |
| `WORD_COUNT_TOLERANCE` | Allowed drift fraction from target words (default 0.05). |
| `PLAGIARISM_OVERLAP_THRESHOLD` | Max overlap fraction with source blogs (default 0.15). |
| `SERP_RESULTS_COUNT` | Number of SERP results to analyze (default 5). |
| `ALLOWED_ORIGINS` | CORS origins. |
| `HOST` / `PORT` / `RELOAD` | Server host/port/reload defaults. |

The `.env` file is gitignored — never commit secrets.

---

## Project structure

```
backend/
  app.py                  # entry point (server + CLI)
  requirements.txt
  acl_agent/
    api.py                # FastAPI app: SSE endpoints, keepalives
    auth.py               # user accounts (unused by frontend)
    auto_brief.py         # SERP + brief generation (SIZE_MAP)
    cli.py                # CLI subcommands
    config.py             # env + constants
    generation.py         # single-call prompt + generate_single_call_article
    knowledge_base.py     # FAISS + BM25 + reranker retrieval
    llm.py                # model clients, JSON parsing, retry logic
    models.py             # Pydantic models
    pipeline_1click.py    # orchestration (generate_1click / generate_full_pipeline)
    scraping.py           # fetching/scraping/chunking
    validation.py         # quality validators
frontend/
  index.html              # form + guide modal (no auth UI)
  app.js                  # SSE reader, word counters, dynamic tracker
  styles.css              # full CSS matching HTML class names
.env                      # gitignored
.gitignore
memory.md                 # session/state log
```

---

## Known limitations

- **HF free API rate limits** restrict to roughly one concurrent generation;
  the 8B model may occasionally return invalid JSON (mitigated by retry and
  lenient parsing). For faster, reliable, multi-user generation, switch to a
  parallel-capable provider (Groq / OpenAI / Gemini).
- Request-time website scraping only runs when the **Website** field is
  filled in (not when it falls back to the `.env` brand site).

---

## License

Project-specific — see repository settings on GitHub.
