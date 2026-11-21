# Black Friday Deals Intelligence

Public tracker of Black Friday / White Friday 2026 promotions for beauty, skincare and fashion stores in the United States and Saudi Arabia.

- `index.html` – the site (GitHub Pages, no build step). It loads `data.json` and refreshes every 5 minutes.
- `data.json` – the deals data, exported from the tracker's database by the scheduled monitoring runs.
- `tools/apply_patch.py` – merges a run's changes into `data.json`.

Every deal records its source; stores without a confirmed offer are shown as *Verifying* or *Not announced*.
