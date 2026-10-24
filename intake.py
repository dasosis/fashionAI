"""The five picture-card intake questions, and how each answer seeds the recommender."""

from typing import Any

# Each option carries:
#   priors: (dimension, value) pairs the recommender starts out favoring when this option is picked
#   image:  {"match": {...}} picks a catalog photo with those attributes; {"swatch": [...]} draws colors
INTAKE_QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "vibe", "type": "multi", "max": 3,
        "question": "What's your vibe?", "subtitle": "Pick up to three.",
        "options": [
            {"value": "streetwear", "label": "Streetwear", "priors": [("styles", "streetwear")],
             "image": {"match": {"styles": "streetwear", "category": ["top", "outerwear"]}}},
            {"value": "minimal", "label": "Minimal & clean", "priors": [("styles", "minimal")],
             "image": {"match": {"styles": "minimal", "category": ["top", "outerwear"], "pattern": "solid"}}},
            {"value": "smart_casual", "label": "Smart casual", "priors": [("styles", "smart_casual"), ("styles", "preppy")],
             "image": {"match": {"styles": "smart_casual", "category": ["top", "outerwear"]}}},
            {"value": "classic_formal", "label": "Sharp & formal", "priors": [("styles", "classic_formal")],
             "image": {"match": {"styles": "classic_formal", "category": ["top", "outerwear"]}}},
            {"value": "ethnic", "label": "Ethnic & Indo-western", "priors": [("styles", "ethnic"), ("styles", "indo_western")],
             "image": {"match": {"category": ["ethnic"]}}},
            {"value": "athleisure", "label": "Sporty & athleisure", "priors": [("styles", "athleisure")],
             "image": {"match": {"styles": "athleisure", "category": ["top", "footwear"]}}},
            {"value": "rugged", "label": "Rugged & vintage", "priors": [("styles", "rugged_outdoor"), ("styles", "vintage_retro")],
             "image": {"match": {"styles": ["rugged_outdoor", "vintage_retro"], "category": ["outerwear", "top", "footwear"]}}},
            {"value": "party", "label": "Party & statement", "priors": [("styles", "party_statement")],
             "image": {"match": {"styles": "party_statement"}}},
        ],
    },
    {
        "id": "occasions", "type": "multi", "max": 6,
        "question": "Where will you wear it?", "subtitle": "Pick all that apply.",
        "options": [
            {"value": "everyday", "label": "Everyday & college", "priors": [("occasions", "everyday")],
             "image": {"match": {"occasions": "everyday", "category": ["top"]}}},
            {"value": "work", "label": "Work", "priors": [("occasions", "work")],
             "image": {"match": {"occasions": "work", "category": ["top", "bottom", "outerwear"]}}},
            {"value": "date_night", "label": "Dates & nights out", "priors": [("occasions", "date_night")],
             "image": {"match": {"occasions": "date_night", "category": ["top", "outerwear", "footwear"]}}},
            {"value": "festive", "label": "Festive & weddings", "priors": [("occasions", "festive")],
             "image": {"match": {"occasions": "festive"}}},
            {"value": "travel", "label": "Travel & weekends", "priors": [("occasions", "travel")],
             "image": {"match": {"occasions": "travel"}}},
            {"value": "sport", "label": "Gym & sport", "priors": [("occasions", "sport")],
             "image": {"match": {"occasions": "sport"}}},
        ],
    },
    {
        "id": "fit", "type": "single",
        "question": "How do you like things to fit?", "subtitle": "Pick one.",
        "options": [
            {"value": "slim", "label": "Slim & fitted", "priors": [("fit", "slim")],
             "image": {"match": {"fit": "slim", "category": ["top", "bottom"]}}},
            {"value": "regular", "label": "Regular", "priors": [("fit", "regular")],
             "image": {"match": {"fit": "regular", "category": ["top", "bottom"]}}},
            {"value": "relaxed", "label": "Relaxed & oversized", "priors": [("fit", "relaxed"), ("fit", "oversized")],
             "image": {"match": {"fit": ["relaxed", "oversized"], "category": ["top", "bottom", "outerwear"]}}},
        ],
    },
    {
        "id": "colors", "type": "multi", "max": 6,
        "question": "Which colors pull you in?", "subtitle": "Pick all that apply.",
        "options": [
            {"value": "neutrals", "label": "Black, white & grey",
             "priors": [("color_tone", "neutral"), ("color_family", "black"), ("color_family", "white"), ("color_family", "grey")],
             "image": {"swatch": ["#111111", "#f4f4f2", "#8e8e8e"]}},
            {"value": "earth", "label": "Earth tones",
             "priors": [("color_tone", "earth"), ("color_family", "olive"), ("color_family", "brown_tan"), ("color_family", "beige_cream")],
             "image": {"swatch": ["#5b6236", "#9a6b3f", "#d9c7a7"]}},
            {"value": "blues", "label": "Navy & blues",
             "priors": [("color_tone", "cool"), ("color_family", "navy"), ("color_family", "blue")],
             "image": {"swatch": ["#1c2b4a", "#3f6fb5", "#9fb8d9"]}},
            {"value": "dark", "label": "Dark & moody",
             "priors": [("color_tone", "dark"), ("color_family", "black"), ("color_family", "red_maroon")],
             "image": {"swatch": ["#0d0d0d", "#3b1a22", "#1f2a24"]}},
            {"value": "bright", "label": "Bold brights",
             "priors": [("color_tone", "bright"), ("color_family", "yellow_mustard"), ("color_family", "red_maroon"), ("color_family", "orange_rust")],
             "image": {"swatch": ["#e0a100", "#c8322b", "#1f8f5f"]}},
            {"value": "pastel", "label": "Soft pastels",
             "priors": [("color_tone", "pastel"), ("color_family", "pink")],
             "image": {"swatch": ["#f2c6cf", "#c9e2d3", "#cdd6f2"]}},
        ],
    },
    {
        "id": "boldness", "type": "single",
        "question": "How loud do you go?", "subtitle": "Pick one.",
        "options": [
            {"value": "subtle", "label": "Clean & subtle", "priors": [("loudness", "subtle"), ("pattern", "solid")],
             "image": {"match": {"loudness": "subtle", "pattern": "solid", "category": ["top"]}}},
            {"value": "moderate", "label": "A little pattern", "priors": [("loudness", "moderate"), ("pattern", "stripes"), ("pattern", "checks")],
             "image": {"match": {"pattern": ["stripes", "checks"], "category": ["top"]}}},
            {"value": "statement", "label": "Statement pieces",
             "priors": [("loudness", "statement"), ("pattern", "graphic_print"), ("pattern", "allover_print"), ("pattern", "colorblock")],
             "image": {"match": {"loudness": "statement", "category": ["top", "outerwear", "footwear"]}}},
        ],
    },
]


