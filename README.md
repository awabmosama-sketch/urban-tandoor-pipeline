# Urban Tandoor & Grill — Menu & Inventory API

Data engineering pipeline that ingests two Excel workbooks and a DOCX restaurant
profile into a Neon PostgreSQL database (with `pgvector`), then serves the data
through an async FastAPI application with menu, inventory, availability,
semantic-search and admin-refresh endpoints.

All data is **synthetic demo data**. The three source files live in `data/`.

---

## Architecture

```
                         ┌──────────────────────────────────────────┐
                         │              data/ (sources)             │
                         │  Menu catalog .xlsx                      │
                         │  Inventory dataset .xlsx                 │
                         │  Restaurant profile .docx                │
                         └──────────────────┬───────────────────────┘
                                            │
                       ┌────────────────────▼─────────────────────┐
                       │        Ingestion layer (async)           │
                       │  app/ingestion/excel_menu.py             │
                       │  app/ingestion/excel_inventory.py        │
                       │  app/ingestion/docs_pipeline.py          │
                       │  chunker + embedder (1536-d vectors)     │
                       └────────────────────┬─────────────────────┘
                                            │ idempotent upserts
                       ┌────────────────────▼─────────────────────┐
                       │     PostgreSQL (Neon) + pgvector         │
                       │  20 tables · HNSW index · GIN indexes    │
                       └────────────────────┬─────────────────────┘
                                            │ async SQLAlchemy 2.x
                       ┌────────────────────▼─────────────────────┐
                       │           FastAPI application            │
                       │  RequestID · CORS · GZip middleware      │
                       │  /health                                 │
                       │  /api/v1/menu/...                        │
                       │  /api/v1/inventory/...                   │
                       │  /api/v1/search/...                      │
                       │  /api/v1/admin/...   (X-Admin-Token)     │
                       └──────────────────────────────────────────┘
```

---

## Features

- **Menu domain** — 8 categories, 118 menu items, 148 variants, addons,
  aliases (English + Roman Urdu), branch menus, deals, allergen guide and
  service rules.
- **Inventory domain** — 7 suppliers, 60 ingredients, 2 branches, 120 branch
  stock rows, 130 recipes and stock movements. Computed `on_hand`,
  `available`, `stock_status`, `suggested_buy` and `stock_value_pkr`.
- **Availability engine** — per-item, per-branch portion availability derived
  from recipe requirements and live stock, with the limiting ingredient
  identified.
- **Document pipeline** — DOCX profile + one narrative chunk per menu item,
  split into chunks with configurable size/overlap and embedded as
  `VECTOR(1536)`.
- **Semantic search** — cosine-distance ranking (`<=>`), min-score filtering,
  pagination, document listing and index health.
- **Admin refresh** — background, non-blocking refreshes per domain
  (`menu | inventory | docs | all`) with an in-memory job lifecycle
  (`pending → running → success | error`) protected by `X-Admin-Token`.
- **Hand-built frontend** — a dependency-free, paper-and-ember kitchen ledger
  served at `/ui/`: menu passport drawer, live portion gauge, semantic archive
  search, kitchen ops drawer and a grounded AI concierge.
- **AI concierge** — Groq chat completions grounded in the live menu, branches
  and branch stock. The API key stays server-side; the browser only calls
  `/api/v1/assistant/chat`.
- **Operational hygiene** — request IDs, CORS, gzip, DB-backed health check,
  structured OpenAPI docs.

---

## Project layout

```
urban-tandoor-pipeline/
├── alembic/                  # migrations (async env.py)
├── app/
│   ├── api/
│   │   ├── deps.py           # SessionDep
│   │   ├── middleware.py     # RequestID / CORS / GZip
│   │   └── routes/           # health, menu, inventory, search, admin
│   ├── ingestion/            # excel, docs, chunker, embedder, CLI helpers
│   ├── models/               # SQLModel tables (menu, inventory, documents)
│   ├── schemas/              # Pydantic response/request DTOs
│   ├── services/             # availability, search, jobs, refresh, assistant
│   ├── static/               # hand-built frontend (HTML/CSS/JS)
│   ├── config.py             # pydantic-settings
│   ├── database.py           # async engine + session factory
│   └── main.py               # FastAPI app + lifespan
├── data/                     # source workbooks + DOCX
├── scripts/                  # ingest CLI + phase self-checks
├── tests/                    # pytest suite
├── .env.example
├── alembic.ini
├── pyproject.toml
└── README.md
```

---

## Quick start

### 1. Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- A PostgreSQL database with the `vector` extension available
  (Neon works out of the box)

### 2. Install

```bash
uv sync
```

