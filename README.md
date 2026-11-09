# Urban Tandoor & Grill — Menu & Inventory API

Data engineering pipeline that turns two Excel workbooks and a DOCX restaurant
profile into JSON snapshots, loads those snapshots into **MongoDB Atlas** or
**PostgreSQL (Neon)**, and serves the data through an async **FastAPI**
application with menu, inventory, availability, semantic-search and
admin-refresh endpoints.

The database backend is selected with a single `.env` flag:

```env
DB_BACKEND=postgres   # or: mongodb
```

JSON is the canonical ingestion format:

```text
Excel / DOCX  ->  data/json/<collection>.json  ->  MongoDB / PostgreSQL  ->  FastAPI
```

All data is **synthetic demo data**. The three source files live in `data/`.

---

## Architecture

```text
                         ┌──────────────────────────────────────────┐
                         │              data/ (sources)             │
                         │  Menu catalog .xlsx                      │
                         │  Inventory dataset .xlsx                 │
                         │  Restaurant profile .docx                │
                         └──────────────────┬───────────────────────┘
                                            │  utg-export / admin refresh
                         ┌──────────────────▼───────────────────────┐
                         │     JSON snapshots (canonical format)    │
                         │  data/json/categories.json               │
                         │  data/json/menu_items.json               │
                         │  ... one file per collection ...         │
                         │  data/json/document_chunks.json          │
                         └──────────────────┬───────────────────────┘
                                            │  utg-ingest / admin refresh
                         ┌──────────────────▼───────────────────────┐
                         │   MongoDB Atlas  or  PostgreSQL / Neon   │
                         │  20 collections/tables · natural keys    │
                         │  embeddings stored as float arrays       │
                         └──────────────────┬───────────────────────┘
                                            │  Motor (Mongo) / asyncpg (PG)
                         ┌──────────────────▼───────────────────────┐
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
  split into chunks with configurable size/overlap. Vectors are generated at
  import time, so the JSON stays small and readable.
- **Semantic search** — cosine similarity ranking with NumPy, min-score
  filtering, document listing and index health. Works on the Atlas free tier
  without a Vector Search index, and on Neon without the pgvector extension.
- **Admin refresh** — background, non-blocking refreshes per domain
  (`menu | inventory | docs | all`) with an in-memory job lifecycle
  (`pending → running → success | error`) protected by `X-Admin-Token`.
  A refresh re-exports the source files to JSON and re-ingests that JSON.
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

```text
urban-tandoor-pipeline/
├── app/
│   ├── api/
│   │   ├── deps.py           # DatabaseDep / SettingsDep
│   │   ├── middleware.py     # RequestID / CORS / GZip
│   │   └── routes/           # health, menu, inventory, search, admin, assistant
│   ├── ingestion/
│   │   ├── excel_menu.py     # workbook -> menu JSON
│   │   ├── excel_inventory.py# workbook -> inventory JSON
│   │   ├── docs_pipeline.py  # DOCX/narratives -> docs JSON
│   │   ├── json_store.py     # JSON read/write
│   │   ├── json_ingest.py    # JSON -> MongoDB upserts + embeddings
│   │   ├── chunker.py        # document chunking
│   │   └── embedder.py       # fake / OpenAI / Gemini providers
│   ├── schemas/              # Pydantic response/request DTOs
│   ├── services/             # availability, search, jobs, refresh, assistant (MongoDB)
│   ├── backends/
│   │   └── postgres/         # PostgreSQL / Neon backend
│   │       ├── models.py     # 20 SQLModel tables
│   │       ├── database.py   # async engine, session factory, schema bootstrap
│   │       ├── ingest.py     # JSON -> PostgreSQL upserts + embeddings
│   │       ├── routes/       # menu, inventory, search, assistant
│   │       └── services/     # availability, search, assistant (PostgreSQL)
│   ├── static/               # hand-built frontend (HTML/CSS/JS)
│   ├── collections.py        # collection names, natural keys, index specs
│   ├── config.py             # pydantic-settings
│   ├── database.py           # Motor client, database dependency, index bootstrap
│   ├── runtime.py            # DB_BACKEND dispatch (ping/schema/close)
│   └── main.py               # FastAPI app + lifespan
├── data/                     # source workbooks + DOCX
│   └── json/                 # canonical JSON snapshots (committed)
├── scripts/
│   ├── export_all.py         # utg-export CLI
│   └── ingest_all.py         # utg-ingest CLI
├── tests/                    # pytest suite (mongomock-motor, no Atlas needed)
├── .env.example
├── pyproject.toml
└── README.md
```

---

## Quick start

### 1. Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Either a **PostgreSQL 14+ / Neon** database **or** a free **MongoDB Atlas M0**
  cluster (pick one with `DB_BACKEND`)

### 2. Install

```bash
uv sync
```

### 3. Configure

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Pick the backend first:

```env
DB_BACKEND=postgres       # postgres | mongodb
```

**PostgreSQL / Neon** (`DB_BACKEND=postgres`): copy a connection string from the
Neon dashboard (or any PostgreSQL server) and force the asyncpg driver:

```env
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE?ssl=require
```

The 20 tables are created automatically (`SQLModel.metadata.create_all`) at
startup and before ingestion, so no Alembic migration step is required.

**MongoDB Atlas** (`DB_BACKEND=mongodb`): create a free cluster at
<https://www.mongodb.com/atlas>, add a database user, allow your IP (or
`0.0.0.0/0` for a throwaway demo), then copy the connection string:

```env
MONGODB_URI=mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=urban_tandoor
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `DB_BACKEND` | `mongodb` | Active backend: `mongodb` or `postgres` |
| `DATABASE_URL` | local PostgreSQL URL | Async PostgreSQL/Neon URL (`postgresql+asyncpg://...`) |
| `DATABASE_ECHO` | `false` | Log SQL statements (PostgreSQL) |
| `MONGODB_URI` | `mongodb://localhost:27017` | Atlas connection string used by the app and CLIs |
| `MONGODB_DB` | `urban_tandoor` | MongoDB database name |
| `MONGODB_TIMEOUT_MS` | `8000` | Server-selection timeout |
| `JSON_DIR` | `./data/json` | Canonical JSON snapshot directory |
| `APP_ENV` | `dev` | Free-form environment label |
| `EMBEDDING_PROVIDER` | `fake` in `.env.example` | `openai`, `gemini` or `fake` |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Provider model name |
| `EMBEDDING_DIM` | `1536` | Vector dimension stored with each chunk |
| `OPENAI_API_KEY` | — | Required when provider is `openai` |
| `GEMINI_API_KEY` | — | Reserved for the Gemini provider |
| `DATA_DIR` | `./data` | Source files directory |
| `CHUNK_SIZE` | `800` | Document chunk size (characters) |
| `CHUNK_OVERLAP` | `120` | Chunk overlap (characters) |
| `ADMIN_TOKEN` | `change-me` | Shared secret for admin endpoints |
| `ADMIN_JOB_MAX_HISTORY` | `100` | In-memory job retention |
| `GROQ_API_KEY` | — | Server-side key for the AI concierge (never sent to the browser) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq chat model used by the concierge |

