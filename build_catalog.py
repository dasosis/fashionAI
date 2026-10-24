"""One-time: build the swipe-deck catalog from the public Myntra product dataset.

    .\\.venv\\Scripts\\python.exe build_catalog.py            # metadata -> sample -> download -> tag -> catalog.json
    .\\.venv\\Scripts\\python.exe build_catalog.py --dry-run  # stop before the paid tagging calls

Resumable: metadata, images and tagging results are cached under data/catalog/.
"""

import argparse
import base64
import io
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

import config
from attributes import (CATEGORIES, COLOR_FAMILIES, COLOR_TONES, FITS, LOUDNESS, MATERIALS, OCCASIONS,
                        PATTERNS, STYLES)
from common import dump_raw, json_schema_format, log_call, openai_usage, parse_openai_json, read_json, write_json

META_COLUMNS = ["id", "gender", "masterCategory", "subCategory", "articleType", "baseColour",
                "season", "year", "usage", "productDisplayName"]

TAG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "keep", "reject_reason", "name", "description", "category", "styles",
                     "color_family", "color_tone", "pattern", "fit", "formality", "loudness", "material",
                     "occasions", "image_quality"],
        "properties": {
            "id": {"type": "integer"},
            "keep": {"type": "boolean"},
            "reject_reason": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "styles": {"type": "array", "items": {"type": "string", "enum": STYLES}},
            "color_family": {"type": "string", "enum": COLOR_FAMILIES},
            "color_tone": {"type": "string", "enum": COLOR_TONES},
            "pattern": {"type": "string", "enum": PATTERNS},
            "fit": {"type": "string", "enum": FITS},
            "formality": {"type": "integer"},
            "loudness": {"type": "string", "enum": LOUDNESS},
            "material": {"type": "string", "enum": MATERIALS},
            "occasions": {"type": "array", "items": {"type": "string", "enum": OCCASIONS}},
            "image_quality": {"type": "integer"},
        },
    }}},
}

TAG_PROMPT = """You are tagging menswear product photos for a style-preference swipe deck.
For each photo (labelled with its id and the store's metadata) return one entry:
- keep: false if the photo is unclear, mostly packaging, not menswear, a near-duplicate of a very
  generic item, or so dated it would confuse someone judging their taste today. Otherwise true.
  reject_reason: short reason, or "" when kept.
- name: short, specific display name without brand, e.g. "Olive utility bomber jacket".
- description: one sentence a stylist would write: color, cut, fabric, details.
- category, styles (1-3 that genuinely apply), color_family (dominant color), color_tone, pattern,
  fit ("not_applicable" for shoes, watches, eyewear, bags, jewelry), material, occasions (1-3).
- formality: 1 very casual, 2 casual, 3 smart, 4 dressy, 5 formal.
- loudness: how much attention it draws (subtle / moderate / statement).
- image_quality: 1-5, how good the photo is as a large swipe card (5 = clean, sharp, whole item visible).
Judge from the photo; the metadata can be wrong."""


def load_metadata() -> list[dict[str, Any]]:
    if not config.CATALOG_META_PATH.exists():
        from huggingface_hub import HfFileSystem
        fs = HfFileSystem()
        base = f"datasets/{config.CATALOG_DATASET}@~parquet/default/train"
        tables, offset = [], 0
        for f in sorted(fs.ls(base, detail=False)):
            print(f"[meta] reading {f.rsplit('/', 1)[-1]}", flush=True)
            with fs.open(f, "rb", block_size=4 * 1024 * 1024) as fh:
                table = pq.read_table(fh, columns=META_COLUMNS)
            tables.append(table.append_column("row_idx", pa.array(range(offset, offset + table.num_rows))))
            offset += table.num_rows
        config.CATALOG_DIR.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.concat_tables(tables), config.CATALOG_META_PATH)
    return pq.read_table(config.CATALOG_META_PATH).to_pylist()


