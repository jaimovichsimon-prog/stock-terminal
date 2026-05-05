from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from config import logger
from services.cache import yields_cache
from services.supabase_auth import require_user
from services.yields_scraper import (
    derive_metrics,
    fetch_all_yields,
    get_changes_bps,
)

router = APIRouter()

_CACHE_KEY = "all"


def _get_cached_or_fetch() -> dict:
    cached = yields_cache.get(_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        data = fetch_all_yields()
        yields_cache.set(_CACHE_KEY, data)
        return data
    except Exception:
        logger.warning("fetch_all_yields failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Yield data temporarily unavailable")


@router.get("/yields/countries")
def get_countries(_: dict = Depends(require_user)):
    """Light list for the world map: 10Y level + 2-10 slope per country."""
    data    = _get_cached_or_fetch()
    tenors  = data["tenors"]
    idx_10  = tenors.index("10Y")
    idx_2y  = tenors.index("2Y")

    out = []
    for code, c in data["countries"].items():
        y10 = c["yields"][idx_10]
        y2  = c["yields"][idx_2y]
        out.append({
            "code":        code,
            "name":        c["name"],
            "iso_n3":      c["iso_n3"],
            "yield_10y":   round(y10, 3) if y10 is not None else None,
            "slope_2_10":  round((y10 - y2) * 100, 1) if (y10 is not None and y2 is not None) else None,
            "source":      c["source"],
        })
    return {
        "countries":    out,
        "as_of":        data["as_of"],
        "last_update":  data["last_update"],
    }


@router.get("/yields/{country_code}")
def get_country_curve(country_code: str, _: dict = Depends(require_user)):
    """Full curve + bps changes + spreads + classification for one country."""
    code = country_code.upper().strip()
    data = _get_cached_or_fetch()
    if code not in data["countries"]:
        raise HTTPException(status_code=404, detail=f"Country '{code}' not supported")

    c       = data["countries"][code]
    tenors  = data["tenors"]
    us_10y: Optional[float] = None
    if "US" in data["countries"]:
        us_10y = data["countries"]["US"]["yields"][tenors.index("10Y")]

    changes = get_changes_bps(code, c["yields"], tenors)
    metrics = derive_metrics(c, tenors, us_10y)

    return {
        "code":            code,
        "name":            c["name"],
        "tenors":          tenors,
        "yields":          c["yields"],
        "changes_1d_bps":  changes["changes_1d_bps"],
        "changes_1w_bps":  changes["changes_1w_bps"],
        "source":          c["source"],
        "as_of":           data["as_of"],
        "last_update":     data["last_update"],
        **metrics,
    }
