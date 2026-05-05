from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import ALLOWED_ORIGINS, SUPABASE_URL, SUPABASE_ANON_KEY, logger
from services.alerts_daemon import start_alert_daemon

from routers import market, portfolio, news, earnings, screener, analyze, yields

app = FastAPI(title="Stock Terminal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Serve static JS files
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Register all routers (auth + per-user data now live in Supabase)
for _router in [
    market.router,
    portfolio.router,
    news.router,
    earnings.router,
    screener.router,
    analyze.router,
    yields.router,
]:
    app.include_router(_router, prefix="/api")


_INDEX_HTML_PATH = Path(__file__).parent / "index.html"


def _render_index() -> str:
    html = _INDEX_HTML_PATH.read_text()
    inject = (
        f'<script>window.SUPABASE_URL="{SUPABASE_URL}";'
        f'window.SUPABASE_ANON_KEY="{SUPABASE_ANON_KEY}";</script>'
    )
    return html.replace("<!-- SUPABASE_CONFIG_INJECT -->", inject)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(_render_index())


# Start background alert checker
start_alert_daemon()
logger.info("Stock Terminal started")


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
