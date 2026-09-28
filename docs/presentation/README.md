# Presentation deck

`ClaimsWatch.pptx` (editable) and `ClaimsWatch.pdf` (export) are generated; do not edit them by hand.

- `deck_data.json` is the single source for the deck: slide copy (as templates), the image path and crop for each slide, and a `facts` section with every number, summary and log line shown.
- `evidence/` holds the raw outputs the facts come from (replay benchmark for seeds 2026 and 1-8, test counts, a masked log line, and an alert read back from SNS via moto). `evidence/make_evidence.py` re-runs them and rewrites `facts`.
- `build_deck.py` turns `deck_data.json` into the PPTX (python-pptx). Colours and fonts match `frontend/src/theme.ts`.

Regenerate (fonts: Inter and JetBrains Mono installed so the PDF embeds them):

```bash
PYTHONPATH=backend:tools backend/.venv/bin/python docs/presentation/evidence/make_evidence.py  # optional: --tests, --sns
pip install python-pptx pillow && python docs/presentation/build_deck.py
soffice --headless --convert-to pdf --outdir docs/presentation docs/presentation/ClaimsWatch.pptx
```

To swap in new screenshots or benchmark numbers, change `deck_data.json` (image paths, or a new table under `facts` referenced by the results slide's `"table"` key) and rebuild.