def sample_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Menswear per articleType quota, weighted toward newer catalog years."""
    rng = random.Random(config.CATALOG_SEED)
    picked = []
    for article, quota in config.CATALOG_QUOTAS.items():
        pool = [r for r in rows if r["gender"] == "Men" and r["articleType"] == article]
        weights = [3.0 if (r["year"] or 0) >= 2015 else 1.0 for r in pool]
        chosen: dict[int, dict[str, Any]] = {}
        while pool and len(chosen) < min(quota, len(pool)):
            r = rng.choices(pool, weights=weights, k=1)[0]
            chosen[r["id"]] = r
        picked += chosen.values()
        print(f"[sample] {article}: {len(chosen)} of {len(pool)}")
    return picked


def download_image(row: dict[str, Any]) -> tuple[int, str | None]:
    path = config.CATALOG_IMAGES_DIR / f"{row['id']}.jpg"
    if path.exists():
        return row["id"], None
    url = "https://datasets-server.huggingface.co/rows?" + urllib.parse.urlencode({
        "dataset": config.CATALOG_DATASET, "config": "default", "split": "train",
        "offset": row["row_idx"], "length": 1})
    error = ""
    for attempt in range(7):
        try:
            data = json.load(urllib.request.urlopen(url, timeout=60))
            found = data["rows"][0]["row"]
            if found["id"] != row["id"]:
                return row["id"], f"row_idx mismatch (got id {found['id']})"
            raw = urllib.request.urlopen(found["image"]["src"], timeout=60).read()
            with Image.open(io.BytesIO(raw)) as img:
                img = img.convert("RGB")
                img.thumbnail((config.CATALOG_IMAGE_MAX_SIDE, config.CATALOG_IMAGE_MAX_SIDE))
                img.save(path, format="JPEG", quality=88)
            return row["id"], None
        except urllib.error.HTTPError as exc:
            error = str(exc)
            if exc.code != 429:
                break
            time.sleep(min(60, 5 * 2 ** attempt))   # the datasets-server rate-limits bursts
        except Exception as exc:
            error = str(exc)
            break
    return row["id"], error


def tag_batch(client: OpenAI, batch: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": TAG_PROMPT}]
    for r in batch:
        meta = f"id {r['id']}: {r['productDisplayName']} | {r['articleType']} | {r['baseColour']} | {r['usage']}"
        b64 = base64.b64encode((config.CATALOG_IMAGES_DIR / f"{r['id']}.jpg").read_bytes()).decode("ascii")
        content += [{"type": "text", "text": meta},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}}]
    try:
        response = client.chat.completions.create(
            model=config.CATALOG_TAG_MODEL,
            messages=[{"role": "user", "content": content}],
            response_format=json_schema_format("catalog_tags", TAG_SCHEMA),
            reasoning_effort="low",
        )
    except Exception as exc:
        log_call("catalog_tag", config.CATALOG_TAG_MODEL, {}, "error", error=str(exc))
        print(f"  ! tagging call failed: {exc}")
        return {}
    usage = openai_usage(response)
    parsed, problems = parse_openai_json(response, TAG_SCHEMA)
    ids = {r["id"] for r in batch}
    results = {}
    if parsed:
        for item in parsed["items"]:
            if item["id"] in ids and 1 <= item["formality"] <= 5 and 1 <= item["image_quality"] <= 5 \
                    and item["styles"] and item["occasions"]:
                results[item["id"]] = item
    if problems or len(results) != len(ids):
        raw = dump_raw("catalog_tag_response", response.model_dump_json(indent=2))
        problems = problems + [f"tagged {len(results)} of {len(ids)} usable"]
        log_call("catalog_tag", config.CATALOG_TAG_MODEL, usage, "partial", problems=problems, raw=str(raw))
        print(f"  ! {problems}")
    else:
        log_call("catalog_tag", config.CATALOG_TAG_MODEL, usage, "ok", items=len(ids))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="sample + download only; no paid tagging calls")
    parser.add_argument("--skip-download", action="store_true", help="tag only images already on disk")
    args = parser.parse_args()
    load_dotenv(config.ROOT / ".env")

    candidates = sample_candidates(load_metadata())
    config.CATALOG_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not args.skip_download:
        print(f"[download] {len(candidates)} images")
        with ThreadPoolExecutor(max_workers=2) as pool:
            failures = [(i, e) for i, e in pool.map(download_image, candidates) if e]
        if failures:
            print(f"  ! {len(failures)} downloads failed (rerun to retry), e.g. {failures[:3]}")
    candidates = [r for r in candidates if (config.CATALOG_IMAGES_DIR / f"{r['id']}.jpg").exists()]

    cache: dict[str, Any] = read_json(config.CATALOG_TAGS_CACHE_PATH) or {}
    todo = [r for r in candidates if str(r["id"]) not in cache]
    batches = [todo[i:i + config.CATALOG_TAG_BATCH] for i in range(0, len(todo), config.CATALOG_TAG_BATCH)]
    print(f"[tag] {len(todo)} untagged items in {len(batches)} calls to {config.CATALOG_TAG_MODEL}")
    if args.dry_run:
        print("[tag] dry run: skipping")
        return 0
    client = OpenAI()
    for n, batch in enumerate(batches, start=1):
        print(f"[tag] batch {n}/{len(batches)}", flush=True)
        for item_id, tags in tag_batch(client, batch).items():
            cache[str(item_id)] = tags
        write_json(config.CATALOG_TAGS_CACHE_PATH, cache)

    by_id = {r["id"]: r for r in candidates}
    catalog = []
    for key, tags in cache.items():
        row = by_id.get(int(key))
        if row is None or not tags["keep"]:
            continue
        catalog.append({k: v for k, v in tags.items() if k not in ("keep", "reject_reason")}
                       | {"image": f"{row['id']}.jpg", "source": {"articleType": row["articleType"],
                                                                  "productDisplayName": row["productDisplayName"],
                                                                  "year": row["year"]}})
    catalog.sort(key=lambda it: it["id"])
    write_json(config.CATALOG_PATH, {"dataset": config.CATALOG_DATASET, "items": catalog})
    rejected = sum(1 for t in cache.values() if not t["keep"])
    print(f"[done] {len(catalog)} items in {config.CATALOG_PATH} ({rejected} rejected, "
          f"{len(candidates) - len(cache)} untagged)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(main())
