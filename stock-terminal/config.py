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
# Supabase
# ---------------------------------------------------------------------------
SUPABASE_URL              = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY         = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_DB_URL           = os.environ.get("SUPABASE_DB_URL", "")
SUPABASE_JWT_ALG          = os.environ.get("SUPABASE_JWT_ALG", "ES256")
ADMIN_EMAIL               = os.environ.get("ADMIN_EMAIL", "")

# ---------------------------------------------------------------------------
# AI / Claude
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS", "http://localhost:8000"
).split(",")

# ---------------------------------------------------------------------------
# Email / SMTP (alert notifications only — auth emails handled by Supabase)
# ---------------------------------------------------------------------------
SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")

# ---------------------------------------------------------------------------
# Monte Carlo — CAPM drift parameters
# Forward drift uses CAPM (rf + beta·ERP) instead of recent historical mean,
# which would extrapolate bull/bear market bias forward. Vol and correlations
# still come from history (those estimators are stable).
# ---------------------------------------------------------------------------
MC_RISK_FREE_RATE = 0.045  # ~10y Treasury proxy
MC_EQUITY_PREMIUM = 0.055  # historical equity risk premium
MC_DEFAULT_BETA   = 1.0    # fallback when SPY regression is unavailable
