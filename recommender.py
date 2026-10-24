"""Swipe-deck recommender: learns taste over item attributes from likes/dislikes. No API calls.

Model: for every (dimension, value) pair, e.g. ("color_family", "olive"), keep a Beta(alpha, beta)
belief that the user likes things with that value. Intake answers add a head start to alpha.
A like adds 1 to alpha for each of the card's values, a love adds 2, a dislike adds 1 to beta.

An item's score is the weighted average, across dimensions, of its values' like-probabilities.
The next card is either exploratory or exploitative. Exploratory cards use Thompson sampling (each
probability drawn from its Beta), so uncertain attributes still get shown; exploitative cards take the
best posterior mean. The exploration rate starts at 60% and decays to 20% as swipes accumulate.
Category pacing keeps apparel, footwear and accessories mixed.
"""

import hashlib
import random
from typing import Any

import config
import intake
from attributes import DIMENSIONS, item_values, label
from common import read_json

PRIOR_STRENGTH = 2.0
VERDICT_UPDATES = {"love": (2.0, 0.0), "like": (1.0, 0.0), "dislike": (0.0, 1.0), "skip": (0.0, 0.0)}
ACCESSORY_CATEGORIES = {"eyewear", "watch", "jewelry", "bag", "headwear", "belt", "scarf"}
ACCESSORY_EVERY = 5   # every 5th card is an accessory
EXPLORE_START, EXPLORE_DECAY, EXPLORE_FLOOR = 0.6, 0.02, 0.2   # chance a card is exploratory
RECENT_WINDOW, RECENT_PENALTY = 5, 0.04   # score penalty per same-category card in the last 5

_catalog_cache: dict[str, Any] = {"mtime": None, "items": []}


def load_catalog() -> list[dict[str, Any]]:
    if not config.CATALOG_PATH.exists():
        return []
    mtime = config.CATALOG_PATH.stat().st_mtime
    if _catalog_cache["mtime"] != mtime:
        _catalog_cache.update(mtime=mtime, items=read_json(config.CATALOG_PATH)["items"])
    return _catalog_cache["items"]


