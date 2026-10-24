"""Helpers shared by the three calls: photos, schema checks, raw dumps, cost + run log."""

import base64
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

import config


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Photos ------------------------------------------------------------------

def list_photos(photos_dir: Path) -> list[Path]:
    if not photos_dir.is_dir():
        return []
    return sorted(
        p for p in photos_dir.iterdir()
        if p.is_file() and p.suffix.lower() in config.PHOTO_EXTENSIONS
    )


def load_photo_jpeg(path: Path) -> tuple[bytes, tuple[int, int]]:
    """Return (JPEG bytes, (width, height)) after EXIF rotation and downscaling."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=config.JPEG_QUALITY)
        return buf.getvalue(), img.size


def openai_photo_parts(photos: list[Path], preview: bool = False) -> list[dict[str, Any]]:
    """Chat content parts labelling each photo "Photo N (file)". preview=True skips encoding."""
    parts: list[dict[str, Any]] = []
    for i, path in enumerate(photos, start=1):
        parts.append({"type": "text", "text": f"Photo {i} ({path.name}):"})
        if preview:
            parts.append({"type": "image_url", "image_url": {"url": f"<data/photos/{path.name}>"}})
            continue
        jpeg, _ = load_photo_jpeg(path)
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode('ascii')}",
                          "detail": config.IMAGE_DETAIL},
        })
    return parts


def render_messages_text(messages: list[dict[str, Any]]) -> str:
    """Human-readable dump of chat messages (images shown as placeholders) for prompt previews."""
    lines = []
    for m in messages:
        lines.append(f"=== {m['role'].upper()} ===")
        content = m["content"]
        if isinstance(content, str):
            lines.append(content)
            continue
        for part in content:
            lines.append(part["text"] if part["type"] == "text" else f"  <image {part['image_url']['url']}>")
    return "\n".join(lines)


# --- Structured output ---------------------------------------------------------

def json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI strict structured-output response_format."""
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Minimal schema check (object/array/string/integer/enum). Returns a list of problems."""
    problems: list[str] = []
    kind = schema["type"]
    if kind == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        for key in schema["required"]:
            if key not in value:
                problems.append(f"{path}.{key}: missing")
        for key in value.keys() - schema["properties"].keys():
            problems.append(f"{path}.{key}: unexpected key")
        for key, sub in schema["properties"].items():
            if key in value:
                problems += validate(value[key], sub, f"{path}.{key}")
    elif kind == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        for i, item in enumerate(value):
            problems += validate(item, schema["items"], f"{path}[{i}]")
    elif kind == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(f"{path}: expected integer")
    elif kind == "string":
        if not isinstance(value, str):
            problems.append(f"{path}: expected string")
        elif "enum" in schema and value not in schema["enum"]:
            problems.append(f"{path}: {value!r} not in {schema['enum']}")
    return problems


def parse_openai_json(response: Any, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (parsed JSON, problems). problems is non-empty on refusal, truncation or schema mismatch."""
    try:
        choice = response.choices[0]
        if choice.message.refusal:
            return None, [f"model refused: {choice.message.refusal}"]
        if choice.finish_reason == "length":
            return None, ["output truncated (finish_reason=length); raise the max output tokens in config.py"]
        parsed = json.loads(choice.message.content or "")
    except Exception as exc:
        return None, [f"could not parse response: {exc}"]
    return parsed, validate(parsed, schema)


def dump_raw(name: str, payload: str) -> Path:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = config.RAW_DIR / f"{name}_{stamp}.json"
    path.write_text(payload, encoding="utf-8")
    return path


# --- Cost + run log -------------------------------------------------------------

def openai_usage(response: Any) -> dict[str, int]:
    usage = response.usage
    if not usage:
        return {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    details = usage.completion_tokens_details
    return {
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,   # includes reasoning, billed at the output rate
        "thinking_tokens": 0,
        "reasoning_tokens_included": (details.reasoning_tokens or 0) if details else 0,
    }


def gemini_usage(response: Any) -> dict[str, int]:
    usage = response.usage_metadata
    if not usage:
        return {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
    return {
        "input_tokens": usage.prompt_token_count or 0,
        "output_tokens": usage.candidates_token_count or 0,
        "thinking_tokens": usage.thoughts_token_count or 0,
    }


def estimate_cost(model: str, usage: dict[str, int]) -> float:
    price = config.PRICES.get(model)
    if price is None:
        return 0.0
    thinking_price = price.get("thinking", price["output"])
    return (usage.get("input_tokens", 0) * price["input"]
            + usage.get("output_tokens", 0) * price["output"]
            + usage.get("thinking_tokens", 0) * thinking_price) / 1_000_000


def log_call(step: str, model: str, usage: dict[str, int], status: str, **extra: Any) -> float:
    """Append one API call to run_log.json and return its estimated cost."""
    cost = estimate_cost(model, usage)
    entry = {"at": utc_now(), "step": step, "model": model, "status": status, **usage,
             "cost_usd": round(cost, 6), **extra}
    if model not in config.PRICES:
        entry["warning"] = "no price in config.PRICES; cost counted as $0"
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    if config.RUN_LOG_PATH.exists():
        try:
            entries = json.loads(config.RUN_LOG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config.RUN_LOG_PATH.replace(config.RUN_LOG_PATH.with_suffix(".corrupt.json"))
    entries.append(entry)
    config.RUN_LOG_PATH.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return cost


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
