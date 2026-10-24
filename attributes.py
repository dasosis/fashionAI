"""Attribute vocabulary shared by the catalog tagger, the recommender and the intake questions."""

from typing import Any

CATEGORIES = ["top", "outerwear", "bottom", "ethnic", "footwear", "eyewear", "watch", "jewelry",
              "bag", "headwear", "belt", "scarf"]
STYLES = ["streetwear", "minimal", "smart_casual", "classic_formal", "ethnic", "indo_western",
          "athleisure", "vintage_retro", "rugged_outdoor", "preppy", "party_statement"]
COLOR_FAMILIES = ["black", "white", "grey", "navy", "blue", "green", "olive", "brown_tan", "beige_cream",
                  "red_maroon", "pink", "yellow_mustard", "orange_rust", "purple", "multicolor", "metallic"]
COLOR_TONES = ["neutral", "earth", "cool", "bright", "pastel", "dark"]
PATTERNS = ["solid", "stripes", "checks", "graphic_print", "allover_print", "textured", "colorblock", "embroidered"]
FITS = ["slim", "regular", "relaxed", "oversized", "not_applicable"]
LOUDNESS = ["subtle", "moderate", "statement"]
MATERIALS = ["cotton", "denim", "linen", "knit", "wool", "leather", "suede", "synthetic", "silk_blend",
             "metal", "other"]
OCCASIONS = ["everyday", "work", "date_night", "festive", "travel", "sport"]
FORMALITY_BUCKETS = {1: "very_casual", 2: "casual", 3: "smart", 4: "dressy", 5: "formal"}

# Dimensions the recommender learns, with how much each counts toward an item's score.
# multi=True means an item can carry several values (e.g. two styles).
DIMENSIONS: dict[str, dict[str, Any]] = {
    "styles": {"values": STYLES, "multi": True, "weight": 1.6},
    "color_family": {"values": COLOR_FAMILIES, "multi": False, "weight": 1.0},
    "color_tone": {"values": COLOR_TONES, "multi": False, "weight": 1.0},
    "pattern": {"values": PATTERNS, "multi": False, "weight": 1.0},
    "fit": {"values": FITS, "multi": False, "weight": 0.9},
    "formality": {"values": list(FORMALITY_BUCKETS.values()), "multi": False, "weight": 0.8},
    "loudness": {"values": LOUDNESS, "multi": False, "weight": 0.9},
    "material": {"values": MATERIALS, "multi": False, "weight": 0.5},
    "occasions": {"values": OCCASIONS, "multi": True, "weight": 0.6},
    "category": {"values": CATEGORIES, "multi": False, "weight": 0.4},
}

LABELS: dict[str, str] = {
    "smart_casual": "smart casual", "classic_formal": "classic formal", "indo_western": "Indo-western",
    "vintage_retro": "vintage / retro", "rugged_outdoor": "rugged / outdoor", "party_statement": "party / statement",
    "brown_tan": "brown / tan", "beige_cream": "beige / cream", "red_maroon": "red / maroon",
    "yellow_mustard": "mustard / yellow", "orange_rust": "orange / rust", "graphic_print": "graphic print",
    "allover_print": "all-over print", "not_applicable": "n/a", "date_night": "date night",
    "very_casual": "very casual", "silk_blend": "silk blend",
}


def label(value: str) -> str:
    return LABELS.get(value, value.replace("_", " "))


def item_values(item: dict[str, Any], dim: str) -> list[str]:
    """The values an item has for a dimension, as a list."""
    if dim == "formality":
        return [FORMALITY_BUCKETS[item["formality"]]]
    value = item[dim]
    return list(value) if isinstance(value, list) else [value]
