"""Single source of truth for model names, prices and paths.

Prices are USD per 1M tokens, copied from the provider pricing pages
(OpenAI: gpt-5; Google: ai.google.dev/gemini-api/docs/pricing, checked 2026-09-15).
Verify before trusting cost output. Nothing else in the project hardcodes a model name.
"""

from pathlib import Path

# --- Models ------------------------------------------------------------------
CATALOG_TAG_MODEL = "gpt-5-mini"  # one-time: tag catalog images with attributes (build_catalog.py)
ANALYSIS_MODEL = "gpt-5"   # call 1: photos -> stylist observations, flags, reference photo
STYLES_MODEL = "gpt-5"     # call 2: photos + intake + swipe taste profile -> three detailed looks
RENDER_MODELS = [          # call 3: reference photo + look -> image
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
    "gemini-2.5-flash-image",  # deprecated by Google; kept for comparison
]
DEFAULT_RENDER_MODELS = ["gemini-3.1-flash-image", "gemini-3-pro-image"]  # "Render all" uses both

# --- Prices (USD per 1M tokens) ------------------------------------------------
# OpenAI reasoning tokens are billed as output. Gemini image models bill generated
# images as output tokens; "thinking" is the price for thought tokens where it differs.
PRICES: dict[str, dict[str, float]] = {
    "gpt-5": {"input": 1.25, "output": 10.00},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gemini-2.5-flash-image": {"input": 0.30, "output": 30.00},    # ~1290 tokens/image = $0.039
    # No "thinking" price verified for these yet, so thought tokens are counted at the
    # image output rate: an overestimate, never an underestimate.
    "gemini-3.1-flash-image": {"input": 0.50, "output": 60.00},    # 1K image ~$0.067
    "gemini-3-pro-image": {"input": 2.00, "output": 120.00},       # 1K/2K image ~$0.134
}

# --- Photos ------------------------------------------------------------------
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_SIDE = 2048        # OpenAI downsizes to this anyway; shrinking locally keeps payloads small
JPEG_QUALITY = 90
IMAGE_DETAIL = "high"

# --- Call settings -------------------------------------------------------------
ANALYSIS_MAX_OUTPUT_TOKENS = 16_000   # includes reasoning tokens

# --- Catalog (swipe deck) ----------------------------------------------------------
# Public dataset: Myntra "Fashion Product Images" (Kaggle, paramaggarwal), 900x1200 mirror on Hugging Face.
# Check its license before using this beyond a local prototype.
CATALOG_DATASET = "benitomartin/fashion-product-images-small-900x1200"
CATALOG_SEED = 7
CATALOG_IMAGE_MAX_SIDE = 800
CATALOG_TAG_BATCH = 8                 # images per tagging call
# Menswear candidates per Myntra articleType. Tagging drops dated/unclear ones, so the final deck is smaller.
CATALOG_QUOTAS: dict[str, int] = {
    "Tshirts": 40, "Shirts": 40, "Sweatshirts": 12, "Jackets": 16, "Sweaters": 10, "Blazers": 5,
    "Waistcoat": 4, "Nehru Jackets": 5, "Kurtas": 16, "Churidar": 3,
    "Trousers": 20, "Jeans": 16, "Shorts": 8, "Track Pants": 6, "Lounge Pants": 3,
    "Casual Shoes": 22, "Formal Shoes": 8, "Sports Shoes": 8, "Sandals": 6,
    "Sunglasses": 12, "Watches": 14, "Belts": 4, "Caps": 6, "Ring": 4, "Bracelet": 4, "Pendant": 3,
    "Backpacks": 4, "Messenger Bag": 2, "Scarves": 3,
}

SWIPE_TARGET = 30                     # progress bar goal
SWIPE_MIN = 15                        # "build my taste profile" unlocks after this many

NUM_LOOKS = 3
STYLES_MAX_OUTPUT_TOKENS = 24_000
STYLES_MAX_ATTEMPTS = 2               # 1 retry with the validation problems fed back

RENDER_ASPECT_RATIO = "3:4"
RENDER_MAX_ATTEMPTS = 2               # retry when a look comes back with no image (e.g. IMAGE_OTHER)

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
CATALOG_DIR = ROOT / "data" / "catalog"
CATALOG_IMAGES_DIR = CATALOG_DIR / "images"
CATALOG_META_PATH = CATALOG_DIR / "meta.parquet"          # metadata columns of the whole dataset
CATALOG_TAGS_CACHE_PATH = CATALOG_DIR / "tags_cache.json"  # per-item tagging results (resumable)
CATALOG_PATH = CATALOG_DIR / "catalog.json"                # final deck used by the app
OUT_DIR = ROOT / "out"
RAW_DIR = OUT_DIR / "raw"             # raw API responses dumped on parse failure
UPLOADS_DIR = OUT_DIR / "uploads"     # uploads/<session id>/photo_N.jpg
MAX_UPLOAD_PHOTOS = 10
LOOKS_DIR = OUT_DIR / "looks"         # look_{n}_{model}.png
SESSION_PATH = OUT_DIR / "session.json"     # intake answers, swipes, reference choice, render results
ANALYSIS_PATH = OUT_DIR / "analysis.json"   # call 1 output
STYLES_PATH = OUT_DIR / "styles.json"       # call 2 output
RUN_LOG_PATH = OUT_DIR / "run_log.json"     # one entry per API call
