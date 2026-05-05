"""Sovereign yield curves: bundled snapshot + live yfinance overrides for US.

Strategy:
  1. `fetch_all_yields()` returns the bundled snapshot immediately (fast path).
  2. A background daemon thread (`start_yields_refresher`) refreshes hourly,
     pulling US Treasury yields and Δ1d/Δ1w from yfinance (^IRX, ^FVX, ^TNX, ^TYX).
  3. The 4 live tickers cover 3M, 5Y, 10Y, 30Y directly. Other US tenors (1M, 6M,
     1Y, 2Y, 3Y, 7Y, 20Y) are interpolated from the live curve so the full curve
     reflects current market levels. Δ1d/Δ1w come from yfinance history.
  4. For non-US countries we keep the snapshot. The history file (30d retention)
     accumulates from each refresh and feeds Δ1d/Δ1w over time.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf

from config import logger

_PROJECT_ROOT      = Path(__file__).parent.parent
_SNAPSHOT_PATH     = _PROJECT_ROOT / "static" / "data" / "yields_snapshot.json"
_HISTORY_PATH      = _PROJECT_ROOT / "data" / "yields_history.json"
_HISTORY_RETENTION = timedelta(days=30)

# yfinance tickers for liquid US Treasury benchmarks. Tenors not listed get
# linearly interpolated from the live curve below.
_US_YF_TICKERS = {
    "3M":  "^IRX",
    "5Y":  "^FVX",
    "10Y": "^TNX",
    "30Y": "^TYX",
}

_snapshot_cache: Optional[dict] = None


def _load_snapshot() -> dict:
    global _snapshot_cache
    if _snapshot_cache is None:
        _snapshot_cache = json.loads(_SNAPSHOT_PATH.read_text())
    return _snapshot_cache


def _yf_history(ticker: str) -> Optional[dict]:
    """Returns {latest, d1, d7} from yfinance close-price history, or None."""
    try:
        h = yf.Ticker(ticker).history(period="14d", auto_adjust=False)["Close"].dropna()
        if len(h) < 2:
            return None
        latest = float(h.iloc[-1])
        d1     = float(h.iloc[-2]) if len(h) >= 2 else None
        # 5 trading days back ≈ 1 calendar week
        d7     = float(h.iloc[-6]) if len(h) >= 6 else None
        return {"latest": latest, "d1": d1, "d7": d7}
    except Exception:
        logger.warning("yfinance fetch failed for %s", ticker, exc_info=True)
        return None


def _interpolate_curve(known: dict, tenors: list, fallback: list) -> list:
    """Given a known {tenor: yield} mapping, fill in missing tenors by linear
    interpolation between the known points. Tenors before the first or after
    the last known point keep the additive shift from the snapshot."""
    # Convert tenors to years for linear interp
    tenor_years = {"1M": 1/12, "3M": 0.25, "6M": 0.5, "1Y": 1, "2Y": 2, "3Y": 3,
                   "5Y": 5, "7Y": 7, "10Y": 10, "20Y": 20, "30Y": 30}
    known_pts = sorted(((tenor_years[t], v) for t, v in known.items()), key=lambda x: x[0])
    out = []
    for i, t in enumerate(tenors):
        if t in known:
            out.append(known[t])
            continue
        ty = tenor_years[t]
        # Find bracketing known points
        lower = None
        upper = None
        for x, y in known_pts:
            if x <= ty: lower = (x, y)
            if x >= ty and upper is None: upper = (x, y)
        if lower and upper and lower[0] != upper[0]:
            # Linear interp between known anchors
            frac = (ty - lower[0]) / (upper[0] - lower[0])
            out.append(lower[1] + frac * (upper[1] - lower[1]))
        elif lower or upper:
            # Outside known range — apply the shift between snapshot and the nearest known point
            anchor = lower or upper
            anchor_tenor = next(t2 for t2, v in known.items() if abs(tenor_years[t2] - anchor[0]) < 1e-6)
            shift = anchor[1] - fallback[tenors.index(anchor_tenor)]
            out.append(fallback[i] + shift)
        else:
            out.append(fallback[i])
    return out


def _fetch_us_curve_full() -> Optional[dict]:
    """Pulls live US Treasury yields from yfinance ^IRX, ^FVX, ^TNX, ^TYX.

    Returns {yields, changes_1d_bps, changes_1w_bps} aligned with snapshot tenors,
    or None if all 4 tickers fail.
    """
    snap_us = _load_snapshot()["countries"]["US"]["yields"]
    snap_tenors = _load_snapshot()["tenors"]
    live: dict = {}
    deltas_1d: dict = {}
    deltas_1w: dict = {}
    for tenor, ticker in _US_YF_TICKERS.items():
        h = _yf_history(ticker)
        if h is None:
            continue
        live[tenor] = h["latest"]
        if h.get("d1") is not None:
            deltas_1d[tenor] = round((h["latest"] - h["d1"]) * 100, 1)
        if h.get("d7") is not None:
            deltas_1w[tenor] = round((h["latest"] - h["d7"]) * 100, 1)
    if not live:
        return None
    yields_full = _interpolate_curve(live, snap_tenors, snap_us)
    # Interpolate deltas linearly between known tenors. Adjacent Treasury
    # maturities move highly correlated in practice, so this is a reasonable
    # approximation rather than leaving 7 of 11 cells blank.
    zero_curve = [0.0] * len(snap_tenors)
    deltas_1d_full = _interpolate_curve(deltas_1d, snap_tenors, zero_curve) if deltas_1d else [None] * len(snap_tenors)
    deltas_1w_full = _interpolate_curve(deltas_1w, snap_tenors, zero_curve) if deltas_1w else [None] * len(snap_tenors)
    return {
        "yields":         [round(y, 4) for y in yields_full],
        "changes_1d_bps": [round(v, 1) if v is not None else None for v in deltas_1d_full],
        "changes_1w_bps": [round(v, 1) if v is not None else None for v in deltas_1w_full],
    }


def _fetch_foreign_10y() -> dict:
    """Foreign 10Y from yfinance is unreliable / sparse. Skip for now —
    non-US countries stay on snapshot data; the persisted history file feeds
    Δ1d/Δ1w as it accumulates over time."""
    return {}


def _rescale_curve(snap_yields: list, snap_10y: float, live_10y: float) -> list:
    """Linearly rescale the snapshot curve so the 10Y point matches the live value.

    Uses additive shift (live_10y - snap_10y) which preserves the curve shape exactly.
    Multiplicative would compress/expand the curve unrealistically.
    """
    shift = live_10y - snap_10y
    return [round(y + shift, 4) for y in snap_yields]


_REFRESHED_LOCK = threading.Lock()
_REFRESHED:      Optional[dict] = None        # most recent FRED-enriched payload
_REFRESHER_RUNNING = False


def _build_payload(us_full: Optional[dict], foreign_live: dict) -> dict:
    snap = _load_snapshot()
    countries_out: dict = {}
    idx_10y = snap["tenors"].index("10Y")
    n_tenors = len(snap["tenors"])
    for code, c in snap["countries"].items():
        if code == "US" and us_full is not None:
            yields    = [round(y, 4) for y in us_full["yields"]]
            deltas_1d = us_full["changes_1d_bps"]
            deltas_1w = us_full["changes_1w_bps"]
            source    = "fred-live"
        elif code in foreign_live:
            yields    = _rescale_curve(c["yields"], c["yields"][idx_10y], foreign_live[code])
            deltas_1d = [None] * n_tenors
            deltas_1w = [None] * n_tenors
            source    = "fred-rescaled"
        else:
            yields    = list(c["yields"])
            deltas_1d = [None] * n_tenors
            deltas_1w = [None] * n_tenors
            source    = "snapshot"
        countries_out[code] = {
            "code":           code,
            "name":           c["name"],
            "iso_n3":         c["iso_n3"],
            "yields":         yields,
            "changes_1d_bps": deltas_1d,
            "changes_1w_bps": deltas_1w,
            "source":         source,
        }
    return {
        "as_of":       snap["as_of"],
        "tenors":      snap["tenors"],
        "countries":   countries_out,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }


def fetch_all_yields() -> dict:
    """Returns the latest payload — FRED-enriched if a refresh has completed,
    otherwise pure snapshot. Always fast (no network in the hot path)."""
    with _REFRESHED_LOCK:
        if _REFRESHED is not None:
            return _REFRESHED
    return _build_payload(us_full=None, foreign_live={})


def _refresh_once() -> None:
    """Pulls live US Treasury data via yfinance and stores the enriched payload."""
    global _REFRESHED
    try:
        us_full = _fetch_us_curve_full()
        with _REFRESHED_LOCK:
            _REFRESHED = _build_payload(us_full, foreign_live={})
        _persist_history(_REFRESHED)
        if us_full:
            logger.info("Yields refreshed: US curve fetched from yfinance (Δ1d/Δ1w live)")
        else:
            logger.info("Yields refresh: yfinance unavailable, serving snapshot")
    except Exception:
        logger.warning("Yields refresh failed", exc_info=True)


def start_yields_refresher() -> None:
    """Daemon thread that refreshes FRED data on startup and every hour after."""
    global _REFRESHER_RUNNING
    if _REFRESHER_RUNNING:
        return
    _REFRESHER_RUNNING = True
    def _loop():
        while True:
            _refresh_once()
            time.sleep(3600)
    threading.Thread(target=_loop, daemon=True, name="yields-refresher").start()


# ---------------------------------------------------------------------------
# History persistence — JSON file, append-only with 30d retention.
# Used to compute 1d / 1w changes in bps for the country detail endpoint.
# ---------------------------------------------------------------------------

def _persist_history(snapshot: dict) -> None:
    """Append the latest yields to `data/yields_history.json`. Best-effort, never raises."""
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        history = _load_history()
        ts      = snapshot["last_update"]
        for code, c in snapshot["countries"].items():
            history.setdefault(code, []).append({"ts": ts, "yields": c["yields"]})
        # Trim entries older than retention window
        cutoff = datetime.now(timezone.utc) - _HISTORY_RETENTION
        for code in list(history.keys()):
            history[code] = [
                e for e in history[code]
                if datetime.fromisoformat(e["ts"]) >= cutoff
            ]
        _HISTORY_PATH.write_text(json.dumps(history))
    except Exception:
        logger.warning("Yield history persist failed", exc_info=True)


def _load_history() -> dict:
    try:
        if _HISTORY_PATH.exists():
            return json.loads(_HISTORY_PATH.read_text())
    except Exception:
        logger.warning("Yield history read failed; resetting", exc_info=True)
    return {}


def get_changes_bps(code: str, current_yields: list, tenors: list,
                    payload_deltas_1d: Optional[list] = None,
                    payload_deltas_1w: Optional[list] = None) -> dict:
    """Returns {changes_1d_bps, changes_1w_bps} in basis points.

    Prefers deltas baked into the payload (FRED-derived for US). Falls back to
    the persisted history file for other countries (populated by the daemon
    over time — first useful Δ1d after ~24h, Δ1w after a week).
    """
    n = len(current_yields)
    if payload_deltas_1d and any(v is not None for v in payload_deltas_1d):
        return {
            "changes_1d_bps": payload_deltas_1d,
            "changes_1w_bps": payload_deltas_1w if payload_deltas_1w else [None] * n,
        }

    history = _load_history().get(code, [])
    now = datetime.now(timezone.utc)

    def _closest(days: int) -> Optional[list]:
        if not history:
            return None
        target = now - timedelta(days=days)
        best = min(history,
                   key=lambda e: abs((datetime.fromisoformat(e["ts"]) - target).total_seconds()))
        age_hours = abs((datetime.fromisoformat(best["ts"]) - target).total_seconds()) / 3600
        # Reject candidates too far off the target (avoids reporting a 30-min-old
        # snapshot as a "1d" delta and showing 0.0 bps).
        if days == 1 and age_hours > 18:
            return None
        if days == 7 and age_hours > 72:
            return None
        return best["yields"]

    snap_1d = _closest(1)
    snap_1w = _closest(7)

    def _delta_bps(then_y: Optional[list]) -> list:
        if then_y is None or len(then_y) != n:
            return [None] * n
        return [round((a - b) * 100, 1) for a, b in zip(current_yields, then_y)]

    return {
        "changes_1d_bps": _delta_bps(snap_1d),
        "changes_1w_bps": _delta_bps(snap_1w),
    }


# ---------------------------------------------------------------------------
# Derived metrics — spreads + curve classification.
# ---------------------------------------------------------------------------

def derive_metrics(country_data: dict, tenors: list, us_10y: Optional[float]) -> dict:
    yields = country_data["yields"]

    def _at(tenor: str) -> Optional[float]:
        try:
            return yields[tenors.index(tenor)]
        except (ValueError, IndexError):
            return None

    y2  = _at("2Y")
    y3m = _at("3M")
    y10 = _at("10Y")

    spread_2_10  = round(y10 - y2,  4) if (y10 is not None and y2  is not None) else None
    spread_3m_10 = round(y10 - y3m, 4) if (y10 is not None and y3m is not None) else None

    # Classify shape by the 2-10 spread in bps
    classification = None
    if spread_2_10 is not None:
        s_bps = spread_2_10 * 100
        if   s_bps < -10:  classification = "Inverted"
        elif s_bps < 30:   classification = "Flat"
        elif s_bps < 150:  classification = "Normal"
        else:              classification = "Steep"

    spread_vs_ust_10y = None
    if us_10y is not None and y10 is not None and country_data["code"] != "US":
        spread_vs_ust_10y = round(y10 - us_10y, 4)

    return {
        "spread_2_10":       spread_2_10,
        "spread_3m_10y":     spread_3m_10,
        "classification":    classification,
        "spread_vs_ust_10y": spread_vs_ust_10y,
    }
