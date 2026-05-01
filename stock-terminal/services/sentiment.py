import re

# ---------------------------------------------------------------------------
# Exclusion keywords — articles matching these are dropped
# ---------------------------------------------------------------------------
EXCLUDE_KEYWORDS = [
    "nfl", "nba", "nhl", "mlb", "soccer", "cricket", "rugby", "tennis", "golf",
    "celebrity", "fashion", "lifestyle", "recipe", "travel", "tourism",
    "movie", "film", "music", "entertainment", "oscars", "grammy",
    "horoscope", "crossword", "puzzle",
    "podcast", "interview", "opinion", "column", "newsletter",
    "webinar", "survey", "poll", "quiz", "listicle", "explainer",
]

# ---------------------------------------------------------------------------
# Category classification keywords
# ---------------------------------------------------------------------------
CAT_KEYWORDS = {
    "Fed/Monetary Policy": [
        "federal reserve", "fed", "fomc", "interest rate", "rate hike", "rate cut",
        "central bank", "ecb", "bank of england", "boe", "boj", "bank of japan",
        "quantitative easing", "quantitative tightening", "monetary policy",
        "inflation", "cpi", "pce", "price stability", "jerome powell", "powell",
        "lagarde", "rate decision", "rate hold", "fed meeting", "fed statement",
        "fed minutes", "beige book", "press conference", "dot plot",
        "fed chair", "fed governor", "fed president",
        "fed funds rate", "neutral rate", "r-star", "terminal rate",
        "balance sheet", "reverse repo", "treasury purchases", "yield curve",
        "2yr", "10yr", "30yr", "hawkish", "dovish", "tightening", "easing",
    ],
    "Geopolitics": [
        "war", "conflict", "military", "sanctions", "sanction", "geopolit",
        "nato", "ukraine", "russia", "iran", "middle east", "taiwan",
        "north korea", "missile", "troops", "invasion", "ceasefire", "treaty",
        "diplomat", "embassy", "nuclear",
    ],
    "Commodities": [
        "oil price", "crude oil", "opec", "natural gas", "energy price",
        "commodity", "gold price", "silver", "wheat", "corn", "supply chain",
        "strait of hormuz", "brent", "wti", "lng",
    ],
    "Tech/AI": [
        "artificial intelligence", " ai ", "openai", "nvidia", "chip shortage",
        "semiconductor", "antitrust", "big tech", "regulation tech",
        "chatgpt", "machine learning", "data center", "cloud computing",
    ],
    "Markets": [
        "stock market", "wall street", "s&p 500", "nasdaq", "dow jones",
        "treasury yield", "bond yield", "credit market", "hedge fund",
        "market rally", "market selloff", "market crash", "volatility",
        "dollar index", "currency", "forex", "ipo",
    ],
    "Macro Economy": [
        "gdp", "recession", "unemployment", "jobs report", "nonfarm payroll",
        "trade deficit", "trade war", "tariff", "fiscal policy", "budget deficit",
        "national debt", "economic growth", "consumer confidence",
        "manufacturing", "pmi", "retail sales",
    ],
}

HIGH_IMPORTANCE = [
    "federal reserve", "fomc", "rate decision", "rate hike", "rate cut",
    "fed holds", "fed raises", "fed cuts", "fed pauses",
    "powell speaks", "powell said", "jerome powell",
    "fed statement", "fed minutes", "fed meeting", "press conference",
    "inflation data", "cpi report", "jobs report", "nonfarm payroll",
    "gdp growth", "gdp contraction", "recession",
    "war ", "invasion", "military strike", "nuclear",
    "sanctions", "opec", "oil supply", "oil price",
    "market crash", "stock market crash", "financial crisis",
    "bank collapse", "bank failure", "systemic",
    "tariff", "trade war",
    "artificial intelligence regulation", "ai regulation",
    "yield curve inversion", "hawkish", "dovish", "rate unchanged",
    "basis points", "bps", "emergency meeting", "systemic risk",
    "contagion", "bank run", "credit crunch", "debt ceiling",
    "sovereign default", "currency crisis", "flash crash",
]

# ---------------------------------------------------------------------------
# Sentiment phrases (scored ±2)
# ---------------------------------------------------------------------------
SENT_PHRASES_POS = [
    "rate cut", "rate cuts", "fed cut", "fed cuts", "fed pivot",
    "fed pause", "fed pauses", "fed holds", "fed hold",
    "interest rate cut", "interest rate cuts",
    "dovish", "easing cycle", "quantitative easing",
    "stimulus package", "fiscal stimulus",
    "inflation cools", "inflation cooled", "cooling inflation",
    "inflation falls", "inflation fell", "inflation eases", "inflation eased",
    "inflation slows", "inflation slowed", "lower inflation", "disinflation",
    "prices cool", "prices ease", "prices fall",
    "better than expected", "beat expectations", "beats estimates",
    "beat estimates", "above expectations", "exceeded expectations",
    "blowout", "record high", "all-time high",
    "soft landing", "strong jobs", "jobs added", "strong gdp", "gdp beats",
    "economy grows", "economy expands", "economy accelerates",
    "stocks rally", "markets rally", "equities rally", "market rally",
    "stocks surge", "markets surge",
    "ceasefire", "peace deal", "trade deal", "trade agreement",
    "sanctions lifted", "sanctions eased", "tariffs reduced",
    "raised guidance", "raised outlook", "upgrade", "buyback",
]

