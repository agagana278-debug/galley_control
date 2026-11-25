# Galley Control — Complete Technical Documentation Report

> **Project Tagline:** *Beyond Food Ordering — Towards an Intelligent, Self-Optimising Campus Canteen.*  
> **Project Workspace:** `C:\Users\gagan\.gemini\antigravity\scratch\galley-control`  
> **Companion Submission Deck:** `C:\Users\gagan\.gemini\antigravity\scratch\galley-control-ppt\GALLEY_CONTROL_HACKATHON_SUBMISSION.pptx`

---

## 1. Project Overview

### What the Project Does
**Galley Control** is a full-stack Agentic AI campus canteen management prototype built with a **React + Vite + Tailwind CSS** frontend, a **Python + FastAPI** backend, and a **SQLite** relational database. Rather than acting as a static food-ordering menu, it coordinates **1 Central Orchestrator Agent** and **8 Specialised Agents** alongside deterministic backend rules to handle menu ordering, smart out-of-stock substitutes, simulated checkout, single-use QR pickup generation and verification, duplicate-QR blocking, refund eligibility rules, conversational food assistance, review sentiment/category triage, outlet bottleneck detection, and seeded sample demand heatmaps.

### Problem Statement Addressed
Conventional campus canteen counters and static ordering apps suffer from:
1. Long queues during short college breaks and manual pickup callouts without preparation-time ETAs.
2. Stockouts of popular dishes alongside avoidable daily waste of over-prepared items.
3. Lack of automated transaction monitoring to detect duplicate QR scan attempts or unusual refund requests.
4. No unified visibility connecting student complaints to per-outlet performance bottlenecks.

### Main Objectives & Proposed Solution
- Deliver a modular 24-hour prototype separating **deterministic business rules** (stock checks, server-side pricing, simulated payment checks, single-use QR invalidation, refund eligibility) from **AI/agentic coordination** (intent routing, natural-language explanations, feedback categorisation, and operational recommendations requiring human approval).
- Exclude real financial integrations (simulated payments only), custom hardware (browser webcam + manual fallback), and digital loyalty/reward points.

### Target Users
1. **Students (`StudentPortal.jsx`):** Browse multi-outlet menus, filter vegetarian items, swap unavailable items to smart substitutes, join friend group orders via `group_code`, pick scheduled meal slots, complete simulated checkout, display/copy single-use QR passes, ask the conversational AI assistant, track orders, request cancellations/refunds, and submit ratings/reviews.
2. **Canteen Counter Staff (`CounterScanner.jsx`):** Scan student QR codes via browser webcam (`html5-qrcode`) or verify pasted/quick-filled QR tokens to collect orders and block duplicate scans.
3. **Canteen Managers / Administrators (`ManagerDashboard.jsx`):** Review security incident briefs, approve/dismiss AI recommendations, inspect outlet performance benchmarking and bottleneck diagnostics, track review resolution status, and view demand heatmaps and inventory/waste alerts.

### Key Features (Implemented vs. Sample-Data Driven vs. Planned)
| Scope Tier | Implemented in Codebase | Notes |
| :--- | :--- | :--- |
| **Live Prototype Workflows** | Multi-outlet menu, veg filter, out-of-stock smart substitute (`Veg Fried Rice` → `Veg Hakka Noodles`), group order code aggregation, scheduled slots, simulated checkout, Python `qrcode` PNG issuance, atomic QR collection & duplicate-QR rejection, deterministic refund rules, Central Orchestrator + 8 agent modules, review submission & resolution tracking, human recommendation approval, and `POST /api/demo/reset` | Verified via `pytest` and live Vite+FastAPI HTTP flow |
| **Seeded Sample-Data Views** | Baseline demand heatmap cells, historical break-hour demand breakdown, sample reviews (`is_sample = 1`), and sample perishable waste watch heuristics | Clearly tagged as `SAMPLE` / `SEEDED SAMPLE + LIVE` in SQLite and UI |
| **External LLM Integration** | REST client (`llm_client.py`) supporting Gemini (`generativelanguage.googleapis.com`) and OpenAI/Groq/OpenRouter endpoints via `.env` | Tested in `deterministic_fallback` mode (no `LLM_API_KEY` configured in `backend/.env`) |
| **Post-MVP / Planned** | Multi-canteen automatic load-balanced routing, ML time-series forecasting models, real campus identity/ERP integration | Not implemented in current prototype |

