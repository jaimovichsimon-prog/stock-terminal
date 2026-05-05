"""Sovereign yield curves: bundled snapshot + live FRED overrides.

Strategy:
  1. `fetch_all_yields()` returns the bundled snapshot immediately (fast path).
  2. A background daemon thread (`start_yields_refresher`) periodically pulls live
     data from FRED (no API key needed for fredgraph.csv) and updates the in-memory
     enriched copy:
       - US: full daily curve (DGS1MO ... DGS30)
       - OECD members with `fred_10y` series ID: monthly 10Y benchmark
  3. For OECD countries we have a live 10Y but no live curve, rescale the snapshot
     curve to the live 10Y (additive shift preserves shape). Mark `source: "fred-rescaled"`.
  4. For countries with no FRED series, return snapshot as-is. Mark `source: "snapshot"`.
  5. Each refresh persists to `data/yields_history.json` (30d retention) so the
     router can compute 1d / 1w changes in bps.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from config import logger

_PROJECT_ROOT      = Path(__file__).parent.parent
_SNAPSHOT_PATH     = _PROJECT_ROOT / "static" / "data" / "yields_snapshot.json"
_HISTORY_PATH      = _PROJECT_ROOT / "data" / "yields_history.json"
_HISTORY_RETENTION = timedelta(days=30)
_FRED_URL          = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
_HTTP_TIMEOUT      = 10.0
_FRED_USER_AGENT   = "Mozilla/5.0 stock-terminal/yields"

# US Treasury constant-maturity series at FRED, aligned 1-to-1 with the snapshot
# tenor list. Used only for the US row.
_US_FRED_SERIES = ["DGS1MO", "DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS3",
                   "DGS5", "DGS7", "DGS10", "DGS20", "DGS30"]

_snapshot_cache: Optional[dict] = None


def _load_snapshot() -> dict:
    global _snapshot_cache
    if _snapshot_cache is None:
        _snapshot_cache = json.loads(_SNAPSHOT_PATH.read_text())
    return _snapshot_cache


def _fred_latest(series_id: str) -> Optional[float]:
    """Returns the most recent non-null value from a FRED series, or None on failure."""
    try:
        url  = _FRED_URL.format(series=series_id)
        resp = httpx.get(url, timeout=_HTTP_TIMEOUT, headers={"User-Agent": _FRED_USER_AGENT})
        resp.raise_for_status()
        # CSV header: observation_date,SERIES_ID
        # Walk lines bottom-up looking for a numeric value (FRED uses "." for missing)
        for line in reversed(resp.text.strip().splitlines()):
            parts = line.split(",")
            if len(parts) != 2:
                continue
            val = parts[1].strip()
            if val and val != "." and val[0].isdigit():
                return float(val)
        return None
    except Exception:
        logger.warning("FRED fetch failed for %s", series_id, exc_info=True)
        return None


def _fetch_us_curve() -> Optional[list]:
    """Returns 11 yields aligned with snapshot tenors, or None if fetch fails badly.

    FRED rate-limits parallel connections aggressively, so serialize with a small
    inter-request delay. This runs at most once per hour on cache miss.
    """
    out = []
    for sid in _US_FRED_SERIES:
        out.append(_fred_latest(sid))
        time.sleep(0.15)
    if sum(1 for v in out if v is not None) < 6:
        return None
    snap_us = _load_snapshot()["countries"]["US"]["yields"]
    return [snap_us[i] if v is None else v for i, v in enumerate(out)]


def _fetch_foreign_10y() -> dict:
    """Returns {country_code: live_10y_yield} for countries with a fred_10y series ID.

    Serialized to respect FRED rate limits. Total time on cache miss: ~5-8s for ~25 series.
    """
    snap = _load_snapshot()
    out: dict = {}
    for code, c in snap["countries"].items():
        if not c.get("fred_10y") or code == "US":
            continue
        v = _fred_latest(c["fred_10y"])
        if v is not None:
            out[code] = v
        time.sleep(0.15)
    return out


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


def _build_payload(us_live: Optional[list], foreign_live: dict) -> dict:
    snap = _load_snapshot()
    countries_out: dict = {}
    idx_10y = snap["tenors"].index("10Y")
    for code, c in snap["countries"].items():
        if code == "US" and us_live is not None:
            yields = [round(y, 4) for y in us_live]
            source = "fred-live"
        elif code in foreign_live:
            yields = _rescale_curve(c["yields"], c["yields"][idx_10y], foreign_live[code])
            source = "fred-rescaled"
        else:
            yields = list(c["yields"])
            source = "snapshot"
        countries_out[code] = {
            "code":   code,
            "name":   c["name"],
            "iso_n3": c["iso_n3"],
            "yields": yields,
            "source": source,
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
    return _build_payload(us_live=None, foreign_live={})


def _refresh_once() -> None:
    """Pulls live FRED data (slow, ~30-60s) and stores the enriched payload."""
    global _REFRESHED
    try:
        us_live      = _fetch_us_curve()
        foreign_live = _fetch_foreign_10y()
        payload      = _build_payload(us_live, foreign_live)
        with _REFRESHED_LOCK:
            _REFRESHED = payload
        _persist_history(payload)
        logger.info("Yields refreshed: %d FRED-live, %d FRED-rescaled",
                    sum(1 for c in payload["countries"].values() if c["source"] == "fred-live"),
                    sum(1 for c in payload["countries"].values() if c["source"] == "fred-rescaled"))
    except Exception:
        logger.warning("Yields FRED refresh failed", exc_info=True)


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


def get_changes_bps(code: str, current_yields: list, tenors: list) -> dict:
    """Returns {1d: [...], 1w: [...]} in basis points, or None lists if no history."""
    history = _load_history().get(code, [])
    now = datetime.now(timezone.utc)
    target_1d = now - timedelta(days=1)
    target_1w = now - timedelta(days=7)

    def _closest(target: datetime) -> Optional[list]:
        if not history:
            return None
        # Find entry with timestamp closest to target, preferring strictly older
        best = min(history,
                   key=lambda e: abs((datetime.fromisoformat(e["ts"]) - target).total_seconds()))
        # Reject if more than 36h off the 1d target or more than 4d off the 1w target
        age_hours = abs((datetime.fromisoformat(best["ts"]) - target).total_seconds()) / 3600
        if target == target_1d and age_hours > 36:
            return None
        if target == target_1w and age_hours > 96:
            return None
        return best["yields"]

    snap_1d = _closest(target_1d)
    snap_1w = _closest(target_1w)

    def _delta_bps(now_y: list, then_y: Optional[list]) -> list:
        if then_y is None or len(then_y) != len(now_y):
            return [None] * len(now_y)
        return [round((a - b) * 100, 1) for a, b in zip(now_y, then_y)]

    return {
        "changes_1d_bps": _delta_bps(current_yields, snap_1d),
        "changes_1w_bps": _delta_bps(current_yields, snap_1w),
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
