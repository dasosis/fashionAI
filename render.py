"""Call 3: one reference photo + one look -> one Gemini image, saved to out/looks/look_{n}_{model}.png."""

import io
import os
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types
from PIL import Image

import config
from common import dump_raw, gemini_usage, load_photo_jpeg, log_call

# Wording matters: phrasing like "a real person" / "recognizable as the same individual"
# made gemini-2.5-flash-image return finish_reason IMAGE_OTHER with no image.
PROMPT_TEMPLATE = """Using the person shown in this photo, create a new full-body photo of them
wearing a completely new outfit. Keep their face, facial hair, skin tone, hair and body
proportions the same as in the photo: do not lighten or smooth the skin, and do not slim or
reshape the body. Replace everything else: clothing, footwear, eyewear, accessories, pose,
background and lighting all come from this description:

{render_prompt}

One person, full body from head to toe in frame, no text, no watermark, no collage."""


def build_prompt(look: dict[str, Any]) -> str:
    return PROMPT_TEMPLATE.format(render_prompt=look["render_prompt"])


def look_path(n: int, model: str) -> Path:
    return config.LOOKS_DIR / f"look_{n}_{model}.png"


def preview(look: dict[str, Any], reference_file: str, model: str) -> str:
    return (f"model: {model} | aspect ratio: {config.RENDER_ASPECT_RATIO} | "
            f"up to {config.RENDER_MAX_ATTEMPTS} attempts\n\n"
            f"  <image {reference_file}>\n{build_prompt(look)}")


def extract_image(response: Any) -> tuple[bytes | None, str]:
    """Return (final image bytes or None, any text). Skips interim 'thought' images from thinking models."""
    image, texts = None, []
    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else None) or []:
            if getattr(part, "thought", False):
                continue
            if part.inline_data and part.inline_data.data:
                image = part.inline_data.data   # keep the last final image
            elif part.text:
                texts.append(part.text)
    return image, "\n".join(texts)


def run(n: int, look: dict[str, Any], reference: Path, model: str) -> tuple[dict[str, Any], float]:
    """Render look n. Returns (result, cost); result["status"] is ok or error. Never raises for API problems."""
    if model not in config.RENDER_MODELS:
        raise ValueError(f"unknown render model {model!r}; allowed: {config.RENDER_MODELS}")
    reference_file = reference.name
    out_path = look_path(n, model)
    out_path.unlink(missing_ok=True)  # never leave a stale image from an earlier run
    jpeg, _ = load_photo_jpeg(reference)
    contents = [types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), build_prompt(look)]
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    total_cost, error = 0.0, ""
    for attempt in range(1, config.RENDER_MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=config.RENDER_ASPECT_RATIO),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        except Exception as exc:
            total_cost += log_call("render", model, {}, "error", look=n, attempt=attempt, error=str(exc))
            return {"status": "error", "error": f"Gemini call failed: {exc}"}, total_cost

        usage = gemini_usage(response)
        image_bytes, text = extract_image(response)
        if image_bytes is not None:
            try:
                with Image.open(io.BytesIO(image_bytes)) as img:
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    img.save(out_path, format="PNG")
                total_cost += log_call("render", model, usage, "ok", look=n, attempt=attempt,
                                       reference=reference_file, file=out_path.name)
                return {"status": "ok", "file": out_path.name, "attempts": attempt}, total_cost
            except Exception as exc:
                error = f"could not decode image: {exc}"
        else:
            reason = response.candidates[0].finish_reason if response.candidates else response.prompt_feedback
            error = f"no image in response (finish: {reason}; text: {text[:300]!r})"
        # Empty responses (e.g. IMAGE_OTHER) are intermittent, so they are worth a retry.
        raw_path = dump_raw(f"render_look{n}_{model}_attempt{attempt}", response.model_dump_json(indent=2))
        total_cost += log_call("render", model, usage, "no_image", look=n, attempt=attempt,
                               error=error, raw=str(raw_path))
    return {"status": "error", "error": error, "attempts": config.RENDER_MAX_ATTEMPTS}, total_cost
