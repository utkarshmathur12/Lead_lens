# LeadLens: acquisition lead triage

> A companion to SaaSquatch for searchers and acquisition entrepreneurs. SaaSquatch finds companies; **LeadLens decides which ones deserve your next hour**, and shows its work.

Built for the Caprae Capital Full Stack Developer challenge (5-hour build).

**Live demo:** https://lead-lens.onrender.com (the first load can take about a minute; click "Load synthetic sample" to start)

## The problem I chose

SaaSquatch-style tools return long lists. The expensive part for a searcher is what comes next: cleaning the export, spotting duplicates, working out which owner-led businesses are actually worth a call, and writing the outreach. A public G2 review of SaaSquatch also notes that filtering can take up to a minute. So I went deep on one thing (the **quality-first** option in the brief): **fast, explainable lead prioritization.**

## What it does

| Feature | Why it matters to a searcher |
|---|---|
| **Smart CSV import**: auto-maps messy headers (`Company Name`, `Estimated Revenue`, `Reviews`…), normalizes phones, states, domains, `$2.5M` / `800k` / `1-3M` money formats | Works with exports from SaaSquatch, Apollo, Google Maps scrapes, or a spreadsheet |
| **Duplicate removal + merge**: same domain, same name+state, or fuzzy match (blocked by state + first word); keeps the richest record and back-fills gaps. "Acme 1" and "Acme 2" are never merged | Stops you cold-calling the same owner twice |
| **Explainable ICP scoring (0-100)** across industry, size, succession signals, geography, reachability and reputation, with per-category notes | Every rank has a reason you can read, so you can trust it or tune it |
| **Editable target profile**: change industries, size, states, tenure and every lead re-scores instantly (~0.5 s for 12k leads) | Different searchers hunt different targets |
| **Tiers A-D, data-confidence %, risk flags** (franchise signals, invalid email, generic-only email) | Work top-down; know when a score rests on thin data |
| **Opt-in website enrichment**: pulls emails, phones, "since 19xx" and family-owned language from the company's own site, then re-scores | Fills the gaps that block outreach |
| **Outreach drafts** (email + call opener) personalised from the same signals | Removes the blank-page step |
| **Status pipeline + filtered CSV export** with a "why" column | Hand a ranked list straight to a CRM or cold-caller |

## Quick start

```bash
git clone https://github.com/utkarshmathur12/Lead_lens.git && cd Lead_lens
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/generate_sample_data.py                 # optional: regenerate the synthetic dataset
uvicorn app.main:app --reload
# open http://localhost:8000 and click "Load synthetic sample"
```

Run the tests: `python -m pytest -q` (8 tests: parsers, dedupe, scoring, API end-to-end, SSRF protection).

Docker: `docker build -t leadlens . && docker run -p 8000:8000 -v leadlens-data:/data leadlens`

## Dataset

`data/sample_leads.csv` is **fully synthetic** (300 rows, seed 42): no real businesses or people. It deliberately includes duplicates with spelling drift, mixed number formats, invalid and generic emails, missing fields and franchise look-alikes, so the cleaning and scoring are visible. All `.example` domains are non-routable.

## Measured performance (12,000 rows, single process, SQLite)

| Operation | Result |
|---|---|
| Import + normalize + dedupe + score | ~1 s |
| Filtered / sorted / searched list query | 6-10 ms |
| Change target profile and re-score everything | ~0.5 s |

(Measured on my dev sandbox. Your numbers will vary.)

## Design decisions

- **Explainability over a black box.** Each score returns a breakdown with human-readable notes. A searcher will only act on a ranking they understand.
- **Missing data isn't treated as bad data.** Unknown fields get a neutral partial score, and a separate *confidence* figure shows how complete the record is.
- **Succession signals** (named owner, long tenure, "family owned" language) are weighted explicitly, because owner-led businesses with long-tenured founders are the typical acquisition thesis.
- **Honest limits:** scoring is a transparent heuristic, not a trained model. There is no ground-truth deal data in this project, so weights are defaults the user is expected to tune.

## Architecture (details in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))

FastAPI (Python) + SQLite (WAL) + a single-file vanilla JS front end. Server-side filtering with indexed columns; stats cached in memory and invalidated on writes. One container, deployable to Render / Fly.io / Cloud Run with a persistent volume.

## Ethics and safety

- Enrichment is **opt-in per lead**, honours `robots.txt`, identifies itself with a User-Agent, fetches at most two pages, and only reads contact info the company publishes itself.
- **SSRF protection:** refuses non-http(s) URLs and any host resolving to a private/loopback/link-local address, including after redirects (tested).
- All CSV-derived text is HTML-escaped in the UI. Uploads are capped at 10 MB.
- Outreach drafts are honest by design: they say who is writing, make no false claims, and are clearly editable before sending. Comply with CAN-SPAM, GDPR and do-not-call rules when contacting people.

## Roadmap (what I'd do with more time)

1. Pull candidates directly from SaaSquatch/Apollo APIs instead of CSV.
2. Learn weights from closed/won outcomes (logistic regression) once deal history exists.
3. CRM push (HubSpot / Pipedrive) and email-verification (MX/SMTP) checks.
4. LLM-assisted outreach personalisation, with the template as the safe fallback.
5. Auth + multi-user workspaces, Postgres for concurrent writers.
