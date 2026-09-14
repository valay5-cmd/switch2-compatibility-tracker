# Switch 2 Compatibility Tracker — proof of concept

A small Python/Playwright proof of concept for monitoring Nintendo's official Switch 2 compatibility detail pages.

## First goal

Start with a small hand-maintained list of title IDs. The scraper saves the visible page text and a normalized status, then compares it with the previous run. Once this is validated against Nintendo's current site, we can add automatic game discovery and a richer frontend.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python scraper.py
```

Then open `index.html`.

## Data files

- `data/games.json` — games to check
- `data/current.json` — latest snapshot
- `data/history.json` — detected changes

## Automation

`.github/workflows/check.yml` runs the scraper twice per day initially and commits changed data back to the repository.

## Next development step

Validate the parser against several real Nintendo records. Do not scale to the entire catalog until the extracted status/details are confirmed to match Nintendo's UI.