For deterministic offline development keep:

```env
EMBEDDING_PROVIDER=fake
```

`FakeEmbedder` produces deterministic hash-based vectors. Retrieval structure
is testable, but semantic relevance is **not** meaningful with this provider.

### 4. Export the JSON snapshots

The repository already contains `data/json/*.json`, but you can regenerate them
from the source workbooks and DOCX at any time:

```bash
uv run utg-export                  # menu + inventory + docs
uv run utg-export --only menu
uv run utg-export --only inventory
uv run utg-export --only docs
uv run utg-export --json-dir ./tmp/json
```

### 5. Load JSON into the selected database

```bash
uv run utg-ingest                 # all domains (uses DB_BACKEND)
uv run utg-ingest --only menu     # menu only
uv run utg-ingest --only inventory
uv run utg-ingest --only docs
uv run utg-ingest --strict        # fail fast on any domain error
uv run utg-ingest --wipe --yes    # destructive clean reload
```

Ingestion is idempotent: every document/row is upserted on its natural key, so
rerunning updates data in place. Document embeddings are generated during
`utg-ingest --only docs`, not inside the JSON files. With
`DB_BACKEND=postgres`, the same JSON is upserted into the 20 PostgreSQL tables
(`INSERT ... ON CONFLICT DO UPDATE`).

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
| `GET` | `/health` | App + active database status, version, request ID |
| `GET` | `/api/v1/` | Service metadata and endpoint index |

