# Stock Terminal — Project Instructions

## What This Is

A self-hosted equity research terminal: FastAPI backend + vanilla JS frontend,
deployed as a single Docker container on Railway. No build toolchain. No React. No webpack.

## Architecture

### Backend
- `main.py` — ~70-line entry point: creates app, includes routers, mounts static files, starts alert daemon + yields refresher
- `config.py` — all env vars and constants; never hardcode values elsewhere
- Persistence: per-user data lives in **Supabase** (no SQLAlchemy models in this repo). Auth uses Supabase JWKS via `services/supabase_auth.py`
- `routers/` — one file per domain (market, portfolio, news, earnings, screener, analyze, yields)
- `services/` — business logic (email_service, claude_service, sentiment, alerts_daemon, cache, supabase_auth, yields_scraper)
- `utils/` — pure functions with no side effects (market_data, indicators)
- `static/data/` — bundled assets shipped with the app: `yields_snapshot.json` (40+ countries × 11 tenors, dated), `world-110m.json` (Natural Earth TopoJSON for the map)
- `data/` — runtime-only writable directory (gitignored). `data/yields_history.json` accumulates daily yield snapshots for Δ1d / Δ1w computation

### Frontend
- `index.html` — HTML structure and embedded CSS only; no inline JS
- `static/js/api.js` — `apiFetch()` with AbortController timeout, `safeTicker()` sanitizer; loaded as regular script
- `static/js/app.js` — all application JS (~3,700 lines); all tab logic, chart rendering, auth modal, yields map
- Chart.js 4.4.0 (CDN), DOMPurify 3.1.6 (CDN), Supabase JS 2.45.4 (CDN), D3 v7 + topojson-client v3 (CDN), Google Fonts — do not upgrade Chart.js without testing all charts

## Deployment

Railway runs `python main.py`. Dockerfile: `python:3.11-slim`, `COPY . .`, `CMD ["python", "main.py"]`.
Do not add new dependencies without updating `requirements.txt` and testing the Docker build.
No npm, no node. Frontend JS runs as regular scripts (not ES modules — see Known Gotchas).

## Environment Variables (all defined in config.py with defaults)

Required in production:
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` — auth + per-user persistence
- `ANTHROPIC_API_KEY` — for news filtering, portfolio impact, AI analysis

Optional:
- `ALLOWED_ORIGINS` — comma-separated CORS origins (default: `http://localhost:8000`)
- `CLAUDE_MODEL` — Anthropic model for all AI calls (default: `claude-haiku-4-5-20251001`)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — email notifications
- `NOTIFY_EMAIL` — destination for new-user signup alerts
- `APP_URL` — used in password reset email links

## Python Conventions

- All exceptions MUST be logged: `logger.warning("context", exc_info=True)` — never `except Exception: pass`
- Per-user mutations go through Supabase client SDK; surface errors to the user, never silently swallow
- New routes go in the appropriate `routers/` file, never in `main.py`
- Ticker symbols: always uppercase + strip; validate with `re.compile(r'^[A-Z0-9.\-\^=]{1,10}$')`
  Valid examples: `AAPL`, `BRK.B`, `^GSPC`, `BTC-USD`, `CL=F` — the old `[A-Z]{1,5}` pattern is wrong
- Ticker regex with dots: use `re.escape(ticker).replace(r"\.", r"[.]")` so `BRK.B` matches correctly
- Model string: use `CLAUDE_MODEL` from `config.py` — never hardcode model name strings
- Cache: use `SimpleCache` from `services/cache.py` — never add new ad-hoc cache dicts
- Python 3.9 compat: use `Optional[X]` not `X | None` for return type annotations

## JavaScript Conventions

- All fetch calls go through `apiFetch()` from `api.js` (adds 15s timeout + error propagation)
- Never assign untrusted data to `innerHTML` — use `textContent`, or `DOMPurify.sanitize()` for markdown
- AI streamed content must be sanitized: `const _san = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize : h => h; el.innerHTML = _san(renderMarkdown(raw));`
- Ticker/symbol data inserted into `innerHTML` must go through `safeTicker()` from `api.js`
- No new global variables — `app.js` owns the global scope; all new code goes in the appropriate existing function or tab handler
- Do NOT convert `app.js` to ES modules: all tab HTML uses `onclick="functionName()"` which requires global scope
- Auth token: stored in `localStorage` — do not log it; do not include in error messages

## Cache TTLs

| Cache | TTL | Max entries |
|-------|-----|-------------|
| Macro dashboard | 60s | 1 |
| News feed | 15 min | 1 |
| Screener (per sector) | 25 min | 11 |
| Upcoming earnings | 4 hr | 1 |
| Options chains | 2 min | 100 |
| Sector lookups | 24 hr | 500 |
| Yields (all 40+ countries) | 1 hr | 1 |

## External Data Sources

- **yfinance** — price, fundamentals, options, earnings. Also US Treasury yields via `^IRX`/`^FVX`/`^TNX`/`^TYX` (`services/yields_scraper.py`). Rate-limited; always cache aggressively.
- **feedparser RSS** — 24 feeds, fetched on demand, cached 15 min
- **Anthropic Claude** — news filter + portfolio impact (`claude_service.py`), AI streaming analysis (`routers/analyze.py`)
- **SMTP** — Gmail + App Password for signup/reset/alert emails (`email_service.py`)
- **Bundled yields snapshot** — `static/data/yields_snapshot.json`, hand-curated 40+ country curves dated `2026-05-01`. Refresh manually when stale; non-US sovereigns have no free live feed

## Known Gotchas

- The alert daemon (`services/alerts_daemon.py`) and yields refresher (`services/yields_scraper.py:start_yields_refresher`) are daemon threads started at app startup; if either stops working, check Railway logs for `INFO Yields refreshed` / alert daemon errors
- Chart.js 4.4.0 is pinned; v4.5+ changed several API shapes that break the options surface chart
- `app.js` uses regular `<script src="...">` not `<script type="module">` — ES modules would isolate scope and break all `onclick="..."` HTML attributes. Do not change to module type.
- `apiFetch()` is defined in `api.js` which loads before `app.js` — maintain this load order in `index.html`
- **Page tabs are gated client-side only** (`body.guest` adds blur + gate-overlay). API endpoints under `/api/*` are public — do NOT add `Depends(require_user)` unless you genuinely need server-side auth for that route (Portfolio, News, Screener, Yields are all public APIs with client-side gating)
- **Yields tab — non-US countries have no live feed**: yfinance only exposes US Treasury benchmarks (^IRX, ^FVX, ^TNX, ^TYX). Foreign sovereign yields require a paid data subscription (TradingEconomics, Bloomberg, ICE BofA). The snapshot file is the source of truth for those — refresh it manually when stale.
- **Yields tab — D3 map width race**: when the tab first becomes visible (`display:none → block`), `clientWidth` can return a stale value. `yieldsRenderMap` schedules a `setTimeout(50ms)` re-measurement and uses a ResizeObserver. Don't switch to `requestAnimationFrame` — it doesn't fire on backgrounded preview tabs.
- The `data/` directory is gitignored and writable at runtime. On Railway, mount a persistent volume there if you need `yields_history.json` to survive redeploys; otherwise foreign Δ1d/Δ1w resets each deploy.
