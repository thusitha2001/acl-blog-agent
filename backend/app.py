"""
ACL Blog Agent - entry point.

All real logic lives in the acl_agent/ package (config, models, llm,
scraping, knowledge_base, prompts, generation, validation, pipeline,
api, cli). This file exists so `python app.py <command>` and
`uvicorn app:app` keep working exactly as before the module split -
see memory.md for the history of this refactor.
"""
from __future__ import annotations

from acl_agent.api import app  # noqa: F401  (re-exported for `uvicorn app:app`)
from acl_agent.cli import main

if __name__ == "__main__":
    main()
