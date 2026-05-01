from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import yfinance as yf
from fastapi import APIRouter

from config import logger
from utils.market_data import clean_float, deep_clean
from services.cache import screener_cache

router = APIRouter()

SCREENER_UNIVERSE = {
    "Technology":             ["AAPL","MSFT","NVDA","GOOGL","META","AVGO","ORCL","AMD","QCOM","TXN","NOW","CRM","ADBE","SNOW","PLTR","NET","CRWD","ZS","DDOG","INTU","AMAT","MU","MRVL","FTNT","PANW","SHOP","UBER","ARM","SMCI","ASML"],
    "Finance":                ["JPM","BAC","WFC","GS","MS","BLK","V","MA","AXP","C","SCHW","USB","PNC","TFC","COF","MCO","SPGI","CME","ICE","PYPL","KKR","APO","BX","CG"],
    "Healthcare":             ["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","DHR","AMGN","GILD","ISRG","CVS","MDT","BMY","REGN","VRTX","PFE","BIIB","MRNA","HCA","ELV","CI","HUM","DGX"],
    "Energy":                 ["XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","OXY","HAL","BKR","DVN","FANG","MRO","HES","LNG","WMB","KMI","OKE","ET"],
    "Consumer Discretionary": ["AMZN","TSLA","HD","NKE","SBUX","MCD","TGT","CMG","LULU","TJX","YUM","BKNG","MAR","HLT","GM","F","ROST","ORLY","AZO","RIVN"],
    "Consumer Staples":       ["WMT","COST","PG","KO","PEP","PM","MO","MDLZ","CL","CHD","GIS","K","SYY","ADM","STZ","MNST","KHC"],
    "Industrials":            ["CAT","DE","BA","HON","RTX","LMT","GE","UPS","FDX","MMM","EMR","ETN","CSX","UNP","NSC","CARR","OTIS","ROK","PWR","CTAS"],
    "Communication":          ["META","GOOGL","NFLX","DIS","CMCSA","T","VZ","SNAP","PINS","SPOT","WBD","FOXA","PARA","TTD","ROKU"],
    "Materials":              ["LIN","APD","ECL","SHW","NEM","FCX","ALB","CF","MOS","DOW","DD","PPG","NUE","STLD","VMC"],
    "Real Estate":            ["AMT","PLD","CCI","EQIX","SPG","O","PSA","WELL","VTR","DLR","EQR","AVB","INVH","SBA","AMH"],
    "Utilities":              ["NEE","DUK","SO","D","AEP","EXC","XEL","AWK","PCG","ES","ED","ETR","FE","AES"],
}


def _fetch_screener_stock(sym: str) -> Optional[dict]:
    try:
        info  = yf.Ticker(sym).info
        price = clean_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if not price:
            return None
        return {
            "ticker":      sym,
            "company":     info.get("longName") or info.get("shortName") or sym,
            "sector":      info.get("sector") or "Unknown",
            "price":       price,
            "change_pct":  clean_float(info.get("regularMarketChangePercent")),
            "market_cap":  clean_float(info.get("marketCap")),
            "pe":          clean_float(info.get("trailingPE")),
            "forward_pe":  clean_float(info.get("forwardPE")),
            "volume":      clean_float(info.get("volume") or info.get("regularMarketVolume")),
            "week52_high": clean_float(info.get("fiftyTwoWeekHigh")),
            "week52_low":  clean_float(info.get("fiftyTwoWeekLow")),
            "beta":        clean_float(info.get("beta")),
            "div_yield":   clean_float(info.get("dividendYield")),
        }
    except Exception:
        logger.warning("Screener fetch failed for %s", sym, exc_info=True)
        return None


@router.get("/screener")
def get_screener(
    sector:     str            = "Technology",
    min_pe:     Optional[float]= None,
    max_pe:     Optional[float]= None,
    min_change: Optional[float]= None,
    max_change: Optional[float]= None,
    min_cap:    Optional[float]= None,
):
    sector  = sector.strip()
    tickers = SCREENER_UNIVERSE.get(sector, SCREENER_UNIVERSE["Technology"])

    cached = screener_cache.get(sector)
    if cached is not None:
        results = cached
    else:
        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = {pool.submit(_fetch_screener_stock, sym): sym for sym in tickers}
            results = [f.result() for f in as_completed(futures) if f.result()]
        results.sort(key=lambda x: x.get("market_cap") or 0, reverse=True)
        screener_cache.set(sector, results)

    filtered = results
    if min_pe     is not None: filtered = [r for r in filtered if r["pe"] is not None and r["pe"] >= min_pe]
    if max_pe     is not None: filtered = [r for r in filtered if r["pe"] is not None and r["pe"] <= max_pe]
    if min_change is not None: filtered = [r for r in filtered if r["change_pct"] is not None and r["change_pct"] >= min_change]
    if max_change is not None: filtered = [r for r in filtered if r["change_pct"] is not None and r["change_pct"] <= max_change]
    if min_cap    is not None: filtered = [r for r in filtered if r["market_cap"] is not None and r["market_cap"] >= min_cap]

    return deep_clean({
        "results": filtered,
        "sector":  sector,
        "total":   len(filtered),
        "sectors": list(SCREENER_UNIVERSE.keys()),
    })