### 3. Configure

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Edit `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | `dev` | `dev` enables SQL echo; use `test` for quiet runs |
| `DATABASE_URL` | local Postgres | Pooled asyncpg URL used by the app |
| `EMBEDDING_PROVIDER` | `openai` | `openai`, `gemini` or `fake` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Provider model name |
| `EMBEDDING_DIM` | `1536` | Must match the `VECTOR(n)` column |
| `OPENAI_API_KEY` | — | Required when provider is `openai` |
| `GEMINI_API_KEY` | — | Required when provider is `gemini` |
| `DATA_DIR` | `./data` | Source files directory |
| `CHUNK_SIZE` | `800` | Document chunk size (characters) |
| `CHUNK_OVERLAP` | `120` | Chunk overlap (characters) |
| `ADMIN_TOKEN` | `change-me` | Shared secret for admin endpoints |
| `ADMIN_JOB_MAX_HISTORY` | `100` | In-memory job retention |
| `GROQ_API_KEY` | — | Server-side key for the AI concierge (never sent to the browser) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq chat model used by the concierge |

> The app connects through the pooled Neon host. Alembic strips `-pooler`
> from the host automatically so migrations use a direct connection.

For deterministic offline development use:

```env
EMBEDDING_PROVIDER=fake
```

`FakeEmbedder` produces deterministic hash-based vectors. Retrieval structure
is testable, but semantic relevance is **not** meaningful with this provider.

### 4. Migrate

```bash
uv run alembic upgrade head
```

### 5. Ingest

```bash
uv run utg-ingest                 # all domains
uv run utg-ingest --only menu     # menu only
uv run utg-ingest --only inventory
uv run utg-ingest --only docs
uv run utg-ingest --strict        # fail fast on any domain error
uv run utg-ingest --wipe --yes    # destructive clean reload
```

Ingestion is idempotent: rerunning updates rows in place and regenerates
document chunks only when the source checksum changes.

### 6. Run the API

```bash
uv run uvicorn app.main:app --reload
```

- Swagger UI: <http://127.0.0.1:8000/docs>
- OpenAPI: <http://127.0.0.1:8000/openapi.json>
- Health: <http://127.0.0.1:8000/health>
- API index: <http://127.0.0.1:8000/api/v1/>
- Frontend: <http://127.0.0.1:8000/ui/>

### 7. Frontend

The interface is plain HTML, CSS and JavaScript under `app/static/` — no build
step, no npm, no CDN dependencies at runtime. FastAPI serves it directly:

```text
GET /        → 307 redirect to /ui/
GET /ui/     → the ledger
```

It reads the existing read APIs: `/menu/*`, `/inventory/*`, `/search/*` and
`/admin/*`. The Ops drawer in the lower-right sends the admin token you type in
the browser (default `change-me`) and polls the refresh job.

The concierge sends chat turns to `POST /api/v1/assistant/chat`. That route
injects `GROQ_API_KEY` server-side and returns only the reply, so the key is
never present in the HTML, CSS, JS or browser network traffic. To disable the
concierge, leave `GROQ_API_KEY` empty; the route returns `503` and the rest of
the UI keeps working.

---

## API reference

### Health

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | App + DB status, version, request ID |
| `GET` | `/api/v1/` | Service metadata and endpoint index |

### Menu

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/menu/categories` | All 8 categories |
| `GET` | `/api/v1/menu/items` | Items; defaults to `catalog_status=Active` |
| `GET` | `/api/v1/menu/items/{menu_id}` | Item with variants + addons |
| `GET` | `/api/v1/menu/items/{menu_id}/variants` | Variants ordered by price |
| `GET` | `/api/v1/menu/items/{menu_id}/addons` | Addons with selectability |
| `GET` | `/api/v1/menu/aliases?phrase=...` | Alias search (substring) |

Menu item filters: `category`, `q` (name search), `catalog_status`
(`Active` by default, or `all`).

### Inventory

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/inventory/branches` | Branch profiles |
| `GET` | `/api/v1/inventory/branches/{branch_id}/stock` | 60 stock rows |
| `GET` | `/api/v1/inventory/branches/{branch_id}/stock/{ingredient_id}` | One row |
| `GET` | `/api/v1/inventory/availability/{menu_id}?branch_id=...` | Portion availability |
| `GET` | `/api/v1/inventory/branches/{branch_id}/availability` | Bulk availability |

### Search

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/search/semantic` | Body: `query`, `top_k`, `min_score` |
| `GET` | `/api/v1/search/semantic?q=...&k=...` | Query-string equivalent |
| `GET` | `/api/v1/search/health` | Chunk/index statistics |
| `GET` | `/api/v1/search/documents` | Source documents + chunk counts |

Results are ordered by cosine similarity descending
(`similarity = 1 - cosine_distance`), rounded to 6 decimal places.

### Admin

All admin routes require the header `X-Admin-Token`.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/admin/refresh/{domain}` | Enqueue refresh; returns `202` + job |
| `GET` | `/api/v1/admin/jobs/{job_id}` | Job status/result |
| `GET` | `/api/v1/admin/jobs?limit=20` | Recent jobs (1–100) |

Valid domains: `menu`, `inventory`, `docs`, `all`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admin/refresh/menu \
  -H "X-Admin-Token: change-me"

curl http://127.0.0.1:8000/api/v1/admin/jobs/<job_id> \
  -H "X-Admin-Token: change-me"
```

Jobs are stored in memory and are lost on restart. Refresh runs in the
background on the FastAPI event loop; poll the job endpoint for completion.

### Assistant

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/assistant/chat` | Grounded restaurant chat via Groq |

Request body:

```json
{
  "message": "What should I order for two?",
  "history": [{ "role": "user", "content": "I like smoky food." }],
  "branch_id": "BR-01"
}
```

`history` is optional (max 12 turns, the server uses the last 8) and
`branch_id` is optional. The service rebuilds a compact snapshot of the active
menu, branches and low-stock lines for that branch and puts it in the system
prompt, so answers stay tied to the demo data. Travels as `502`/`503`/`504` when
Groq is unreachable, unconfigured or slow.

---

## Data model (20 tables)

| Group | Tables |
| --- | --- |
| Menu | `categories`, `menu_items`, `variants`, `addons`, `item_addons`, `item_aliases`, `branch_menu`, `inventory_links`, `deals`, `deal_items`, `allergen_guide`, `service_rules` |
| Inventory | `suppliers`, `ingredients`, `branches`, `branch_stock`, `recipes`, `stock_movements` |
| Documents | `source_documents`, `document_chunks` (`VECTOR(1536)`, JSONB metadata) |

Baseline row counts:

```
suppliers       7    categories      8    source_documents    2
ingredients    60    menu_items    118    document_chunks   128
branches        2    variants      148
branch_stock  120    addons         10
recipes       130    item_addons   284
stock_movements 8    item_aliases  158
                     branch_menu   236
                     inventory_links 236
                     deals           6
                     deal_items     15
                     allergen_guide  8
                     service_rules   7
```

Indexes include an HNSW cosine index on `document_chunks.embedding` and GIN
indexes on JSONB metadata columns.

---

## Testing

```bash
uv run pytest -q
```

Coverage by file:

| File | Scope |
| --- | --- |
| `tests/test_health.py` | Health, request IDs, API index, OpenAPI |
| `tests/test_ingestion.py` | Workbook-derived row counts, computed stock fields, spot checks |
| `tests/test_menu_api.py` | Menu categories/items/variants/addons/aliases |
| `tests/test_inventory_api.py` | Branches and stock endpoints |
| `tests/test_availability.py` | Exact portion math (including limiting ingredient) |
| `tests/test_search_api.py` | Search shape, validation, ordering, determinism |
| `tests/test_admin_api.py` | Auth, lifecycle, `all` domain, concurrency |
| `tests/test_end_to_end.py` | Cross-layer journeys and refresh isolation |

Tests are read-only against the database; only admin refresh tests trigger
writes, and ingestion is idempotent so counts remain stable.

The repository also contains `scripts/_selfcheck_*.py`, one per phase, used to
verify each migration/ingestion/API milestone end to end. They are diagnostic
tools, not part of the pytest suite.

---

## Design notes

- **Async everywhere** — async SQLAlchemy 2.x engine/session, async ingestion,
  async httpx tests via `ASGITransport`.
- **No pandas `to_sql`** — ingestion uses PostgreSQL `INSERT ... ON CONFLICT
  DO UPDATE` for deterministic idempotent upserts.
- **Migration URLs** — `alembic/env.py` removes the `-pooler` suffix so
  migrations use a direct Neon connection; the API keeps the pooled URL.
- **Availability formula** — portions are the minimum across recipe lines of
  `floor(available_ingredient / qty_per_portion)`; zero/negative outcomes are
  reported as `OUT_OF_STOCK`/`NOT_ACTIVE` with a limiting ingredient where
  applicable.
- **Embeddings** — the provider is pluggable. The committed demo uses
  `fake` deterministic 1536-d vectors so the pipeline runs without API keys.
- **Job store** — in-memory singleton guarded by `asyncio.Lock`; background
  task references are retained until completion so they are not garbage
  collected mid-flight.
- **Error handling** — refresh failures are captured on the job
  (`status=error`, `error="ExceptionType: message"`) instead of crashing the
  request that enqueued them.

---

## Limitations / production notes

- The admin job store is **not persistent**; use a database table or Redis for
  multi-process deployments.
- Background refreshes use the API process event loop. In production move them
  to a worker queue (Celery/RQ/Arq) and add per-domain locking.
- `FakeEmbedder` is for development/testing only; real semantic relevance
  requires `EMBEDDING_PROVIDER=openai` or `gemini` and a re-embed of all
  chunks.
- Admin auth is a single shared token (demo). Use OAuth2/OIDC and scoped tokens
  for real deployments.
- Ingestion assumes the source workbooks keep their current sheet names and
  column headers.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `asyncpg ... attached to a different loop` | Dispose the engine between event loops (the test suite does this automatically) |
| `type "vector" does not exist` | Enable the extension: run the Phase 5 extensions migration |
| `Missing data file` | Confirm the three source files exist under `DATA_DIR` |
| `401` on admin routes | Send `X-Admin-Token` matching `ADMIN_TOKEN` |
| Search returns chunks but scores look random | Expected with `EMBEDDING_PROVIDER=fake` |
| Alembic SSL/connection errors | Verify `DATABASE_URL`; `-pooler` is stripped automatically |
