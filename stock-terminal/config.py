import os
import logging
from pathlib import Path

# Load .env file if present (local dev only)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("stock_terminal")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production-please")
JWT_ALG    = "HS256"
JWT_EXPIRE = 60 * 24 * 30  # 30 days in minutes

# ---------------------------------------------------------------------------
# AI / Claude
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# Single constant — override per call if you need different model per feature
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:8000"
).split(",")

# ---------------------------------------------------------------------------
# Email / SMTP
# ---------------------------------------------------------------------------
NOTIFY_EMAIL  = os.environ.get("NOTIFY_EMAIL", "jaimovichsimon@gmail.com")
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
APP_URL       = os.environ.get("APP_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_DIR = Path(os.environ.get("DB_DIR", str(Path(__file__).parent)))

# ---------------------------------------------------------------------------
# Monte Carlo — CAPM drift parameters
# Forward drift uses CAPM (rf + beta·ERP) instead of recent historical mean,
# which would extrapolate bull/bear market bias forward. Vol and correlations
# still come from history (those estimators are stable).
# ---------------------------------------------------------------------------
MC_RISK_FREE_RATE = 0.045  # ~10y Treasury proxy
MC_EQUITY_PREMIUM = 0.055  # historical equity risk premium
MC_DEFAULT_BETA   = 1.0    # fallback when SPY regression is unavailable
