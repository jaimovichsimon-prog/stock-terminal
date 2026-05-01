from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import ALLOWED_ORIGINS, logger
from database import Base, engine
from services.alerts_daemon import start_alert_daemon

from routers import auth, user_data, market, portfolio, news, earnings, screener, analyze

# Create tables on startup
Base.metadata.create_all(bind=engine)

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

# Register all routers
for _router in [
    auth.router,
    user_data.router,
    market.router,
    portfolio.router,
    news.router,
    earnings.router,
    screener.router,
    analyze.router,
]:
    app.include_router(_router, prefix="/api")

@app.get("/")
def index():
    return FileResponse(str(Path(__file__).parent / "index.html"))


# Start background alert checker
start_alert_daemon()
logger.info("Stock Terminal started")


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
