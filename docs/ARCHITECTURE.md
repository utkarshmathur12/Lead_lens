# Architecture

```
Browser (single-file HTML/JS)  ──HTTP/JSON──▶  FastAPI app  ──▶  SQLite (WAL, indexed)
                                                   │
                                                   └──▶ optional: company website (enrichment, robots-aware, SSRF-guarded)
```

## Request pipeline for an import

`CSV upload → header alias mapping → normalize (phone/state/domain/money/year) → in-file dedupe (union-find over domain, name+state, blocked fuzzy) → merge with existing rows → score → persist → invalidate stats cache`

## Modules

| Module | Responsibility |
|---|---|
| `app/validate.py` | Pure parsing/validation helpers |
| `app/dedupe.py` | Duplicate grouping and record merging |
| `app/scoring.py` | ICP config + explainable scoring engine (pure, unit-tested) |
| `app/enrich.py` | Guarded website fetch and parse |
| `app/outreach.py` | Draft generation |
| `app/db.py` | SQLite connection, schema, settings |
| `app/main.py` | REST API and static hosting |

## Data storage
**SQLite** in WAL mode (stdlib `sqlite3`, no ORM). Indexes on `score`, `tier`, `state`, `domain`, `(name_norm, state)`. The score breakdown is stored as JSON so the explanation is read, never recomputed, on list/detail. The target profile lives in a `settings` table.

## Caching and performance
- All list queries are parameterized and run in the database, where indexes and `LIMIT/OFFSET` pagination keep the browser light.
- `/api/stats` is cached in-process and invalidated on every write.
- Scoring is a pure function, so re-scoring after a profile change is a tight loop (~0.5 s for 12k rows).
- Fuzzy matching is restricted to blocks (state + first token) to avoid O(n²) comparisons.

## UX choices
- First-run empty state offers one clear action (load sample / import).
- Table is sorted by fit by default; tier chips, state, status and email filters apply live (search is debounced).
- Clicking a row opens a drawer showing *why* the score is what it is, plus the next actions: enrich, draft outreach, set status.
- Respects the user's light/dark preference; keyboard-focus-safe search re-render.

## Hosting and deployment
- **Shape:** a single stateful container (not static, not pure serverless) because it writes to SQLite.
- **Build:** the included `Dockerfile` (python:3.12-slim, uvicorn).
- **Where:** any container host with a persistent volume mounted at `/data` (`LEADLENS_DB=/data/leadlens.db`). For example Fly.io (volume), Render (disk), or Google Cloud Run + Cloud Storage FUSE / Cloud SQL if you outgrow SQLite.
- **Scaling path:** move storage to managed Postgres, run multiple stateless workers, and move the stats cache to Redis.
- **Not deployed in this submission** unless a demo link is provided in the email.

## Testing
`pytest`: parsers, dedupe (including the "numbered locations" guard), scoring behaviour, franchise/geography penalties, full API flow including re-import idempotency and ICP-triggered re-scoring, SSRF blocking, and HTML parsing.
