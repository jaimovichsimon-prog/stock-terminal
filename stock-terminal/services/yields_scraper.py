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
_HTTP_TIMEOUT      = 25.0
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


def _fred_history(series_id: str) -> list:
    """Returns up to ~30 most recent (date_iso, value) observations from a FRED series.

    Empty list on failure. Skips FRED's '.' missing-value markers.
    """
    try:
        url  = _FRED_URL.format(series=series_id)
        resp = httpx.get(url, timeout=_HTTP_TIMEOUT, headers={"User-Agent": _FRED_USER_AGENT})
        resp.raise_for_status()
        rows: list = []
        for line in resp.text.strip().splitlines():
            parts = line.split(",")
            if len(parts) != 2:
                continue
            d, v = parts[0].strip(), parts[1].strip()
            if v and v != "." and v[0].isdigit() and len(d) >= 8:
                rows.append((d, float(v)))
        return rows[-60:]   # keep recent window only
    except Exception:
        logger.warning("FRED fetch failed for %s", series_id, exc_info=True)
        return []


def _fred_latest(series_id: str) -> Optional[float]:
    """Convenience: returns just the most recent value, or None."""
    rows = _fred_history(series_id)
    return rows[-1][1] if rows else None


def _delta_bps_from_series(rows: list, target_days: int) -> Optional[float]:
    """Given (date_iso, value) tuples and a target lookback in days, returns the
    bps change between the latest value and the value closest to N days ago.
    Returns None if history is too short or no candidate is within tolerance."""
    if len(rows) < 2:
        return None
    latest_date_str, latest_val = rows[-1]
    try:
        latest = datetime.fromisoformat(latest_date_str)
    except ValueError:
        return None
    target = latest - timedelta(days=target_days)
    # Find the row with date closest to target, within target_days * 1.5 tolerance
    best = None
    best_diff = None
    for d_str, v in rows[:-1]:
        try:
            d = datetime.fromisoformat(d_str)
        except ValueError:
            continue
        diff = abs((d - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best, best_diff = (d_str, v), diff
    if best is None:
        return None
    if best_diff > target_days * 86400 * 1.5:
        return None
    return round((latest_val - best[1]) * 100, 1)


def _fetch_us_curve_full() -> Optional[dict]:
    """Returns {yields, changes_1d_bps, changes_1w_bps} for the US curve, or None.

    FRED rate-limits parallel connections aggressively, so serialize. This runs at
    most once per hour on cache miss / scheduled refresh.
    """
    yields: list = []
    deltas_1d: list = []
    deltas_1w: list = []
    for sid in _US_FRED_SERIES:
        rows = _fred_history(sid)
        if rows:
            yields.append(rows[-1][1])
            deltas_1d.append(_delta_bps_from_series(rows, 1))
            deltas_1w.append(_delta_bps_from_series(rows, 7))
        else:
            yields.append(None)
            deltas_1d.append(None)
            deltas_1w.append(None)
        time.sleep(0.15)
    if sum(1 for v in yields if v is not None) < 6:
        return None
    snap_us = _load_snapshot()["countries"]["US"]["yields"]
    return {
        "yields":         [snap_us[i] if v is None else v for i, v in enumerate(yields)],
        "changes_1d_bps": deltas_1d,
        "changes_1w_bps": deltas_1w,
    }


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
    """Pulls live FRED data and stores the enriched payload.

    Two-phase: publish the US-only enriched payload as soon as US is fetched, then
    optionally enrich with foreign 10Y. If foreign fails entirely, the US payload
    still benefits users (live curve + Δ1d/Δ1w).
    """
    global _REFRESHED
    try:
        us_full = _fetch_us_curve_full()
        # Phase 1: publish US data immediately (no foreign yet).
        with _REFRESHED_LOCK:
            _REFRESHED = _build_payload(us_full, foreign_live={})
        _persist_history(_REFRESHED)
        if us_full:
            logger.info("Yields phase 1: US curve fetched from FRED (Δ1d/Δ1w live)")
        # Phase 2: enrich with foreign 10Y. Best effort — if FRED times out a lot
        # we just skip and stick with phase 1.
        foreign_live = _fetch_foreign_10y()
        if foreign_live:
            with _REFRESHED_LOCK:
                _REFRESHED = _build_payload(us_full, foreign_live)
            _persist_history(_REFRESHED)
            logger.info("Yields phase 2: %d foreign 10Y rescaled from FRED", len(foreign_live))
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