### Menu

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/menu/categories` | All 8 categories |
| `GET` | `/api/v1/menu/items` | Items; defaults to `catalog_status=Active` |
| `GET` | `/api/v1/menu/items/{menu_id}` | Item with variants |
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

Results are ordered by cosine similarity descending, rounded to 6 decimals.
`/api/v1/search/health` reports `vector_index_present: false` because ranking
runs in the application process.

### Admin

All admin routes require the header `X-Admin-Token`.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/admin/refresh/{domain}` | Enqueue export+ingest; returns `202` + job |
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
  "branch_id": "UTG-KHI-001"
}
```

`history` is optional (max 12 turns, the server uses the last 8) and
`branch_id` is optional. The service rebuilds a compact snapshot of the active
menu, branches and low-stock lines for that branch and puts it in the system
prompt, so answers stay tied to the demo data. Returns `502`/`503`/`504` when
Groq is unreachable, unconfigured or slow.

---

## Data model (20 collections / tables)

| Group | Collections / tables |
| --- | --- |
| Menu | `categories`, `menu_items`, `variants`, `addons`, `item_addons`, `item_aliases`, `branch_menu`, `inventory_links`, `deals`, `deal_items`, `allergen_guide`, `service_rules` |
| Inventory | `suppliers`, `ingredients`, `branches`, `branch_stock`, `recipes`, `stock_movements` |
| Documents | `source_documents`, `document_chunks` (`embedding` float array, `metadata_json` JSONB/object) |

Both backends store the same fields: MongoDB uses one collection per table and
PostgreSQL uses one SQLModel table per collection.

Baseline document counts:

```text
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

Natural keys are declared in `app/collections.py` and drive idempotent upserts.
Unique indexes enforce those keys in MongoDB; the PostgreSQL schema declares the
same natural keys as primary keys. Secondary indexes cover the read paths
(branch stock, menu filters, document chunks). JSON snapshots use ISO-8601
strings for dates; the importers convert them to BSON dates or `timestamptz`.

---

## Testing

```bash
uv run pytest -q
```

The suite runs fully offline against **`mongomock-motor`** (`tests/conftest.py`
forces `DB_BACKEND=mongodb`). One in-memory database is seeded per session
through the real JSON ingestion path, so no Atlas/Neon connection or API key is
required. Embeddings are forced to the deterministic `fake` provider.

| File | Scope |
| --- | --- |
| `tests/test_health.py` | Health, request IDs, API index, OpenAPI |
| `tests/test_ingestion.py` | Workbook-derived counts, computed stock fields, spot checks |
| `tests/test_menu_api.py` | Menu categories/items/variants/addons/aliases |
| `tests/test_inventory_api.py` | Branches and stock endpoints |
| `tests/test_availability.py` | Exact portion math (including limiting ingredient) |
| `tests/test_search_api.py` | Search shape, validation, ordering, determinism |
| `tests/test_admin_api.py` | Auth, lifecycle, `all` domain, concurrency |
| `tests/test_end_to_end.py` | Cross-layer journeys and refresh isolation |

Only admin refresh tests trigger writes; ingestion is idempotent, so counts
remain stable.

---

## Design notes

- **JSON is the contract** — every write path (CLI and admin refresh) goes
  through Excel/DOCX → JSON → database. Nothing writes directly from a parser
  into the database. The same JSON feeds MongoDB or PostgreSQL.
