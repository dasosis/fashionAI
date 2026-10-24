"""Call 2: photos + intake vibe + swipe taste profile + stylist notes -> three detailed looks with render prompts."""

import json
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

import config
import intake
import recommender
from common import (dump_raw, json_schema_format, log_call, openai_photo_parts,
                    openai_usage, parse_openai_json, render_messages_text, utc_now)

PIECE_CATEGORIES = ["base top", "mid layer", "outer layer", "bottom", "one-piece", "footwear", "headwear"]

LOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "direction", "occasion", "silhouette", "summary", "why_it_suits",
                 "pieces", "eyewear", "accessories", "grooming", "palette", "render_prompt"],
    "properties": {
        "name": {"type": "string"},
        "direction": {"type": "string"},      # e.g. "Korean streetwear"
        "occasion": {"type": "string"},
        "silhouette": {"type": "string"},
        "summary": {"type": "string"},
        "why_it_suits": {"type": "string"},
        "pieces": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["category", "item", "color", "material", "fit", "design_details"],
                "properties": {
                    "category": {"type": "string", "enum": PIECE_CATEGORIES},
                    "item": {"type": "string"},
                    "color": {"type": "string"},
                    "material": {"type": "string"},
                    "fit": {"type": "string"},
                    "design_details": {"type": "string"},
                },
            },
        },
        "eyewear": {
            "type": "object",
            "additionalProperties": False,
            "required": ["type", "shape", "color", "material", "why"],
            "properties": {
                "type": {"type": "string", "enum": ["prescription frames", "sunglasses", "none"]},
                "shape": {"type": "string"},
                "color": {"type": "string"},
                "material": {"type": "string"},
                "why": {"type": "string"},
            },
        },
        "accessories": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "description", "why"],
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
        "grooming": {"type": "string"},
        "palette": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "hex"],
                "properties": {"name": {"type": "string"}, "hex": {"type": "string"}},
            },
        },
        "render_prompt": {"type": "string"},
    },
}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["looks"],
    "properties": {"looks": {"type": "array", "items": LOOK_SCHEMA}},
}

SYSTEM_PROMPT = """You are a senior personal stylist designing outfits for one client. You work
from their photos (look at them yourself), the vibe they picked, a taste profile learned from them
swiping like/dislike on real clothing items, and your own earlier notes on what suits them.

Principles:
- Taste comes from the swipes: styles, colors, patterns, fits, formality, loudness and accessory
  types they liked or rejected. Loved and liked items are strong signals; disliked attributes
  should not appear. Where swipes and the intake disagree, trust the swipes (they are revealed
  preference). Accessory types they consistently disliked stay out.
- Suitability comes from your eye: pick exact colors for their coloring, necklines and lengths for
  their face and build, frame shapes for their face, proportions for their body. Where taste and
  suitability conflict, find the version of what they like that flatters them (e.g. their liked
  color in a better shade, away from the face) and say so in why_it_suits.
- What they wear today is not their style. Fix the flagged items; do not repeat them.
- Be as specific as a tech pack: exact color names, fabric, cut, rise, length, hem, collar,
  wash, prints/graphics (motif, placement, scale, colors), hardware, sole, toe shape.
  "Graphic tee" or "nice jacket" is not acceptable.
- No brand names."""

USER_TEMPLATE = """Intake (overall vibe):
{answers}

Taste profile from swiping (score = learned like-probability, n = cards with that attribute):
{taste}

Your earlier notes on this client:
Summary: {summary}
What suits them: {suits}
Items flagged as working against them:
{flags}

The client's photos follow. Design exactly {n} looks.

Requirements:
- The {n} looks must be clearly different from each other in direction or occasion AND in
  silhouette. Changing only colors is not a different look. Stay within the styles and occasions
  the client showed they like; spread across them.
- pieces: every garment and footwear, each with category, item, color, material, fit and
  design_details (prints/graphics, construction, trims, hardware). Every look needs footwear and
  either a bottom or a one-piece.
- eyewear: if the client wears glasses (see photos) or liked sunglasses, specify frames that suit
  their face shape and coloring, and say why. Address any eyewear flag directly.
- accessories: only types the client liked in the swipes, each with an exact description and why
  it suits them. May be empty.
- grooming: hair and beard styling that finishes the look.
- why_it_suits: 3-5 sentences tying specific choices to what you see in the photos (coloring,
  face, build) and to specific things they liked while swiping.
- palette: 3-6 colors from the look, hex as "#RRGGBB".
- render_prompt: one self-contained paragraph of 120-200 words for an image model that receives
  a reference photo of the client separately. Refer to the client only as "the person" and do
  not describe their face, skin, hair or body. Describe every piece in full detail (color, fabric,
  fit, length, prints/graphics, how it is worn: tucked, cuffed, open), footwear, eyewear,
  accessories and grooming, then a setting that fits the occasion, a natural confident standing
  pose, flattering natural light, full-body framing head to toe, photorealistic fashion editorial."""


