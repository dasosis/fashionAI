"""Call 1: photos (+ intake vibe) -> stylist observations, flags on what works against them, reference photo."""

from pathlib import Path
from typing import Any

from openai import OpenAI

import config
import intake
from common import (dump_raw, json_schema_format, log_call, openai_photo_parts,
                    openai_usage, parse_openai_json, render_messages_text, utc_now)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["observations", "reference_photo"],
    "properties": {
        "observations": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "suits_you", "what_works", "flags"],
            "properties": {
                "summary": {"type": "string"},
                "suits_you": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["colors", "avoid_colors", "necklines_and_collars", "fits_and_silhouettes",
                                 "eyewear", "accessories"],
                    "properties": {
                        "colors": {"type": "array", "items": {"type": "string"}},
                        "avoid_colors": {"type": "array", "items": {"type": "string"}},
                        "necklines_and_collars": {"type": "string"},
                        "fits_and_silhouettes": {"type": "string"},
                        "eyewear": {"type": "string"},
                        "accessories": {"type": "string"},
                    },
                },
                "what_works": {"type": "array", "items": {"type": "string"}},
                "flags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["item", "issue", "suggestion"],
                        "properties": {
                            "item": {"type": "string"},
                            "issue": {"type": "string"},
                            "suggestion": {"type": "string"},
                        },
                    },
                },
            },
        },
        "reference_photo": {
            "type": "object",
            "additionalProperties": False,
            "required": ["photo_number", "reason"],
            "properties": {"photo_number": {"type": "integer"}, "reason": {"type": "string"}},
        },
    },
}

SYSTEM_PROMPT = """You are a senior personal stylist meeting a new client. You have their photos
and the overall vibe they told you they want.

How you work:
- Look at the photos yourself and judge the whole person: skin tone and undertone, contrast,
  face shape and features, hair and grooming, build and proportions, posture. Reason from what
  you see, not from a checklist.
- What the client currently wears is evidence, not their preference. People often wear things
  that undersell them.
- Be candid. If something they wear (eyewear, a color near the face, a fit, footwear, an
  accessory, grooming) works against them, flag it and say why in terms of what you see.
- Do not identify the person, and do not comment on ethnicity, age, weight or health. Stick to
  what matters for clothes, colors, eyewear, accessories and grooming.
- Photos vary in lighting; weight well-lit photos most for color judgements."""

USER_TEMPLATE = """The vibe the client picked:
{answers}

The client's photos follow. Then produce:

1. observations.summary: 4-6 sentences, in prose, on how this person reads to a stylist:
   coloring (undertone, contrast), face shape and features, hair and grooming, build and proportions.
2. observations.suits_you: what will look good on them regardless of taste: specific colors
   (names), colors to keep away from the face, necklines and collars, fits and silhouettes,
   eyewear frame shapes and colors, accessory scale and metals.
3. observations.what_works: things currently worn in the photos that genuinely suit them, and why.
4. observations.flags: things currently worn that work against them, each with the item, the
   issue tied to what you see (e.g. "white round frames wash out against medium skin and echo a
   round jaw"), and a concrete suggestion. Cite photo numbers. Empty only if nothing is off.
5. reference_photo: (if there is only one photo, it is photo 1) the ONE photo best suited as the identity reference for an image model that
   will re-dress this person. Prefer: whole body head to feet; face clearly visible and roughly
   front-facing; bright, even lighting; plain, uncluttered background; nothing covering face or
   hair; nobody else in frame. Give the photo number and the reason."""


def build_messages(intake_answers: dict[str, Any], photos: list[Path], preview: bool = False) -> list[dict[str, Any]]:
    user_text = USER_TEMPLATE.format(answers=intake.answers_text(intake_answers))
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": user_text},
                                     *openai_photo_parts(photos, preview=preview)]},
    ]


def preview(intake_answers: dict[str, Any], photos: list[Path]) -> str:
    header = (f"model: {config.ANALYSIS_MODEL} | detail: {config.IMAGE_DETAIL} | "
              f"response_format: json_schema (strict) 'client_analysis'\n\n")
    return header + render_messages_text(build_messages(intake_answers, photos, preview=True))


def run(intake_answers: dict[str, Any], photos: list[Path]) -> tuple[dict[str, Any], float]:
    """Call 1. Returns (analysis, cost). Raises RuntimeError with a readable message on failure."""
    if not photos:
        raise RuntimeError("Upload at least one photo first")
    try:
        response = OpenAI().chat.completions.create(
            model=config.ANALYSIS_MODEL,
            messages=build_messages(intake_answers, photos),
            response_format=json_schema_format("client_analysis", RESPONSE_SCHEMA),
            max_completion_tokens=config.ANALYSIS_MAX_OUTPUT_TOKENS,
        )
    except Exception as exc:
        log_call("analysis", config.ANALYSIS_MODEL, {}, "error", error=str(exc))
        raise RuntimeError(f"OpenAI analysis call failed: {exc}") from exc

    usage = openai_usage(response)
    parsed, problems = parse_openai_json(response, RESPONSE_SCHEMA)
    if parsed is not None and not problems:
        n = parsed["reference_photo"]["photo_number"]
        if not 1 <= n <= len(photos):
            problems = [f"reference_photo.photo_number {n} out of range 1..{len(photos)}"]
    if problems:
        raw_path = dump_raw("analysis_response", response.model_dump_json(indent=2))
        cost = log_call("analysis", config.ANALYSIS_MODEL, usage, "error", problems=problems, raw=str(raw_path))
        raise RuntimeError(f"Analysis output rejected: {problems} (raw response: {raw_path}, cost ${cost:.4f})")

    cost = log_call("analysis", config.ANALYSIS_MODEL, usage, "ok")
    ref = parsed["reference_photo"]
    return {
        "created_at": utc_now(),
        "model": config.ANALYSIS_MODEL,
        "photos": [p.name for p in photos],
        "observations": parsed["observations"],
        "reference_photo": {"file": photos[ref["photo_number"] - 1].name, "reason": ref["reason"]},
    }, cost