---

## 2. Technologies and Tech Stack

All versions below are verified from installed Python package metadata (`importlib.metadata`) and `frontend/package-lock.json`.

### Frontend Technologies
| Technology | Version | What It Is & Role | Where Used | Why Chosen |
| :--- | :--- | :--- | :--- | :--- |
| **React** (`react`, `react-dom`) | `18.3.1` | Component UI library managing state across role views | `frontend/src/App.jsx`, `pages/*` | Fast SPA development without page reloads |
| **Vite** (`vite`, `@vitejs/plugin-react`) | `7.3.8` / `4.7.0` | Dev server, HMR bundler, and `/api` HTTP proxy | `frontend/vite.config.js`, `package.json` | Instant local startup and clean production bundling |
| **Tailwind CSS** (`tailwindcss`, `postcss`, `autoprefixer`) | `3.4.19` / `8.5.33` / `10.7.0` | Utility-first CSS framework | `frontend/tailwind.config.js`, `src/index.css`, all JSX | Rapid consistent dark-navy + cyan styling |
| **html5-qrcode** | `2.3.8` | Browser webcam QR decoder (`Html5Qrcode`) | `frontend/src/pages/CounterScanner.jsx` | Enables zero-hardware QR verification in browser |
| **lucide-react** | `0.468.0` | Icon library | All frontend JSX pages | Clean UI iconography |

### Backend Technologies & Languages
| Technology | Version | What It Is & Role | Where Used | Why Chosen |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | `3.12.10` | Primary backend language | All files under `backend/` | Unifies API, QR generation, SQLite, and AI logic |
| **FastAPI** | `0.162.0` | Async/sync REST API framework with OpenAPI docs | `backend/app/main.py`, `routers/*.py` | Built-in validation, clean routing, `/docs` Swagger UI |
| **Uvicorn** | `0.54.0` | ASGI server serving FastAPI | Runtime (`uvicorn app.main:app --port 8000`) | Lightweight standard runner for FastAPI |
| **Pydantic & pydantic-settings** | `2.14.3` / `2.16.2` | Request payload schema validation | `backend/app/schemas.py` | Rejects malformed inputs (`ge`/`le`/regex constraints) |
| **qrcode** + **Pillow** | `8.2` / `12.3.0` | Generates PNG QR images encoded as base64 data URIs | `backend/app/services/qr_service.py` | Creates scannable single-use QR passes on checkout |
| **python-dotenv** | `1.2.4` | Loads `.env` config safely | `backend/app/config.py` | Keeps optional API keys outside source control |

### Database, AI/LLM, Testing & Tooling
| Technology | Version | Role & Where Used |
| :--- | :--- | :--- |
| **SQLite (`sqlite3`)** | Python stdlib | Single-file relational DB (`backend/galley_control.db`) configured with `PRAGMA foreign_keys = ON` and `sqlite3.Row` in `backend/app/database.py` |
| **httpx** | `0.28.1` | Outbound HTTP calls to optional LLM providers (`llm_client.py`) and FastAPI `TestClient` transport |
| **pytest** | `9.2.0` | Automated API and business-rule test runner (`backend/tests/*.py`) |
| **Node.js / npm** | `v22.14.0` / `10.9.2` | Local JS toolchain (bundled at `scratch/node-v22.14.0-win-x64`) |
| **Windows Launch Scripts** | PowerShell / Batch | `start_galley_control.ps1` and `start_galley_control.bat` start both backend (`8000`) and frontend (`5173`) |

---

## 3. System Architecture

### Overall Architecture & Communication
- **Frontend → Backend:** `frontend/src/api/client.js` sends JSON HTTP requests via `fetch()` to `/api/*`. In development, `frontend/vite.config.js` proxies `/api/*` to `http://127.0.0.1:8000` and intercepts proxy connection errors to return HTTP `503` JSON guidance.
- **Backend → Database:** Every router opens a short-lived context-managed SQLite transaction via `db_session()` in `backend/app/database.py`, committing on success and rolling back on unhandled exceptions.
- **Backend → AI & External LLM:** `orchestrator.py` coordinates 8 pure-Python agent modules reading live + sample SQLite state. Where natural-language phrasing or JSON classification is helpful (`orchestrator.py`, `security_agent.py`, `review_agent.py`), `llm_client.generate_llm_text()` checks `settings.llm_api_key`; if unconfigured or unreachable, callers fall back seamlessly to deterministic rule logic.