SENT_PHRASES_NEG = [
    "rate hike", "rate hikes", "interest rate hike", "interest rate hikes",
    "hawkish", "tightening cycle", "emergency rate hike",
    "worse than expected", "miss expectations", "misses estimates",
    "missed estimates", "below expectations", "disappoints",
    "hotter than expected",
    "inflation rises", "inflation rose", "inflation jumps", "inflation surged",
    "inflation accelerates", "inflation surge", "inflation spike",
    "prices rise", "prices surged", "prices jumped",
    "market crash", "flash crash", "market selloff", "market sell-off",
    "stocks plunge", "equities fall sharply",
    "bank collapse", "bank failure", "bank run", "systemic risk",
    "financial crisis", "credit crunch", "contagion",
    "stagflation", "hyperinflation",
    "recession confirmed", "gdp contraction", "gdp shrinks",
    "yield curve inversion", "sovereign default", "debt ceiling",
    "credit downgrade", "rating downgrade",
    "war escalates", "military invasion", "military strike",
    "nuclear threat", "sanctions imposed", "new sanctions",
    "oil supply disruption", "trade war", "tariff escalation",
    "new tariffs", "tariff hike",
    "blockade", "oil blockade", "iran blockade", "naval blockade",
    "supply shock", "supply disruption", "energy crisis",
    "oil embargo", "oil sanctions",
    "oil price rises above", "oil prices above", "crude above",
    "oil hits", "crude hits", "brent hits",
    "mass layoffs", "layoffs announced", "job cuts",
]

# Single words scored ±1 via pre-compiled regex
SENT_WORDS_POS = [
    "rally", "rallies", "rallied", "rallying",
    "surge", "surges", "surged", "surging",
    "gain", "gains", "gained", "gaining",
    "rise", "rises", "rose", "rising",
    "jump", "jumps", "jumped", "jumping",
    "soar", "soars", "soared", "soaring",
    "boom", "booms", "boomed",
    "recovery", "recover", "recovers", "recovered", "recovering",
    "rebound", "rebounds", "rebounded", "rebounding",
    "bullish", "upbeat", "optimism", "optimistic",
    "expansion", "expansionary", "expands", "expanded", "expanding",
    "advance", "advances", "advanced", "advancing",
    "outperform", "outperforms", "outperformed",
    "upgrade", "upgrades", "upgraded",
    "improves", "improved", "improving", "improvement",
    "accelerate", "accelerates", "accelerated", "accelerating",
    "stabilize", "stabilizes", "stabilized", "stabilizing",
    "strengthen", "strengthens", "strengthened", "strengthening",
    "boost", "boosts", "boosted", "boosting",
    "hiring", "hired",
]

SENT_WORDS_NEG = [
    "crash", "crashes", "crashed", "crashing",
    "collapse", "collapses", "collapsed", "collapsing",
    "plunge", "plunges", "plunged", "plunging",
    "tumble", "tumbles", "tumbled", "tumbling",
    "slump", "slumps", "slumped", "slumping",
    "fell", "fallen", "falling",
    "drop", "drops", "dropped", "dropping",
    "decline", "declines", "declined", "declining",
    "weaken", "weakens", "weakened", "weakening", "weakness",
    "bearish", "slowdown", "downturn",
    "layoffs", "contraction", "recessionary",
    "downgrade", "downgrades", "downgraded", "downgrading",
    "underperform", "underperforms", "underperformed",
    "pressured", "pressuring",
    "deteriorate", "deteriorates", "deteriorated", "deteriorating",
    "slipped", "slipping",
    "worsen", "worsens", "worsened", "worsening",
    "shrink", "shrinks", "shrank", "shrinking",
    "contract", "contracts", "contracted", "contracting",
]

# Compile once at import time
_RE_POS = re.compile(r'\b(?:' + '|'.join(re.escape(w) for w in SENT_WORDS_POS) + r')\b')
_RE_NEG = re.compile(r'\b(?:' + '|'.join(re.escape(w) for w in SENT_WORDS_NEG) + r')\b')


def classify_category(text: str) -> str:
    fed_triggers = [
        "federal reserve", "fomc", "powell", "fed meeting", "rate decision",
        "rate hike", "rate cut", "fed statement", "fed holds", "press conference",
    ]
    if any(kw in text for kw in fed_triggers):
        return "Fed/Monetary Policy"
    scores = {cat: sum(1 for kw in kws if kw in text) for cat, kws in CAT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Macro Economy"


def classify_sentiment(text: str) -> str:
    t     = text.lower()
    score = 0
    for phrase in SENT_PHRASES_POS:
        if phrase in t:
            score += 2
    for phrase in SENT_PHRASES_NEG:
        if phrase in t:
            score -= 2
    score += len(_RE_POS.findall(t))
    score -= len(_RE_NEG.findall(t))
    if score > 0:
        return "Positive"
    if score < 0:
        return "Negative"
    return "Neutral"