def _matches(item: dict[str, Any], match: dict[str, Any]) -> bool:
    for key, wanted in match.items():
        wanted_set = set(wanted) if isinstance(wanted, list) else {wanted}
        have = item[key] if isinstance(item[key], list) else [item[key]]
        if not wanted_set & set(have):
            return False
    return True


def _purity(item: dict[str, Any], match: dict[str, Any]) -> float:
    """How clearly an item represents a style option: primary style matches, few other styles, draws attention."""
    wanted = match.get("styles")
    if wanted is None:
        return 0.0
    wanted_set = set(wanted) if isinstance(wanted, list) else {wanted}
    primary = 2.0 if item["styles"][0] in wanted_set else 0.0
    return primary - 0.5 * (len(item["styles"]) - 1) + (0.5 if item["loudness"] != "subtle" else 0.0)


def questions_with_images(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Intake questions for the UI, with each picture option resolved to a catalog image (no priors exposed)."""
    used: set[int] = set()
    out = []
    for q in INTAKE_QUESTIONS:
        options = []
        for opt in q["options"]:
            image = opt["image"]
            resolved: dict[str, Any] = {}
            if "swatch" in image:
                resolved = {"swatch": image["swatch"]}
            else:
                candidates = sorted((it for it in catalog if _matches(it, image["match"]) and it["id"] not in used),
                                    key=lambda it: (-_purity(it, image["match"]), -it["image_quality"], it["id"]))
                if candidates:
                    used.add(candidates[0]["id"])
                    resolved = {"src": f"/catalog/{candidates[0]['image']}"}
            options.append({"value": opt["value"], "label": opt["label"], "image": resolved})
        out.append({k: v for k, v in q.items() if k != "options"} | {"options": options})
    return out


def priors(answers: dict[str, Any]) -> list[tuple[str, str]]:
    """(dimension, value) pairs to favor, from answers[question_id] = [selected values]."""
    pairs = []
    for q in INTAKE_QUESTIONS:
        selected = set(answers.get(q["id"]) or [])
        for opt in q["options"]:
            if opt["value"] in selected:
                pairs += opt["priors"]
    return pairs


def answers_text(answers: dict[str, Any]) -> str:
    lines = []
    for q in INTAKE_QUESTIONS:
        labels = [o["label"] for o in q["options"] if o["value"] in set(answers.get(q["id"]) or [])]
        lines.append(f"- {q['question']} {', '.join(labels) if labels else '(no answer)'}")
    return "\n".join(lines)
