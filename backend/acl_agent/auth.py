"""
ACL Blog Agent - simple user accounts.

Users are stored in a local JSON file (backend/data/users.json,
gitignored). Passwords are salted + hashed with PBKDF2 via
hashlib, never stored in plaintext. Each user gets an opaque bearer
token used to authenticate the generation API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from pathlib import Path

from acl_agent.config import DATA_DIR, logger

USERS_PATH = Path(DATA_DIR) / "users.json"

_lock = threading.Lock()


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "user"


def _hash_password(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        200_000,
    )
    return digest.hex()


def _load_users() -> list[dict]:
    if not USERS_PATH.exists():
        return []
    try:
        data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
        return data.get("users", [])
    except Exception as error:
        logger.warning("Could not read users.json: %s", error)
        return []


def _save_users(users: list[dict]) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USERS_PATH.write_text(
        json.dumps({"users": users}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def signup_user(name: str, password: str) -> dict:
    """
    Creates a new user account. Returns the user record
    (with token) on success. Raises ValueError if the name is
    already taken or the inputs are invalid.
    """
    name = (name or "").strip()
    if not name or len(name) > 100:
        raise ValueError("A name (max 100 chars) is required.")
    if not password or len(password) < 4 or len(password) > 200:
        raise ValueError("Password must be 4-200 characters.")

    with _lock:
        users = _load_users()

        if any(u["name"].lower() == name.lower() for u in users):
            raise ValueError(f"User '{name}' already exists - please log in.")

        salt = secrets.token_hex(16)
        user_id = f"{_slugify(name)}-{secrets.token_hex(3)}"
        record = {
            "user_id": user_id,
            "name": name,
            "salt": salt,
            "password_hash": _hash_password(password, salt),
            "token": secrets.token_hex(24),
            "created_at": time.time(),
        }
        users.append(record)
        _save_users(users)

        logger.info("New user signed up: %s (%s)", name, user_id)
        return {
            "user_id": record["user_id"],
            "name": record["name"],
            "token": record["token"],
        }


def login_user(name: str, password: str) -> dict | None:
    """
    Authenticates an existing user. Returns the session payload
    on success, or None on bad credentials. Reuses the current
    token so other open tabs stay signed in.
    """
    name = (name or "").strip()

    with _lock:
        users = _load_users()
        record = next(
            (u for u in users if u["name"].lower() == name.lower()),
            None,
        )

        if record is None:
            return None

        expected = _hash_password(password, record["salt"])

        if not hmac.compare_digest(
            expected,
            record["password_hash"],
        ):
            return None

        token = (record.get("token") or "").strip()
        if len(token) != 48:
            record["token"] = secrets.token_hex(24)
            _save_users(users)
            token = record["token"]

        logger.info("User logged in: %s (%s)", record["name"], record["user_id"])
        return {
            "user_id": record["user_id"],
            "name": record["name"],
            "token": token,
        }


def logout_user(token: str) -> None:
    """Invalidates the current session token."""
    if not token:
        return
    with _lock:
        users = _load_users()
        changed = False
        for user in users:
            stored = user.get("token") or ""
            if not stored or len(stored) != len(token):
                continue
            if hmac.compare_digest(stored, token):
                user["token"] = secrets.token_hex(24)
                changed = True
                break
        if changed:
            _save_users(users)


def verify_token(token: str) -> dict | None:
    """Returns the user record if the token is valid, else None."""
    if not token:
        return None

    with _lock:
        for user in _load_users():
            stored = user.get("token") or ""
            if not stored or len(stored) != len(token):
                continue
            if hmac.compare_digest(stored, token):
                return {
                    "user_id": user["user_id"],
                    "name": user["name"],
                    "token": token,
                }
    return None