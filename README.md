# fashion-ai

Local web app: your photos + a 5-card vibe check + a swipe deck -> a taste profile (what you like) and a stylist's read (what suits you) -> three detailed looks -> images of you wearing them.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env   # fill in OPENAI_API_KEY and GEMINI_API_KEY (Gemini needs billing enabled)
.\.venv\Scripts\python.exe build_catalog.py   # one-time: builds the swipe deck (~15-40 min, ~$0.17)
```

## Run

```powershell
.\.venv\Scripts\python.exe app.py      # prints a computer URL and a phone URL
```

**On your phone:** join the same Wi-Fi as the PC and open the printed `http://192.168.x.x:8000`. If it doesn't load, Windows Firewall is blocking it: set the Wi-Fi network to *Private* (Settings > Network & internet > Wi-Fi > your network) and allow Python when Windows asks. To install it like an app, use your browser's menu and choose *Add to Home screen*. Set `HOST=127.0.0.1` in `.env` to keep it on this computer only.

## Flow

One screen at a time: `#/` upload, `#/vibe/1-5`, `#/swipe`, `#/taste`, `#/designing`, `#/looks`. Refreshing resumes where you left off.

1. **Photos**: upload 1-10 photos or take one with the camera. Phones downscale before upload; the server fixes rotation, converts HEIC and keeps them per session in `out/uploads/<session>/`. With one photo, it's also the render reference.
2. **Vibe check**: 5 big picture-card questions (vibe, occasions, fit, colors, loudness). Answers give the recommender a head start.
3. **Swipe**: a dating-app-style deck of real menswear products. Drag, use the buttons, or press ← → ↑ (Backspace undoes). No API calls.
   - Each item carries attributes: category, styles, color family, color tone, pattern, fit, formality, loudness, material, occasions.
   - `recommender.py` keeps a Beta belief per attribute value and updates it on every swipe. It picks the next card by mixing exploration (Thompson sampling) with exploitation (best predicted), so the deck drifts toward your taste while still testing uncertain attributes.
   - While you swipe, the **photo analysis** (`analysis.py`, gpt-5 vision) runs in the background. It produces a prose read of you, what suits you (colors, collars, fits, eyewear, accessories), flags on what you currently wear, and the best **reference photo** (you can click a different one).
4. **Taste × suitability**: learned likes and dislikes with evidence counts, next to the stylist's notes.
5. **Looks** (`styles.py`, gpt-5 vision): photos + vibe + taste profile (including the loved, liked and passed items) + stylist notes -> 3 looks with every piece, eyewear, accessories, grooming, palette and a render prompt.
6. **Render** (`render.py`): one reference photo + a look -> image. "Both" renders with `gemini-3.1-flash-image` and `gemini-3-pro-image` side by side.

Paid calls only run when you act. Regenerating needs a second click, and replaced output is moved to `out/archive/`. **Preview prompt** buttons show exactly what would be sent.

## Catalog

`build_catalog.py` samples ~300 menswear items from the public Myntra *Fashion Product Images* dataset (900x1200 mirror on Hugging Face). It reads only the metadata columns, downloads just the chosen images, and tags each with `gpt-5-mini`, dropping unclear photos. Quotas per article type are in `config.py`. It's resumable: re-run it to fill in failed downloads or untagged items; `--skip-download` tags only what's on disk. **Check the dataset's license before using it beyond a local prototype.**

## Files

| Path | What |
|---|---|
| `config.py` | all model names, prices, quotas, limits, paths |
| `app.py` | FastAPI server + JSON API |
| `attributes.py` | attribute vocabulary + recommender dimension weights |
| `intake.py` | the 5 picture questions and how answers seed the recommender |
| `recommender.py` | swipe-deck learning, card selection, taste profile |
| `analysis.py`, `styles.py`, `render.py` | the three paid calls |
| `build_catalog.py` | one-time catalog builder |
| `static/` | the page |
| `data/catalog/catalog.json` | tagged deck (images in `data/catalog/images/`) |
| `out/session.json` | intake answers, swipes, reference choice, render results |
| `out/analysis.json`, `out/styles.json`, `out/looks/` | model outputs |
| `out/run_log.json` | every API call with timestamp, model, tokens and estimated cost |
| `out/raw/` | raw API responses whenever output is unparseable or rejected |

## Notes

- Render prompt wording matters: phrases like "real person" or "recognizable as the same individual" make Gemini return `IMAGE_OTHER` with no image. Empty responses are retried once.
- Cost figures are estimates from `config.py` prices.
