from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 4_000_000
MAX_CANDIDATES = 500
MAX_OFFERS = 500
MAX_REVIEWS = 1500
MAX_DOCUMENTS = 300
MAX_MERCHANTS = 200


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def load_json_file(path: Path) -> dict[str, Any]:
    size = path.stat().st_size
    if size > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return ensure_object(json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant))


def load_json_text(text: str) -> dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return ensure_object(json.loads(text, parse_constant=reject_constant))


def ensure_object(value: Any, name: str = "payload") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object")
    return value


def bounded_list(value: Any, name: str, maximum: int) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds maximum length {maximum}")
    return value


def finite_number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return number


def limited_text(value: Any, name: str, maximum: int = 50_000) -> str:
    text = "" if value is None else str(value)
    if len(text) > maximum:
        return text[:maximum]
    return text