```
+-----------------------------------------------------------------------------+
|                         BROWSER CLIENT (React 18 + Vite)                    |
|   [StudentPortal.jsx]      [CounterScanner.jsx]      [ManagerDashboard.jsx] |
+------------+-------------------------+-------------------------+------------+
             |                         |                         |
             +-------------------------+-------------------------+
                                       | fetch("/api/*") -> Vite Proxy (:5173 -> :8000)
                                       v
+-----------------------------------------------------------------------------+
|                    FASTAPI APPLICATION (backend/app/main.py)                |
|  Routers: catalog | orders | qr | reviews | agents | dashboard              |
+------------------+-------------------------------------+--------------------+
                   |                                     |
                   v                                     v
+----------------------------------+   +--------------------------------------+
|  DETERMINISTIC SERVICES          |   |  CENTRAL ORCHESTRATOR AGENT          |
|  - rules_engine.py               |   |  (agents/orchestrator.py)            |
|    * Stock & Substitute Guard    |   |  SENSE -> THINK -> ACT -> EXPLAIN    |
|    * Simulated Payment Check     |   |  Delegates across 8 Agents:          |
|    * Atomic ACTIVE->COLLECTED QR |   |   1. ordering_agent   2. inventory   |
|    * Refund & Escalation Policy  |   |   3. queue_agent      4. support     |
|  - qr_service.py (qrcode PNG)    |   |   5. security_agent   6. review      |
|                                  |   |   7. outlet_agent     8. analytics   |
+------------------+---------------+   +------------------+-------------------+
                   |                                      |
                   +------------------+-------------------+
                                      |
                                      v
                        +---------------------------+       Optional REST
                        | SQLITE (galley_control.db)|   +-------------------+
                        | 8 Tables (FK + UNIQUE)    |   | Hosted LLM API    |
                        +---------------------------+   | (Gemini / OpenAI) |
                                                        +-------------------+
```

### Data Flow (User Input to Output)
1. **Checkout Flow:** `StudentPortal` submits `OrderCreateRequest` → `orders.checkout_order` → `rules_engine.place_order_and_issue_qr()` recalculates prices from `menu_items`, validates stock (or raises `409` with substitute), validates `simulate_payment_success` (or commits `SIMULATED_PAYMENT_FAILED` and raises `402`), computes ETA via `compute_queue_eta()`, inserts `orders` + `order_items` + `qr_tokens` (`ACTIVE`), decrements `menu_items.stock_qty`, and returns JSON with `qr_image` (`data:image/png;base64,...`).
2. **QR Scan Flow:** `CounterScanner` sends `{ token }` → `qr.verify_qr` → `rules_engine.verify_and_collect_qr()` performs `UPDATE qr_tokens SET status = 'COLLECTED' ... WHERE id = ? AND status = 'ACTIVE'`. Any subsequent scan fails that atomic guard, logs `DUPLICATE_QR_REUSE` (`HIGH` risk) in `security_events`, and returns `valid: false`.
3. **Feedback-to-Action Flow:** `StudentPortal` submits review → `reviews.submit_review` → `orchestrator.orchestrate_review_to_action()` classifies sentiment + 5-category tag (`review_agent`), aggregates open complaints, runs `evaluate_outlets()` (`outlet_agent` + `queue_agent`), and inserts a `PENDING_APPROVAL` row in `ai_recommendations` when `>= 2` open negative/neutral complaints share an outlet and category.

---

## 4. Working Mechanism (Step by Step)

