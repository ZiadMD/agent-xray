"""Short, secret-free previews of arbitrary Python values.

Everything X-Ray records about user data goes through here: values are shrunk to a small
JSON-ish shape, rendered, run through a redaction pass and truncated.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Any

import orjson
from pydantic import BaseModel

PREVIEW_CHARS = 280
_MAX_DEPTH = 4
_MAX_ITEMS = 6
_MAX_KEYS = 16
_MAX_PAYLOAD_BYTES = 4096
REDACTED = "[REDACTED]"

_SECRET_RE = re.compile(
    "|".join(
        (
            r"sk-(?:proj-|ant-|or-)?[A-Za-z0-9_\-]{16,}",  # OpenAI / Anthropic / OpenRouter
            r"gsk_[A-Za-z0-9]{20,}",  # Groq
            r"AIza[0-9A-Za-z_\-]{30,}",  # Google
            r"tvly-[A-Za-z0-9_\-]{16,}",  # Tavily
            r"(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}",  # GitHub
            r"xox[abprs]-[A-Za-z0-9\-]{10,}",  # Slack
            r"hf_[A-Za-z0-9]{30,}",  # Hugging Face
            r"lsv2_[a-z]{2}_[A-Za-z0-9_]{20,}",  # LangSmith
            r"AKIA[0-9A-Z]{16}",  # AWS access key id
            r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",  # JWT
            r"(?i:bearer)\s+[A-Za-z0-9._\-]{16,}",
        )
    )
)
_SECRET_KV_RE = re.compile(
    r"(?i)((?:api[_-]?key|secret|token|password|passwd|authorization)[\"']?\s*[:=]\s*[\"']?)"
    r"([^\"'\s,}]{6,})"
)


def redact(text: str) -> str:
    """Replace anything that looks like a credential with ``[REDACTED]``."""
    text = _SECRET_RE.sub(REDACTED, text)
    return _SECRET_KV_RE.sub(lambda m: m.group(1) + REDACTED, text)


def truncate(text: str, limit: int = PREVIEW_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _message_dict(msg: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"type": getattr(msg, "type", type(msg).__name__)}
    content = getattr(msg, "content", None)
    if content:
        out["content"] = content
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        out["tool_calls"] = [tc.get("name") for tc in tool_calls]
    return out


def compact(value: Any, depth: int = 0) -> Any:
    """Shrink any value to a small JSON-compatible structure (bounded size and depth)."""
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return truncate(value, PREVIEW_CHARS)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if depth >= _MAX_DEPTH:
        return truncate(repr(value), 80)
    # LangChain messages: keep the parts that matter for a preview
    if hasattr(value, "content") and hasattr(value, "type") and hasattr(value, "id"):
        return compact(_message_dict(value), depth)
    if isinstance(value, BaseModel):
        try:
            return compact(value.model_dump(), depth)
        except Exception:
            return truncate(repr(value), 120)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        fields = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
        # leave out empty fields (a langgraph Command is mostly None: show its `update`)
        return compact({k: v for k, v in fields.items() if v not in (None, (), [], {})}, depth)
    if isinstance(value, Mapping):
        items = list(value.items())
        out = {str(k): compact(v, depth + 1) for k, v in items[:_MAX_KEYS]}
        if len(items) > _MAX_KEYS:
            out["…"] = f"+{len(items) - _MAX_KEYS} more keys"
        return out
    if isinstance(value, list | tuple | set | frozenset):
        seq = list(value)
        if len(seq) <= _MAX_ITEMS:
            return [compact(v, depth + 1) for v in seq]
        # keep the tail: for message lists the latest items are the interesting ones
        tail = seq[-(_MAX_ITEMS - 1) :]
        return [f"…(+{len(seq) - len(tail)} earlier)", *(compact(v, depth + 1) for v in tail)]
    return truncate(repr(value), 120)


def preview(value: Any, limit: int = PREVIEW_CHARS) -> str:
    """Render a value as a short, redacted string (at most ``limit`` chars)."""
    if isinstance(value, str):
        text = value
    else:
        small = compact(value)
        text = small if isinstance(small, str) else orjson.dumps(small).decode()
    return truncate(redact(text), limit)


def _redact_tree(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_tree(v) for v in value]
    return value


def payload(value: Any) -> Any:
    """Make a user payload (custom events) JSON-safe, redacted and size-capped."""
    small = _redact_tree(compact(value))
    if len(orjson.dumps(small)) > _MAX_PAYLOAD_BYTES:
        return preview(value)
    return small
