import re
import datetime
from typing import Any, List, Optional

import yfinance as yf
from fastapi import APIRouter
from pydantic import BaseModel

from config import logger
from utils.market_data import clean_float
from services.cache import news_cache, sector_cache
from services.sentiment import classify_sentiment, EXCLUDE_KEYWORDS, HIGH_IMPORTANCE, CAT_KEYWORDS
from services.claude_service import claude_filter, claude_portfolio_impact

router = APIRouter()

RSS_FEEDS = [
    # US Central Banks & Official
    ("Federal Reserve",       "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("ECB",                   "https://www.ecb.europa.eu/rss/fsr.xml"),
    # US Wire Services
    ("Reuters Business",      "https://feeds.reuters.com/reuters/businessNews"),
    ("Reuters Markets",       "https://feeds.reuters.com/reuters/financeNews"),
    ("AP Business",           "https://apnews.com/hub/business.rss"),
    ("AP Economy",            "https://apnews.com/hub/economy.rss"),
    # US Financial TV / Wire
    ("CNBC Markets",          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("CNBC Economy",          "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("MarketWatch",           "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("Barrons",               "https://www.barrons.com/xml/rss/3_7514.xml"),
    ("Investing.com",         "https://www.investing.com/rss/news_301.rss"),
    ("Yahoo Finance",         "https://finance.yahoo.com/news/rssindex"),
    # US Quality Press
    ("NYT Business",          "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"),
    ("NYT Economy",           "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml"),
    ("Washington Post Econ",  "https://feeds.washingtonpost.com/rss/business/economy"),
    ("NPR Business",          "https://feeds.npr.org/1006/rss.xml"),
    # US Magazines / Journals
    ("The Economist Finance", "https://www.economist.com/finance-and-economics/rss.xml"),
    ("The Economist Business","https://www.economist.com/business/rss.xml"),
    # UK / Europe
    ("BBC Business",          "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("The Guardian Business", "https://www.theguardian.com/business/rss"),
    ("Financial Times",       "https://www.ft.com/rss/home"),
    # Macro data & think tanks
    ("Brookings Economy",     "https://www.brookings.edu/topic/economy/feed/"),
    ("Peterson Institute",    "https://www.piie.com/rss.xml"),
    ("Calculated Risk",       "https://feeds.feedburner.com/CalculatedRisk"),
]

# ---------------------------------------------------------------------------
# Portfolio impact ticker/sector topic tables
# ---------------------------------------------------------------------------
_TICKER_TOPICS: dict[str, list[str]] = {
    "YPF":  ["oil", "petroleum", "crude", "opec", "brent", "wti", "natural gas", "energy price", "oil price", "fuel", "refin", "hydrocarbons", "latin america energy", "argentina energy"],
    "XOM":  ["oil", "petroleum", "crude", "opec", "brent", "wti", "natural gas", "energy"],
    "CVX":  ["oil", "petroleum", "crude", "opec", "brent", "wti", "energy"],
    "BP":   ["oil", "petroleum", "crude", "opec", "brent", "wti", "energy"],
    "COP":  ["oil", "petroleum", "crude", "opec", "energy"],
    "SLB":  ["oil", "drilling", "oilfield", "crude", "energy"],
    "OXY":  ["oil", "petroleum", "crude", "opec", "energy"],
    "PSX":  ["oil", "refinery", "petroleum", "crude", "energy"],
    "MPC":  ["oil", "refinery", "petroleum", "crude", "energy"],
    "HAL":  ["oil", "drilling", "oilfield", "crude", "energy"],
    "PBR":  ["oil", "petroleum", "crude", "opec", "brazil energy"],
    "USO":  ["oil", "crude", "wti", "petroleum"],
    "UNG":  ["natural gas", "lng", "gas price"],
    "NVDA": ["nvidia", "gpu", "semiconductor", "ai chip", "artificial intelligence", "data center", "blackwell", "chip", "h100", "export control"],
    "AMD":  ["amd", "semiconductor", "cpu", "gpu", "chip", "processor"],
    "INTC": ["intel", "semiconductor", "chip", "processor", "foundry"],
    "TSM":  ["tsmc", "taiwan", "semiconductor", "chip", "foundry"],
    "TSMC": ["tsmc", "taiwan", "semiconductor", "chip", "foundry"],
    "QCOM": ["qualcomm", "semiconductor", "chip", "mobile", "wireless"],
    "AVGO": ["broadcom", "semiconductor", "chip", "networking"],
    "MU":   ["micron", "memory", "dram", "nand", "semiconductor"],
    "AMAT": ["semiconductor", "chip equipment", "wafer"],
    "LRCX": ["semiconductor", "chip equipment", "wafer"],
    "AAPL": ["apple", "iphone", "ipad", "mac", "app store", "china tariff", "consumer electronics", "services revenue"],
    "MSFT": ["microsoft", "azure", "windows", "office", "cloud", "ai"],
    "GOOGL":["google", "alphabet", "search", "youtube", "android", "cloud"],
    "GOOG": ["google", "alphabet", "search", "youtube", "android", "cloud"],
    "AMZN": ["amazon", "aws", "e-commerce", "cloud", "retail"],
    "META": ["meta", "facebook", "instagram", "whatsapp", "social media", "advertising"],
    "NFLX": ["netflix", "streaming", "content", "subscriber"],
    "JPM":  ["jpmorgan", "banking", "interest rate", "fed", "credit", "financial"],
    "BAC":  ["bank of america", "banking", "interest rate", "credit", "financial"],
    "GS":   ["goldman", "investment banking", "trading", "financial"],
    "MS":   ["morgan stanley", "wealth management", "banking", "financial"],
    "WFC":  ["wells fargo", "banking", "mortgage", "credit"],
    "C":    ["citigroup", "banking", "global", "credit", "financial"],
    "BRK.B":["berkshire", "insurance", "buffett", "financial"],
    "TSLA": ["tesla", "electric vehicle", "ev", "lithium", "battery", "autonomous"],
    "GM":   ["general motors", "automobile", "ev", "car", "tariff"],
    "F":    ["ford", "automobile", "ev", "car", "tariff"],
    "RIVN": ["rivian", "electric vehicle", "ev"],
    "GLD":  ["gold", "precious metal", "safe haven", "inflation hedge"],
    "SLV":  ["silver", "precious metal"],
    "GDX":  ["gold mining", "gold", "precious metal"],
    "FCX":  ["copper", "mining", "commodity"],
    "NEM":  ["gold mining", "gold"],
    "JNJ":  ["johnson", "pharma", "drug", "fda", "healthcare"],
    "PFE":  ["pfizer", "pharma", "drug", "fda", "vaccine"],
    "MRK":  ["merck", "pharma", "drug", "fda"],
    "ABBV": ["abbvie", "pharma", "drug", "fda", "immunology"],
    "LLY":  ["lilly", "pharma", "drug", "fda", "obesity", "glp"],
    "WMT":  ["walmart", "retail", "consumer", "tariff", "import"],
    "TGT":  ["target", "retail", "consumer", "tariff"],
    "COST": ["costco", "retail", "consumer", "membership"],
    "LOMA": ["argentina", "cement", "construction", "latin america"],
    "GGAL": ["argentina", "bank", "galicia", "financial", "peso"],
    "BMA":  ["argentina", "bank", "macro", "financial", "peso"],
    "CEPU": ["argentina", "energy", "electricity", "utility"],
    "GLOB": ["globant", "technology", "software", "latin america"],
    "MELI": ["mercadolibre", "e-commerce", "fintech", "latin america", "brazil"],
}

_SECTOR_TOPICS: dict[str, list[str]] = {
    "Energy":                 ["oil", "petroleum", "crude", "opec", "brent", "wti", "natural gas", "lng", "energy price", "fuel"],
    "Technology":             ["semiconductor", "chip", "ai", "artificial intelligence", "tech", "cloud", "data center", "software"],
    "Financials":             ["interest rate", "fed rate", "bank", "banking", "credit", "lending", "financial crisis", "yield"],
    "Healthcare":             ["drug", "fda", "pharmaceutical", "biotech", "clinical trial", "healthcare", "vaccine"],
    "Consumer Discretionary": ["consumer spending", "retail", "tariff", "import", "automobile", "housing"],
    "Industrials":            ["manufacturing", "pmi", "factory", "supply chain", "infrastructure", "tariff"],
    "Materials":              ["gold", "copper", "mining", "steel", "aluminum", "commodity", "raw material"],
}

_COMMODITY_PRODUCERS = {
    "YPF", "XOM", "CVX", "BP", "COP", "OXY", "PSX", "MPC", "HAL", "SLB",
    "PBR", "USO", "VLO", "GLD", "SLV", "GDX", "NEM", "FCX", "AEM", "GOLD", "CEPU",
}

_COMMODITY_PRICE_UP = [
    "oil price rises", "oil prices rise", "oil price up", "oil prices up",
    "crude rises", "crude surges", "crude up", "crude higher",
    "brent rises", "brent surges", "brent up", "brent higher",
    "wti rises", "wti surges", "wti up",
    "oil hits", "crude hits", "brent hits",
    "oil above", "crude above", "oil rally", "crude rally",
    "oil price above", "oil prices above",
    "natural gas rises", "natural gas surges", "gas prices rise",
    "gold rises", "gold surges", "gold up", "gold hits", "gold above",
    "copper rises", "copper surges",
]

_COMMODITY_PRICE_DOWN = [
    "oil price falls", "oil prices fall", "oil price down", "crude falls",
    "crude drops", "crude down", "crude lower", "brent falls", "brent drops",
    "wti falls", "oil plunges", "crude plunges", "oil collapses",
    "oil below", "crude below", "oil drops", "oil declines",
    "natural gas falls", "gas prices fall",
    "gold falls", "gold drops", "gold down", "gold declines",
    "copper falls", "copper drops",
]


def _parse_feed_date(entry):
    import feedparser  # local import to avoid at module level if feedparser not installed
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime.datetime(*t[:6], tzinfo=datetime.timezone.utc)
            except Exception:
                pass
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _title_key(title: str) -> str:
    return re.sub(r"\W+", " ", title.lower()).strip()


def _fetch_articles() -> list[dict]:
    import feedparser

    cutoff    = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    seen_keys: set[str] = set()
    articles  = []
    for source_name, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub = _parse_feed_date(entry)
                if pub and pub < cutoff:
                    continue
                title = _strip_html(getattr(entry, "title", "") or "")
                if not title:
                    continue
                key = _title_key(title)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                summary = _strip_html(
                    getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
                )
                link = getattr(entry, "link", "") or ""
                articles.append({
                    "title":        title,
                    "summary":      summary[:500],
                    "source":       source_name,
                    "url":          link,
                    "published_at": pub.isoformat() if pub else None,
                })
        except Exception:
            logger.warning("RSS feed failed: %s", url, exc_info=True)
    return articles


def _lookup_sector(ticker: str) -> str:
    cached = sector_cache.get(ticker)
    if cached is not None:
        return cached
    try:
        info   = yf.Ticker(ticker).fast_info
        sector = getattr(info, "sector", "") or ""
    except Exception:
        sector = ""
    if not sector:
        try:
            sector = yf.Ticker(ticker).info.get("sector", "") or ""
        except Exception:
            sector = ""
    sector_cache.set(ticker, sector)
    return sector


def _commodity_direction(raw: str) -> Optional[str]:
    if any(p in raw for p in _COMMODITY_PRICE_UP):
        return "Positive"
    if any(p in raw for p in _COMMODITY_PRICE_DOWN):
        return "Negative"
    return None


def _keyword_portfolio_impact(tickers: list, articles: list) -> dict:
    impacts = []
    for a in articles:
        raw      = (a.get("title", "") + " " + a.get("summary", "")).lower()
        art_sent = classify_sentiment(raw)
        for entry in tickers:
            if isinstance(entry, dict):
                ticker = entry.get("ticker", "").upper()
                sector = entry.get("sector", "") or ""
            else:
                ticker = str(entry).upper()
                sector = ""
            if not sector and ticker not in _TICKER_TOPICS:
                sector = _lookup_sector(ticker)

            if ticker in _COMMODITY_PRODUCERS:
                commodity_dir = _commodity_direction(raw)
                direction     = commodity_dir if commodity_dir else (art_sent if art_sent != "Neutral" else "Mixed")
            else:
                direction = art_sent if art_sent != "Neutral" else "Mixed"

            note = None
            # Use word-boundary regex that handles dots in tickers (BRK.B, etc.)
            safe_ticker_re = re.escape(ticker).replace(r"\.", r"[.]")
            if re.search(r'(?<![A-Z])' + safe_ticker_re + r'(?![A-Z])', raw, re.IGNORECASE):
                note = f"{ticker} is directly referenced in this article."
            elif ticker in _TICKER_TOPICS:
                matched = [kw for kw in _TICKER_TOPICS[ticker] if kw in raw]
                if matched:
                    note = (f"This article covers {matched[0]}, which directly affects {ticker}'s revenues and valuation.")
            elif sector and sector in _SECTOR_TOPICS:
                matched = [kw for kw in _SECTOR_TOPICS[sector] if kw in raw]
                if matched:
                    note = (f"As a {sector} company, {ticker} is exposed to {matched[0]} dynamics covered in this article.")

            if note:
                impacts.append({"article_id": a["id"], "ticker": ticker, "direction": direction, "note": note})
    return {"impacts": impacts}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/news")
def get_news(refresh: bool = False):
    if not refresh:
        cached = news_cache.get("main")
        if cached is not None:
            return cached

    articles = _fetch_articles()
    filtered = claude_filter(articles)
    result   = {
        "articles":      filtered,
        "total_fetched": len(articles),
        "cached_at":     datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    news_cache.set("main", result)
    return result


class PortfolioImpactRequest(BaseModel):
    tickers:  List[Any]
    articles: List[dict]


@router.post("/news/portfolio-impact")
def get_portfolio_impact(body: PortfolioImpactRequest):
    if not body.tickers or not body.articles:
        return {"impacts": []}
    result = claude_portfolio_impact(body.tickers, body.articles)
    if result is not None:
        return result
    return _keyword_portfolio_impact(body.tickers, body.articles)


@router.get("/news/ticker/{symbol}")
def get_ticker_news(symbol: str):
    symbol = symbol.upper().strip()
    try:
        tk       = yf.Ticker(symbol)
        raw      = tk.news or []
        articles = []
        for item in raw[:20]:
            pub_ts = item.get("providerPublishTime") or item.get("pubDate")
            pub_dt = None
            if pub_ts:
                try:
                    pub_dt = datetime.datetime.fromtimestamp(int(pub_ts), tz=datetime.timezone.utc).isoformat()
                except Exception:
                    logger.warning("Bad pub timestamp for ticker news %s", symbol, exc_info=True)
            articles.append({
                "title":        item.get("title", ""),
                "url":          item.get("link", "") or item.get("url", ""),
                "source":       item.get("publisher", "") or item.get("source", ""),
                "published_at": pub_dt,
                "summary":      item.get("summary", "")[:400],
            })
        return {"articles": articles, "ticker": symbol}
    except Exception:
        logger.warning("Ticker news fetch failed for %s", symbol, exc_info=True)
        return {"articles": [], "ticker": symbol}