1. **Startup:** FastAPI's `lifespan` runs `init_db()` (`CREATE TABLE IF NOT EXISTS ...`) and `seed_database()`, ensuring 3 outlets, 12 menu items, 6 historical sample orders, 4 sample reviews, and 1 sample recommendation exist on first boot.
2. **Student Assistance:** Typing *"Quick veg food under ₹60"* triggers `POST /api/agents/chat` → `orchestrate_student_assistant()` → `ordering_agent.query_menu_options()` parses `"veg"` and regex `under (\d+)` against SQLite, `inventory_agent` + `queue_agent` read live stock & queue congestion, `support_agent` drafts a grounded reply (optionally rephrased by `llm_client`), and returns the full `agentic_lifecycle` trace (`sense`, `think`, `act`, `explain`, `learn`).
3. **Ordering & Substitute Handling:** Attempting to order out-of-stock *Veg Fried Rice* returns HTTP `409` containing `{ substitute: { id, name: "Veg Hakka Noodles", price, stock_qty } }`. `StudentPortal` renders a 1-click **Swap to Veg Hakka Noodles** button.
4. **QR Verification & Escalation:** First scan marks `orders.order_status = 'COLLECTED'` and `qr_tokens.status = 'COLLECTED'`. Scanning again logs `DUPLICATE_QR_REUSE` (`HIGH`). Clicking **Cancel / Refund** on a collected order triggers `evaluate_cancellation_and_refund()`, which blocks automated refund and inserts `COLLECTED_ORDER_REFUND_ESCALATION` (`requires_human_review = 1`).
5. **Manager Review:** `GET /api/dashboard/summary` invokes `orchestrate_dashboard_summary()` across all 8 agents. Managers click **Approve**/**Dismiss** (`POST /api/dashboard/recommendations/{id}`), **Mark Reviewed** (`POST /api/dashboard/security/{id}/resolve`), or **Resolve** (`POST /api/reviews/{id}/resolve`).

---

## 5. Codebase Analysis

```text
galley-control/
├── .env.example / .gitignore / README.md
├── start_galley_control.bat & start_galley_control.ps1
├── backend/
│   ├── .env.example / requirements.txt / galley_control.db
│   ├── app/
│   │   ├── main.py                # FastAPI app, lifespan DB init/seed, CORS, /api/health
│   │   ├── config.py              # Settings dataclass loaded from .env
│   │   ├── database.py            # SQLite schema (8 tables) & db_session() context manager
│   │   ├── seed_data.py           # seed_database() & reset_database() (resets sqlite_sequence)
│   │   ├── schemas.py             # 7 Pydantic v2 request schemas
│   │   ├── routers/               # catalog.py, orders.py, qr.py, reviews.py, agents.py, dashboard.py
│   │   ├── services/              # qr_service.py, rules_engine.py, llm_client.py
│   │   └── agents/                # orchestrator.py + 8 specialised agent modules
│   └── tests/                     # test_foundation.py, test_milestone2_orders_qr.py, test_milestone3_agents_analytics.py
└── frontend/
    ├── index.html / package.json / vite.config.js / tailwind.config.js / postcss.config.js
    └── src/
        ├── main.jsx / index.css / App.jsx
        ├── api/client.js          # ApiError + fetch wrappers for all backend endpoints
        └── pages/                 # StudentPortal.jsx, CounterScanner.jsx, ManagerDashboard.jsx
```

### File-by-File Module Summary
- **`backend/app/config.py`:** Defines mutable `Settings` dataclass (`database_path`, `llm_provider`, `llm_api_key`, `llm_model`, `cors_origins`).
- **`backend/app/database.py`:** Defines `SCHEMA_SQL`, `get_connection()`, `db_session()`, and `init_db()`.
- **`backend/app/seed_data.py`:** Defines `OUTLETS`, `MENU_ITEMS`, `SAMPLE_REVIEWS`, `seed_database()`, and `reset_database()`.
- **`backend/app/services/qr_service.py`:** `generate_qr_token(order_code)` (`GC-{order_code}-{8 hex chars}`) and `render_qr_base64(token)`.
- **`backend/app/services/rules_engine.py`:** `compute_queue_eta()`, `place_order_and_issue_qr()`, `verify_and_collect_qr()`, and `evaluate_cancellation_and_refund()`.
- **`backend/app/services/llm_client.py`:** `generate_llm_text()` supporting Gemini and OpenAI/Groq/OpenRouter with 10s timeout and `None` fallback.
- **`backend/app/agents/*.py`:** Isolated single-responsibility modules for each of the 8 agents plus `orchestrator.py` (`orchestrate_student_assistant`, `orchestrate_review_to_action`, `orchestrate_dashboard_summary`).
- **`frontend/src/api/client.js`:** Defines `ApiError` and 14 API helper functions; interprets empty-body `500` responses as backend unreachable guidance.
- **`frontend/src/App.jsx`:** Coordinates top-level role tabs (`student`, `counter`, `manager`), global refresh via `loadAll()`, security badge count, and `Reset Demo`.
- **`frontend/src/pages/StudentPortal.jsx`:** Menu, veg filter, cart, group code lookup, scheduled slots, simulated pay toggle, QR pass, AI Food Assistant with lifecycle trace, review submission, and order tracker.
- **`frontend/src/pages/CounterScanner.jsx`:** `Html5Qrcode` camera scanner + manual token form + quick-fill order chips + verification verdict + security event log.
- **`frontend/src/pages/ManagerDashboard.jsx`:** 8-agent banner, 6 KPI tiles, recommendation approval controls, security incident brief, outlet benchmarking table, feedback 5-category breakdown, demand heatmap grid, and inventory/waste alerts.

---

## 6. Algorithms and Technical Implementation

| Feature / Logic | Implementation Type | Inputs & Outputs | Status |
| :--- | :--- | :--- | :--- |
| **Queue Wait ETA (`compute_queue_eta`)** | Deterministic formula | In: `outlet_id`, `max_item_prep`, active `PLACED`/`PREPARING` count, `active_staff` → Out: `max(2, max_item_prep + round((active_orders * 3) / staff))` | Implemented |
| **Single-Use QR Lock (`verify_and_collect_qr`)** | Atomic SQL conditional update | In: `token` → Executes `WHERE id = ? AND status = 'ACTIVE'`; blocks duplicate/cancelled tokens and inserts `security_events` | Implemented |
| **Refund Policy (`evaluate_cancellation_and_refund`)** | Deterministic policy tree | Blocks collected orders (`HIGH` escalation) and students with `>= 2` prior live cancellations (`MEDIUM` escalation); otherwise refunds and restores stock | Implemented |
| **Menu Filtering (`query_menu_options`)** | Keyword + regex NLU | Detects veg terms and `(?:under\|below\|max\|rs\.?\|₹)\s*(\d+)` budget constraints over SQLite | Implemented |
| **Review Sentiment & Categorisation (`review_agent.py`)** | Optional LLM JSON + keyword/rating fallback | Maps comment + rating (`1..5`) to `{POSITIVE, NEUTRAL, NEGATIVE}` and 5 categories; flags recurring issues when open negative/neutral count `>= 2` | Implemented |
| **Outlet Bottleneck Diagnosis (`evaluate_outlets`)** | Cross-agent rule synthesis | Combines recurring reviews + queue congestion (`HIGH` at `>= 4` active orders or sample rush) + cancel rate (`>= 25%`) | Implemented |
| **Demand Heatmap (`build_analytics_report`)** | SQL `GROUP BY` aggregation | Aggregates non-cancelled orders by `(outlet_id, slot)` separating `live_cnt` vs `sample_cnt` | Implemented |
| **Demand Forecasting & ML Models** | Slot aggregation + stock threshold heuristics | Uses seeded `is_sample = 1` orders and `stock_qty >= 28` perishable heuristic; full ML time-series models are planned post-MVP | Sample Heuristic / Planned |

---

## 7. Database and Data Management

Data is stored locally in `backend/galley_control.db` (SQLite) using 8 tables defined in `backend/app/database.py`:
1. `outlets` (`id`, `name UNIQUE`, `location`, `status`, `avg_prep_minutes`, `active_staff`)
2. `menu_items` (`id`, `outlet_id FK`, `name`, `category`, `price`, `stock_qty`, `prep_minutes`, `is_veg`, `substitute_item_id`)
3. `orders` (`id`, `order_code UNIQUE`, `outlet_id FK`, `student_name`, `group_code`, `scheduled_slot`, `total_amount`, `payment_status`, `order_status`, `estimated_wait_minutes`, `is_sample`, `created_at`)
4. `order_items` (`id`, `order_id FK`, `menu_item_id FK`, `item_name`, `quantity`, `unit_price`)
5. `qr_tokens` (`id`, `order_id FK UNIQUE`, `token UNIQUE`, `status`, `scan_count`, `issued_at`, `collected_at`)
6. `security_events` (`id`, `order_id`, `token`, `event_type`, `risk_level`, `ai_explanation`, `requires_human_review`, `resolved`, `created_at`)
7. `reviews` (`id`, `outlet_id FK`, `order_id`, `student_name`, `rating`, `comment`, `sentiment`, `category`, `is_resolved`, `is_sample`, `created_at`)
8. `ai_recommendations` (`id`, `source_agent`, `outlet_id`, `title`, `rationale`, `status`, `is_sample`, `created_at`)

**Validation & Data Safety:** All inputs pass Pydantic v2 validation (`schemas.py`). Prices and totals are computed strictly server-side from `menu_items`. Stock decrements guard `WHERE id = ? AND stock_qty >= ?`.

---

## 8. Development Process (Observed Chronology)

1. **Milestone 1 (Foundation):** Created workspace directories, `.gitignore`, `.env.example`, `requirements.txt`, `package.json`, `database.py`, `seed_data.py`, `main.py`, and initial React/Vite/Tailwind shell; installed Python `qrcode 8.2` and 132 npm packages; verified `/api/health`, `/api/catalog/overview`, and Vite proxy.
2. **Milestone 2 (Core Orders & QR Guard):** Implemented `schemas.py`, `qr_service.py`, `rules_engine.py`, `routers/{catalog,orders,qr}.py`, `StudentPortal.jsx`, and `CounterScanner.jsx`. Fixed transactional rollback on HTTP `402` payment failure audit logging in `rules_engine.py`.
3. **Milestone 3 (Multi-Agent System & Manager Dashboard):** Implemented `llm_client.py`, `orchestrator.py`, all 8 agent modules, `routers/{reviews,agents,dashboard}.py`, `ManagerDashboard.jsx`, and updated `StudentPortal.jsx` with AI chat + review forms.
4. **Integration & E2E Hardening:** Caught and fixed `sqlite_sequence` reset bug in `seed_data.py` so `POST /api/demo/reset` consistently restores outlet IDs `1..3`; added `503` proxy error handling in `vite.config.js`, friendlier fallback messaging in `client.js`, and `start_galley_control.bat`/`.ps1` launchers.

---

## 9. Testing and Validation

### Automated Backend Test Suite (`pytest 9.2.0` + FastAPI `TestClient`)
Verified **7/7 passing tests** in `4.30s` (latest run via `python -m pytest -v`):
1. `test_foundation.py::test_health_and_catalog_foundation` — Verifies `/api/health`, SQLite connectivity, 3 outlets, 12 items, and *Veg Fried Rice* substitute link.
2. `test_milestone2_orders_qr.py::test_out_of_stock_returns_smart_substitute` — Verifies HTTP `409` substitute payload.
3. `test_milestone2_orders_qr.py::test_failed_simulated_payment_preserves_stock` — Verifies HTTP `402`, unchanged stock, and persisted `SIMULATED_PAYMENT_FAILED` audit row.
4. `test_milestone2_orders_qr.py::test_checkout_qr_collection_and_duplicate_rejection` — Verifies PNG QR generation, group order lookup, valid 1st scan, `HIGH`-risk `DUPLICATE_QR_REUSE` on 2nd scan, and human escalation on refund attempt after collection.
5. `test_milestone2_orders_qr.py::test_uncollected_order_cancellation_and_demo_reset` — Verifies refund approval + stock restoration, `CANCELLED_QR_ATTEMPT` blocking, and `POST /api/demo/reset` resetting outlet IDs to `[1, 2, 3]`.
6. `test_milestone3_agents_analytics.py::test_orchestrator_assistant_and_lifecycle_trace` — Verifies budget/veg filtering, invoked agents, and 5-step lifecycle fields.
7. `test_milestone3_agents_analytics.py::test_review_to_outlet_action_and_dashboard_consolidation` — Verifies recurring complaint detection, recommendation creation, manager approval, and review resolution.

### Frontend Build & Live E2E Smoke Verification
- `npm run build` (`vite v7.3.8`): Built production bundle (`dist/index.html`, CSS, JS) cleanly in `20.89s`.
- End-to-end proxy script (`e2e_smoke.py`) verified full HTTP flow (`CHAT_AGENTS`, `CHECKOUT` + `QR_OK`, `SCAN1`/`SCAN2`, `COLLECTED_REFUND_BLOCKED`, `REVIEW_TO_ACTION` + `APPROVED`, `DASHBOARD_AGENTS: 8`, `DEMO_RESET`).
- Live host FastAPI server (`task-378.log`) recorded `145` HTTP requests (`200 OK`) during interactive browser testing.

### Known Limitations
- **LLM API Mode:** Verified in `deterministic_fallback` mode (`backend/.env` has no `LLM_API_KEY` set); live Gemini/OpenAI API calls require adding a key to `backend/.env`.
- **Webcam Scanner:** `html5-qrcode` builds cleanly and renders in `CounterScanner.jsx`, but physical camera frame decoding was not tested headlessly without hardware; manual token entry and quick-fill demo chips provide full functional fallback.
- **Persistence Scope:** Uses a local single-file SQLite database without user login/password authentication (persona tabs switch views directly for hackathon demonstration).

---

## 10. Challenges and Solutions

| Challenge Encountered | Root Cause | Solution Implemented |
| :--- | :--- | :--- |
| **`FrozenInstanceError` in tests** | `Settings` dataclass used `frozen=True`, blocking pytest `monkeypatch` of `database_path` | Removed `frozen=True` in `backend/app/config.py` |
| **`npm install` `esbuild` failure** | `node` was not on system PATH during `esbuild` postinstall | Prepended `scratch/node-v22.14.0-win-x64` to `PATH` in commands and `start_galley_control.ps1` |
| **HTTP `402` audit log rolled back** | `place_order_and_issue_qr()` raised `HTTPException(402)` inside `db_session()`, triggering rollback | Explicitly called `conn.commit()` after inserting `SIMULATED_PAYMENT_FAILED` before raising |
| **Post-reset `Outlet not found` (`404`)** | `DELETE FROM outlets` did not reset SQLite `AUTOINCREMENT`, shifting IDs to `4..6` | Added `DELETE FROM sqlite_sequence` in `seed_data.reset_database()` |
| **Browser `Error: Request failed with status 500`** | Frontend `:5173` ran without FastAPI running on `:8000` | Added `503` JSON proxy error handler in `vite.config.js`, clear hint in `client.js`, and `start_galley_control.bat`/`.ps1` |

---

## 11. Future Scope (Proposed Improvements — Not Yet Implemented)

1. **Multi-Canteen Automatic Order Routing:** Automatically split or re-route items across campus outlets based on real-time kitchen load.
2. **True Time-Series ML Forecasting:** Train demand/prep-time models (e.g., Prophet/scikit-learn) on real multi-week campus order logs instead of seeded sample counts.
3. **Real Campus SSO & Payment Gateway Integration:** Add institutional OAuth login and sandboxed/approved campus wallet integration under finance governance.
4. **Live WebSocket Kitchen Display:** Push real-time order tickets to kitchen tablets instead of manual/poll refreshes.
5. **Production Deployment Hardening:** Migrate from SQLite to PostgreSQL for concurrent multi-counter writes and deploy HTTPS frontend + backend.

---

## 12. Final Technical Summary

- **Architecture Summary:** 3-tier web app (**React 18 + Vite + Tailwind** → **FastAPI + Deterministic Rules + Central Orchestrator + 8 Python Agents** → **SQLite**, plus optional **Hosted LLM API**).
- **Main Workflow:** Student browses/chats → checks out with simulated payment → receives single-use PNG QR → Counter verifies once & blocks duplicate scans → Security Agent explains anomalies → Student reviews feed Outlet Performance & Queue bottleneck recommendations → Manager approves actions.
- **Strengths:** Strict separation of deterministic security/financial rules from AI reasoning, offline-resilient fallback mode, zero custom hardware, 7 automated tests, and 1-click Windows launch scripts.
- **Limitations:** Single-file SQLite, simulated payments, unauthenticated role switcher, and sample-seeded demand heatmaps.

---

## Concise Executive Summary (For Hackathon Presentation Prep)

- **Pitch in 1 Sentence:** *Galley Control transforms manual campus canteens from static menu apps into an intelligent, self-optimising ecosystem powered by 1 Central Orchestrator and 8 collaborating AI agents.*
- **Core Technical Credibility Points for Judges:**
  1. **Security First:** AI never approves payments or overrides pickups—Python + SQLite enforce single-use QR locks atomically (`WHERE status = 'ACTIVE'`), reject duplicate scans deterministically, and escalate collected-order refunds for human approval.
  2. **True Multi-Agent Collaboration:** Our `SENSE → THINK → ACT → EXPLAIN → LEARN` trace connects *Ordering + Inventory + Queue + Support* for students and *Review & Feedback + Outlet Performance + Queue* to turn recurring wait complaints into manager-approved fixes.
  3. **Honest 24-Hour Scope:** Live student ordering, simulated checkout, real PNG QR generation/verification, duplicate blocking, AI chat, and review-to-action run on real code and SQLite; demand heatmaps and waste alerts transparently badge seeded sample data.
  4. **Zero Hardware & Offline Safe:** Runs on any laptop/phone browser with `html5-qrcode` webcam scanning plus manual token fallback, and includes full deterministic fallback if an LLM API key is absent or venue Wi-Fi drops.