def build_messages(analysis: dict[str, Any], session: dict[str, Any], photos: list[Path],
                   preview: bool = False) -> list[dict[str, Any]]:
    obs = analysis["observations"]
    flags_text = "\n".join(f"- {f['item']}: {f['issue']} -> {f['suggestion']}" for f in obs["flags"]) or "- none"
    profile = recommender.taste_profile(session.get("intake_answers") or {}, session.get("swipes") or [])
    user_text = USER_TEMPLATE.format(answers=intake.answers_text(session.get("intake_answers") or {}),
                                     taste=recommender.profile_text(profile),
                                     summary=obs["summary"], suits=json.dumps(obs["suits_you"]),
                                     flags=flags_text, n=config.NUM_LOOKS)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [{"type": "text", "text": user_text},
                                     *openai_photo_parts(photos, preview=preview)]},
    ]


def preview(analysis: dict[str, Any], session: dict[str, Any], photos: list[Path]) -> str:
    header = (f"model: {config.STYLES_MODEL} | up to {config.STYLES_MAX_ATTEMPTS} attempts | "
              f"response_format: json_schema (strict) 'styled_looks'\n\n")
    return header + render_messages_text(build_messages(analysis, session, photos, preview=True))


def check_looks(looks: list[dict[str, Any]]) -> list[str]:
    """Checks beyond the JSON schema: count, distinctness, completeness, detail."""
    problems = []
    if len(looks) != config.NUM_LOOKS:
        problems.append(f"expected {config.NUM_LOOKS} looks, got {len(looks)}")
    for field in ("name", "silhouette"):
        values = [look[field].strip().lower() for look in looks]
        if len(set(values)) != len(values):
            problems.append(f"every look needs a different {field}, got {values}")
    for i, look in enumerate(looks, start=1):
        label = f"look {i} ({look['name']})"
        categories = {p["category"] for p in look["pieces"]}
        if "footwear" not in categories:
            problems.append(f"{label}: no footwear")
        if not categories & {"bottom", "one-piece"}:
            problems.append(f"{label}: needs a bottom or one-piece")
        for p in look["pieces"]:
            if len(p["design_details"].split()) < 4 or not p["color"].strip():
                problems.append(f"{label}: '{p['item']}' is not specific enough (color + design_details)")
        if not 3 <= len(look["palette"]) <= 6:
            problems.append(f"{label}: palette needs 3-6 colors")
        bad_hex = [c["hex"] for c in look["palette"] if not re.fullmatch(r"#[0-9A-Fa-f]{6}", c["hex"])]
        if bad_hex:
            problems.append(f"{label}: invalid hex colors {bad_hex}")
        words = len(look["render_prompt"].split())
        if words < 100:
            problems.append(f"{label}: render_prompt has {words} words, needs 120-200")
    return problems


def run(analysis: dict[str, Any], session: dict[str, Any], photos: list[Path]) -> tuple[dict[str, Any], float]:
    """Call 2 (with one retry on rejected output). Returns (styles, cost). Raises RuntimeError on failure."""
    client = OpenAI()
    messages = build_messages(analysis, session, photos)
    total_cost = 0.0
    problems: list[str] = []
    for attempt in range(1, config.STYLES_MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=config.STYLES_MODEL,
                messages=messages,
                response_format=json_schema_format("styled_looks", RESPONSE_SCHEMA),
                max_completion_tokens=config.STYLES_MAX_OUTPUT_TOKENS,
            )
        except Exception as exc:
            log_call("styles", config.STYLES_MODEL, {}, "error", attempt=attempt, error=str(exc))
            raise RuntimeError(f"OpenAI styles call failed: {exc}") from exc

        usage = openai_usage(response)
        parsed, problems = parse_openai_json(response, RESPONSE_SCHEMA)
        if parsed is not None and not problems:
            problems = check_looks(parsed["looks"])
        if not problems:
            total_cost += log_call("styles", config.STYLES_MODEL, usage, "ok", attempt=attempt)
            break
        raw_path = dump_raw(f"styles_response_attempt{attempt}", response.model_dump_json(indent=2))
        total_cost += log_call("styles", config.STYLES_MODEL, usage, "rejected", attempt=attempt,
                               problems=problems, raw=str(raw_path))
        content = response.choices[0].message.content if response.choices else None
        if content:
            messages = messages + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "Your output was rejected for these reasons:\n- "
                    + "\n- ".join(problems) + "\nReturn the complete corrected set of looks."},
            ]
    else:
        raise RuntimeError(f"Looks rejected after {config.STYLES_MAX_ATTEMPTS} attempts: {problems} "
                           f"(cost ${total_cost:.4f}; raw responses in {config.RAW_DIR})")

    return {"created_at": utc_now(), "model": config.STYLES_MODEL, "looks": parsed["looks"]}, total_cost