- **One collection/table per former table** — field names are unchanged, so the
  API and frontend do not depend on the storage engine.
- **Backend selection is a single flag** — `app/runtime.py` dispatches
  ping/schema/shutdown, `app/api/routes/__init__.py` mounts the matching route
  modules, and the refresh/CLI code picks the matching ingest path.
- **Async everywhere** — Motor async client and SQLAlchemy async sessions,
  async ingestion, async httpx tests via `ASGITransport`.
- **Embeddings at import time** — `document_chunks.json` stores text and
  metadata only; `utg-ingest --only docs` embeds chunks with the configured
  provider. This keeps the committed JSON small and lets you swap providers
  without regenerating the corpus.
- **Search without a vector extension** — for the 128-chunk demo, cosine
  similarity is computed in Python/NumPy on both backends. If the corpus grows,
  replace `_rank_chunks` with MongoDB `$vectorSearch` or pgvector; the response
  contract stays the same.
- **Schema bootstrap is idempotent** — `app/database.py` creates MongoDB
  indexes; `app/backends/postgres/database.py` runs
  `SQLModel.metadata.create_all` for the 20 tables (no Alembic step). Startup
  never fails if the database is temporarily unreachable; the health endpoint
  reports `degraded` instead.
- **Availability formula** — portions are the minimum across recipe lines of
  `floor(available_ingredient / qty_per_portion)`; zero/negative outcomes are
  reported as `OUT_OF_STOCK`/`NOT_ACTIVE` with a limiting ingredient where
  applicable.
- **Job store** — in-memory singleton guarded by `asyncio.Lock`; background
  task references are retained until completion so they are not garbage
  collected mid-flight.
- **Error handling** — refresh failures are captured on the job
  (`status=error`, `error="ExceptionType: message"`) instead of crashing the
  request that enqueued them.

---

## Limitations / production notes

- The admin job store is **not persistent**; use a database collection or
  Redis for multi-process deployments.
- Background refreshes use the API process event loop. In production move them
  to a worker queue (Celery/RQ/Arq) and add per-domain locking.
- `FakeEmbedder` is for development/testing only; real semantic relevance
  requires `EMBEDDING_PROVIDER=openai` (or a wired Gemini provider) and a
  re-ingest of the docs domain.
- Admin auth is a single shared token (demo). Use OAuth2/OIDC and scoped tokens
  for real deployments.
- Ingestion assumes the source workbooks keep their current sheet names and
  column headers.
- MongoDB Atlas M0 and Neon's free tier are fine for this demo. Very large
  embedding collections should use Atlas Vector Search, pgvector or a dedicated
  vector store.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `ServerSelectionTimeoutError` | Check `MONGODB_URI`, the database user and the Atlas IP allowlist |
| `DNS operation timed out` / SRV lookup fails | Some networks block `_mongodb._tcp` SRV queries. Use the direct form instead: `mongodb://USER:PASSWORD@shard-00-00…,shard-00-01…,shard-00-02…/?authSource=admin&replicaSet=…&tls=true` (hostnames and replica set name are in the SRV records / Atlas UI) |
| `InvalidPasswordError` / connection refused on PostgreSQL | Check `DATABASE_URL`, the database name and `?ssl=require` for Neon |
| `asyncpg` cannot find a driver | Use a `postgresql+asyncpg://` URL (plain `postgresql://` is normalised automatically) |
| `JSON snapshot missing ... Run utg-export first` | Run `uv run utg-export` (or pass `--json-dir`) |
| `E11000 duplicate key` | Stale documents from an older natural key; run `uv run utg-ingest --wipe --yes` |
| `Missing data file` | Confirm the three source files exist under `DATA_DIR` |
| `401` on admin routes | Send `X-Admin-Token` matching `ADMIN_TOKEN` |
| Search returns chunks but scores look random | Expected with `EMBEDDING_PROVIDER=fake` |
| Tests cannot connect to MongoDB | They do not need Atlas; `mongomock-motor` is used automatically |
