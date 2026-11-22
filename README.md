# Black Friday Deals Intelligence

Public tracker of Black Friday / White Friday 2026 promotions for beauty, skincare and fashion stores in the United States and Saudi Arabia.

- `index.html` – the site (GitHub Pages, no build step). It loads `data.json` and refreshes every 5 minutes.
- `data.json` – the deals data, exported from the tracker's database by the scheduled monitoring runs.
- `tools/apply_patch.py` – merges a run's changes into `data.json`.

Every deal records its source; stores without a confirmed offer are shown as *Verifying* or *Not announced*.

## Self-Portrait Black Friday Edit (`/self-portrait/`)

Private (passcode-gated) tracker of discounted midi dresses on Self-Portrait Spain (eu.self-portrait.com/es-es).

- `self-portrait/index.html` – the boutique-style site. Final price = discounted € × EUR/SAR + 450 SAR per dress (adjustable in Admin).
- `self-portrait/data.json` – products, sizes and rate, written by `tools/sp_update.py`.
- `.github/workflows/self-portrait-update.yml` – checks the store every 30 minutes (and on demand) and commits changes.
- `self-portrait/personal.json` – favorites, notes and edits, only if sync is turned on in Admin.

## Friday Index (`/friday-index/`)

Public Black Friday / White Friday 2026 deals hub for the USA and Saudi Arabia across 14 shopping categories.

- `friday-index/index.html` – the site (no build step). Loads `friday-index/data.json` and refreshes every 5 minutes.
- `friday-index/data.json` – exported from the Friday Index database (claude.ai artifact) by a scheduled publish task.
- `tools/fi_patch.py` – merges a publish run's changes into `friday-index/data.json`.
