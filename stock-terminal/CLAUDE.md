# Stock Terminal — Project Instructions

## What This Is

A self-hosted equity research terminal: FastAPI backend + vanilla JS frontend,
deployed as a single Docker container on Railway. No build toolchain. No React. No webpack.

## Architecture

### Backend
- `main.py` — ~50-line entry point: creates app, includes routers, mounts static files, starts alert daemon
- `config.py` — all env vars and constants; never hardcode values elsewhere
- `database.py` — SQLAlchemy engine, SessionLocal, Base, get_db()
- `models.py` — ORM models (User, PortfolioPosition, WatchlistItem, PasswordResetToken, PriceAlert, Transaction)
- `routers/` — one file per domain (auth, user_data, market, portfolio, news, earnings, screener, analyze)
- `services/` — business logic (email_service, claude_service, sentiment, alerts_daemon, cache)
- `utils/` — pure functions with no side effects (market_data, indicators)

### Frontend
- `index.html` — HTML structure and embedded CSS only; no inline JS
- `static/js/api.js` — `apiFetch()` with AbortController timeout, `safeTicker()` sanitizer; loaded as regular script
- `static/js/app.js` — all application JS (~2,890 lines); all tab logic, chart rendering, auth modal
- Chart.js 4.4.0 (CDN), DOMPurify 3.1.6 (CDN), Google Fonts — do not upgrade Chart.js without testing all charts

## Deployment

Railway runs `python main.py`. Dockerfile: `python:3.11-slim`, `COPY . .`, `CMD ["python", "main.py"]`.
Do not add new dependencies without updating `requirements.txt` and testing the Docker build.
No npm, no node. Frontend JS runs as regular scripts (not ES modules — see Known Gotchas).

## Environment Variables (all defined in config.py with defaults)

Required in production:
- `JWT_SECRET` — random 32+ char string (never use the default)
- `ANTHROPIC_API_KEY` — for news filtering, portfolio impact, AI analysis

Optional:
- `ALLOWED_ORIGINS` — comma-separated CORS origins (default: `http://localhost:8000`)
- `CLAUDE_MODEL` — Anthropic model for all AI calls (default: `claude-haiku-4-5-20251001`)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` — email notifications
- `NOTIFY_EMAIL` — destination for new-user signup alerts
- `APP_URL` — used in password reset email links
- `DB_DIR` — directory for `terminal.db` (Railway persistent volume: `/app/data`)

## Python Conventions

- All exceptions MUST be logged: `logger.warning("context", exc_info=True)` — never `except Exception: pass`
- Database mutations (PUT portfolio, PUT watchlist) must wrap in try/except with `db.rollback()` on failure
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

## External Data Sources

- **yfinance** — price, fundamentals, options, earnings. Rate-limited; always cache aggressively.
- **feedparser RSS** — 15 feeds, fetched on demand, cached 15 min
- **Anthropic Claude** — news filter + portfolio impact (`claude_service.py`), AI streaming analysis (`routers/analyze.py`)
- **SMTP** — Gmail + App Password for signup/reset/alert emails (`email_service.py`)

## Known Gotchas

- SQLite `check_same_thread=False` is required because the background alert daemon shares the engine across threads
- Railway persistent volume must be mounted at `/app/data`; set `DB_DIR=/app/data` in Railway env vars or the DB resets on every deploy
- The alert daemon (`services/alerts_daemon.py`) is a daemon thread started at app startup; if alerts stop working, check Railway logs for daemon errors
- Chart.js 4.4.0 is pinned; v4.5+ changed several API shapes that break the options surface chart
- `app.js` uses regular `<script src="...">` not `<script type="module">` — ES modules would isolate scope and break all `onclick="..."` HTML attributes. Do not change to module type.
- `get_user_watchlist` (in `routers/user_data.py`) and `get_public_watchlist` (in `routers/market.py`) must stay distinct names — they were previously the same name (`get_watchlist`), which caused Python to silently replace the auth-gated route with the public one, returning empty data for all logged-in users
- `apiFetch()` is defined in `api.js` which loads before `app.js` — maintain this load order in `index.html`