def beliefs(answers: dict[str, Any], swipes: list[dict[str, Any]],
            catalog: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    """(dim, value) -> {alpha, beta, seen} where seen counts real swipes (not priors)."""
    table: dict[tuple[str, str], dict[str, float]] = {
        (dim, v): {"alpha": 1.0, "beta": 1.0, "seen": 0} for dim, spec in DIMENSIONS.items() for v in spec["values"]}
    for pair in intake.priors(answers):
        if pair in table:
            table[pair]["alpha"] += PRIOR_STRENGTH
    by_id = {it["id"]: it for it in catalog}
    for swipe in swipes:
        item = by_id.get(swipe["item_id"])
        if item is None or swipe["verdict"] == "skip":
            continue
        add_alpha, add_beta = VERDICT_UPDATES[swipe["verdict"]]
        for dim in DIMENSIONS:
            for v in item_values(item, dim):
                cell = table[(dim, v)]
                cell["alpha"] += add_alpha
                cell["beta"] += add_beta
                cell["seen"] += 1
    return table


def score(item: dict[str, Any], table: dict[tuple[str, str], dict[str, float]], rng: random.Random | None = None) -> float:
    """0..1 predicted like-probability (sampled when rng is given)."""
    total, weight_sum = 0.0, 0.0
    for dim, spec in DIMENSIONS.items():
        probs = []
        for v in item_values(item, dim):
            cell = table[(dim, v)]
            probs.append(rng.betavariate(cell["alpha"], cell["beta"]) if rng
                         else cell["alpha"] / (cell["alpha"] + cell["beta"]))
        total += spec["weight"] * sum(probs) / len(probs)
        weight_sum += spec["weight"]
    return total / weight_sum


def next_card(answers: dict[str, Any], swipes: list[dict[str, Any]], seed: str) -> dict[str, Any] | None:
    catalog = load_catalog()
    seen = {s["item_id"] for s in swipes}
    pool = [it for it in catalog if it["id"] not in seen]
    if not pool:
        return None
    position = len(swipes) + 1
    want_accessory = position % ACCESSORY_EVERY == 0
    paced = [it for it in pool if (it["category"] in ACCESSORY_CATEGORIES) == want_accessory]
    by_id = {it["id"]: it for it in catalog}
    recent = [by_id[s["item_id"]]["category"] for s in swipes[-2:] if s["item_id"] in by_id]
    if len(recent) == 2 and recent[0] == recent[1]:
        paced = [it for it in paced if it["category"] != recent[0]] or paced
    pool = paced or pool

    # Deterministic per position, so a page refresh shows the same card.
    rng = random.Random(int(hashlib.sha256(f"{seed}:{position}".encode()).hexdigest(), 16))
    table = beliefs(answers, swipes, catalog)
    # Explore early, exploit more as evidence builds. Exploring = Thompson sample; exploiting = posterior mean.
    explore = rng.random() < max(EXPLORE_FLOOR, EXPLORE_START - EXPLORE_DECAY * len(swipes))
    # Variety: categories seen in the last few cards are less likely to come up again right away.
    recent_categories = [by_id[s["item_id"]]["category"] for s in swipes[-RECENT_WINDOW:] if s["item_id"] in by_id]
    # Small nudge toward clean photos; they are easier to judge.
    return max(pool, key=lambda it: score(it, table, rng if explore else None)
               + 0.02 * (it["image_quality"] - 3)
               - RECENT_PENALTY * recent_categories.count(it["category"])
               + rng.random() * 0.01)


def taste_profile(answers: dict[str, Any], swipes: list[dict[str, Any]]) -> dict[str, Any]:
    """What the swipes say: per-dimension liked/disliked values with evidence, plus example items."""
    catalog = load_catalog()
    table = beliefs(answers, swipes, catalog)
    by_id = {it["id"]: it for it in catalog}
    dims = {}
    for dim, spec in DIMENSIONS.items():
        rows = []
        for v in spec["values"]:
            cell = table[(dim, v)]
            if cell["seen"] == 0 or v == "not_applicable":
                continue
            mean = cell["alpha"] / (cell["alpha"] + cell["beta"])
            rows.append({"value": v, "label": label(v), "score": round(mean, 3), "seen": int(cell["seen"])})
        rows.sort(key=lambda r: -r["score"])
        dims[dim] = {
            "liked": [r for r in rows if r["score"] >= 0.62 and r["seen"] >= 2],
            "disliked": [r for r in rows if r["score"] <= 0.4 and r["seen"] >= 2],
            "all": rows,
        }

    def items_with(verdicts: set[str]) -> list[dict[str, Any]]:
        return [by_id[s["item_id"]] | {"verdict": s["verdict"]} for s in swipes
                if s["verdict"] in verdicts and s["item_id"] in by_id]

    counts = {v: sum(1 for s in swipes if s["verdict"] == v) for v in VERDICT_UPDATES}
    return {"swipes": len(swipes), "counts": counts, "dimensions": dims,
            "loved": items_with({"love"}), "liked": items_with({"like"}), "disliked": items_with({"dislike"})}


def profile_text(profile: dict[str, Any]) -> str:
    """Taste profile as prompt text for the styles call."""
    lines = [f"{profile['swipes']} swipes: {profile['counts']['love']} loved, {profile['counts']['like']} liked, "
             f"{profile['counts']['dislike']} disliked."]
    for dim, d in profile["dimensions"].items():
        liked = ", ".join(f"{r['label']} ({r['score']:.2f}, n={r['seen']})" for r in d["liked"]) or "-"
        disliked = ", ".join(f"{r['label']} ({r['score']:.2f}, n={r['seen']})" for r in d["disliked"]) or "-"
        lines.append(f"- {dim}: likes {liked}; dislikes {disliked}")
    for key in ("loved", "liked", "disliked"):
        if profile[key]:
            lines.append(f"\n{key.capitalize()} items:")
            lines += [f"- {it['name']}: {it['description']}" for it in profile[key]]
    return "\n".join(lines)
